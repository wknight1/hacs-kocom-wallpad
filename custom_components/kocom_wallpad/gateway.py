"""Kocom 월패드 게이트웨이."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import (
    LOGGER,
    RECV_POLL_SEC,
    IDLE_GAP_SEC,
    SEND_RETRY_MAX,
    SEND_RETRY_GAP,
)
from .models import DeviceKey, DeviceState


@dataclass(slots=True)
class _CmdItem:
    """명령 큐 아이템."""
    key: DeviceKey
    action: str
    kwargs: dict
    future: asyncio.Future = field(default_factory=asyncio.get_running_loop().create_future)


class _PendingWaiter:
    """응답 대기자."""

    __slots__ = ("key", "predicate", "future")

    def __init__(
        self, 
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        loop: asyncio.AbstractEventLoop
    ) -> None:
        self.key = key
        self.predicate = predicate
        self.future: asyncio.Future[DeviceState] = loop.create_future()


class EntityRegistry:
    """인메모리 엔티티 레지스트리 (게이트웨이 내부용)."""

    def __init__(self) -> None:
        """레지스트리를 초기화합니다."""
        self._states: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self._shadow: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self.by_platform: Dict[Platform, Dict[str, DeviceState]] = {}

    def upsert(self, dev: DeviceState, allow_insert: bool = True) -> tuple[bool, bool]:
        """디바이스 상태를 업데이트하거나 삽입합니다.

        Args:
            dev (DeviceState): 디바이스 상태 객체
            allow_insert (bool): 새 디바이스일 경우 삽입 허용 여부

        Returns:
            tuple[bool, bool]: (신규 삽입 여부, 변경 여부)
        """
        k = dev.key.key
        old = self._states.get(k)
        is_new = old is None

        if is_new and not allow_insert:
            return False, False
        if is_new:
            self._states[k] = dev
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            return True, True

        platform_changed = (old.platform != dev.platform)
        state_changed = (old.state != dev.state)
        attr_changed = (old.attribute != dev.attribute)
        changed = platform_changed or state_changed or attr_changed

        if changed:
            if platform_changed:
                self.by_platform.get(old.platform, {}).pop(old.key.unique_id, None)
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            self._states[k] = dev
        return False, changed

    def get(self, key: DeviceKey, include_shadow: bool = False) -> Optional[DeviceState]:
        """디바이스 상태를 조회합니다."""
        dev = self._states.get(key.key)
        if dev is None and include_shadow:
            return self._shadow.get(key.key)
        return dev

    def promote(self, key: DeviceKey) -> bool:
        """섀도우(임시) 상태를 실제 엔티티 생성 대상으로 승격합니다."""
        k = key.key
        dev = self._shadow.pop(k, None)
        if dev is None:
            return False
        self._states[k] = dev
        self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
        return True

    def all_by_platform(self, platform: Platform) -> List[DeviceState]:
        """특정 플랫폼의 모든 디바이스를 반환합니다."""
        return list(self.by_platform.get(platform, {}).values())


class KocomGateway:
    """Kocom 월패드 통합 관리 허브.

    연결 관리, 수신 루프, 송신 큐, 엔티티 레지스트리를 총괄합니다.
    """

    def __init__(
        self, 
        hass: HomeAssistant, 
        entry: ConfigEntry,
        host: str,
        port: int | None
    ) -> None:
        """게이트웨이를 초기화합니다."""
        from .transport import AsyncConnection
        from .controller import KocomController

        self.hass = hass
        self.entry = entry
        self.host = host
        self.port = port
        self.conn = AsyncConnection(host=host, port=port)
        self.controller = KocomController(self)
        self.registry = EntityRegistry()
        self._tx_queue: asyncio.Queue[_CmdItem] = asyncio.Queue(maxsize=50)  # 최대 큐 크기 제한
        self._task_reader: asyncio.Task | None = None
        self._task_sender: asyncio.Task | None = None
        self._task_heartbeat: asyncio.Task | None = None
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None
        self._consecutive_failures: int = 0

    async def _async_register_gateway_device(self) -> None:
        """게이트웨이 자체를 HA 장치 레지스트리에 등록합니다 (via_device 이슈 해결)."""
        from homeassistant.helpers import device_registry as dr
        from .const import DOMAIN
        
        dev_reg = dr.async_get(self.hass)
        dev_reg.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.host)},
            manufacturer="KOCOM Co., Ltd",
            model="EW11 Wallpad Gateway",
            name=f"Kocom Gateway ({self.host})",
            configuration_url=f"http://{self.host}" if self.port else None
        )
        LOGGER.debug("Gateway: 기기 레지스트리 등록 완료 (%s)", self.host)

    async def async_start(self) -> None:
        """게이트웨이를 시작하고 통신 루프를 가동합니다."""
        LOGGER.info("Gateway: 서비스를 시작합니다. (%s:%s)", self.host, self.port or "Serial")
        
        # 1. 게이트웨이 기기 등록 (최우선)
        await self._async_register_gateway_device()
        
        # 2. 연결 시도
        try:
            await self.conn.open()
        except Exception as e:
            LOGGER.error("Gateway: 초기 연결 실패 (백그라운드에서 재시도): %s", e)
            
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())
        self._task_heartbeat = asyncio.create_task(self._heartbeat_loop())
        
        # 기기 탐색 강제 실행
        asyncio.create_task(self._force_discovery())

    def is_available(self) -> bool:
        """현재 월패드 통신이 가용한지 판단합니다 (10분 이상 무반응 시 불가)."""
        if not self.conn._is_connected():
            return False
        # 월패드로부터 10분(600초) 이상 패킷이 없으면 가용성 상실로 간주
        if self.conn.recv_idle_since() > 600:
            return False
        return True

    async def _heartbeat_loop(self) -> None:
        """EW11 소켓 및 월패드 전원 상태 감시 루프."""
        while True:
            try:
                await asyncio.sleep(25)
                if not self.conn._is_connected():
                    continue
                
                # 가용성 체크 (로깅)
                if not self.is_available():
                    LOGGER.warning("Gateway: 월패드 무반응 상태 감지 (버스가 조용하거나 전원이 꺼짐).")

                idle_time = min(
                    asyncio.get_running_loop().time() - self._last_rx_monotonic,
                    asyncio.get_running_loop().time() - self._last_tx_monotonic
                )
                
                if idle_time > 20:
                    # LOGGER.debug("Gateway: 유휴 상태 감지 (%.1fs). 하트비트 송신.", idle_time)
                    # from .models import DeviceKey, SubType
                    # from .const import DeviceType
                    # 하트비트 기능 비활성화 (주기적 비프음 방지)
                    # key = DeviceKey(DeviceType.GASVALVE, 0, 0, SubType.NONE)
                    # try:
                    #     packet, _, _ = self.controller.generate_command(key, "query")
                    #     await self.conn.send(packet)
                    # except Exception:
                    #     pass
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.debug("Gateway: 하트비트 루프 예외: %s", e)

    async def _force_discovery(self) -> None:
        """시스템 부팅 시 모든 기기 상태를 강제로 조회하여 탐색합니다."""
        await asyncio.sleep(5)  # 연결 안정화 대기
        if not self.conn._is_connected():
            return
            
        LOGGER.info("Gateway: 기기 탐색(Discovery)을 시작합니다.")
        from .models import DeviceKey, SubType
        from .const import DeviceType
        
        # 주요 기기 타입들에 대해 룸 0번부터 조회를 날림
        for dt in [DeviceType.LIGHT, DeviceType.THERMOSTAT, DeviceType.VENTILATION, DeviceType.AIRCONDITIONER]:
            for room in range(5):  # 룸 0~4번까지 시도
                key = DeviceKey(device_type=dt, room_index=room, device_index=0, sub_type=SubType.NONE)
                await self.async_send_action(key, "query")
                await asyncio.sleep(0.5)  # 버스 부하 방지
        
        LOGGER.info("Gateway: 기기 탐색 프로세스 완료.")

    async def _read_loop(self) -> None:
        """데이터 수신 루프 (안전 모드 적용)."""
        LOGGER.info("Gateway: 수신(Read) 루프 가동.")
        while True:
            try:
                # 연결 상태 확인 및 재연결
                if not self.conn._is_connected():
                    await self.conn.reconnect()
                    if self.conn._is_connected():
                        # 네트워크 복구 직후 기기 상태 재검색 (공유기 재부팅 대응)
                        LOGGER.info("Gateway: 네트워크 복구 감지. 기기 상태 재동기화 시작.")
                        asyncio.create_task(self._force_discovery())
                    else:
                        await asyncio.sleep(5)
                        continue
                
                # 수신 대기
                chunk = await self.conn.recv(512, RECV_POLL_SEC)
                if chunk:
                    self._last_rx_monotonic = asyncio.get_running_loop().time()
                    self.controller.feed(chunk)
                else:
                    await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                LOGGER.info("Gateway: 수신 루프 종료.")
                break
            except Exception as e:
                LOGGER.exception("Gateway: 수신 루프 예외 발생: %s", e)
                await asyncio.sleep(1)

    async def _sender_loop(self) -> None:
        """송신 큐 처리 루프 (안전 모드 적용)."""
        LOGGER.info("Gateway: 송신(Sender) 루프가 시작되었습니다.")
        try:
            while True:
                item = await self._tx_queue.get()
                if item is None:
                    continue

                try:
                    LOGGER.debug("Gateway: 명령 처리 시작 - Action: %s, Key: %s", item.action, item.key)
                    packet, expect_predicate, timeout = self.controller.generate_command(
                        item.key, item.action, **item.kwargs
                    )
                except Exception as e:
                    LOGGER.error("Gateway: 명령 생성 실패 (건너뜀): %s", e)
                    if not item.future.done():
                        item.future.set_result(False)
                    self._tx_queue.task_done()
                    continue

                success = False
                for attempt in range(1, SEND_RETRY_MAX + 1):
                    try:
                        t0 = asyncio.get_running_loop().time()
                        while not self.is_idle():
                            await asyncio.sleep(0.01)
                            if asyncio.get_running_loop().time() - t0 > 1.0:
                                LOGGER.debug("Gateway: 유휴 대기 타임아웃")
                                break

                        if not self.conn._is_connected():
                            LOGGER.warning("Gateway: 연결 미수립 상태. 명령 중단.")
                            break

                        await self.conn.send(packet)
                        self._last_tx_monotonic = asyncio.get_running_loop().time()
                        await self._wait_for_confirmation(item.key, expect_predicate, timeout)
                        LOGGER.debug("Gateway: 명령 성공 (시도 %d회)", attempt)
                        success = True
                        break

                    except asyncio.TimeoutError:
                        LOGGER.warning("Gateway: 명령 응답 없음 (시도 %d/%d)", attempt, SEND_RETRY_MAX)
                        if attempt < SEND_RETRY_MAX:
                            await asyncio.sleep(SEND_RETRY_GAP)
                    except Exception as tx_err:
                        LOGGER.exception("Gateway: 송신 시도 중 오류: %s", tx_err)
                        await asyncio.sleep(SEND_RETRY_GAP)

                if success:
                    self._consecutive_failures = 0
                    # 명령 성공 후 즉시 상태 조회(query)를 날리는 로직 제거
                    # 이유: 에어컨 등 일부 기기에서 제어 명령 직후 쿼리 수신 시 비프음이 중복(2회) 발생함.
                    # 대부분의 RS485 기기는 제어 명령에 대한 응답으로 상태를 반환하므로,
                    # 앞선 _wait_for_confirmation 단계에서 이미 상태가 업데이트되었을 가능성이 높음.
                else:
                    self._consecutive_failures += 1
                    LOGGER.error("Gateway: 명령 최종 실패 (연속 실패: %d회)", self._consecutive_failures)
                    if self._consecutive_failures >= 5:
                        LOGGER.error("Gateway: 연속 실패 과다. 연결 재설정 트리거.")
                        asyncio.create_task(self.conn.reconnect())
                        self._consecutive_failures = 0

                if not item.future.done():
                    item.future.set_result(success)
                self._tx_queue.task_done()

        except asyncio.CancelledError:
            LOGGER.info("Gateway: 송신 루프 정상 종료.")
            raise
        except Exception as e:
            LOGGER.critical("Gateway: 송신 루프 치명적 오류: %s", e)

    async def async_stop(self, event: Event | None = None) -> None:
        """게이트웨이를 중지하고 모든 자원을 해제합니다."""
        LOGGER.info("Gateway: 서비스를 중지합니다.")
        
        if self._task_heartbeat:
            self._task_heartbeat.cancel()
            try:
                await asyncio.wait_for(self._task_heartbeat, timeout=1.0)
            except Exception:
                pass
            self._task_heartbeat = None

        if self._task_sender:
            self._task_sender.cancel()
            try:
                await asyncio.wait_for(self._task_sender, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task_sender = None

        if self._task_reader:
            self._task_reader.cancel()
            try:
                await asyncio.wait_for(self._task_reader, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task_reader = None

        for p in self._pendings:
            if not p.future.done():
                p.future.set_exception(asyncio.CancelledError())
        self._pendings.clear()
        await self.conn.close()

    def is_idle(self) -> bool:
        """연결이 유휴 상태인지 확인합니다."""
        return self.conn.idle_since() >= IDLE_GAP_SEC

    async def async_send_action(self, key: DeviceKey, action: str, **kwargs) -> bool:
        """디바이스 제어 명령을 전송 큐에 추가합니다."""
        if self._tx_queue.full():
            LOGGER.warning("Gateway: 송신 큐 가득 참 (Backpressure). 거부: %s", action)
            return False

        item = _CmdItem(key=key, action=action, kwargs=kwargs)
        try:
            await self._tx_queue.put(item)
            res = await item.future
            return bool(res)
        except asyncio.CancelledError:
            if not item.future.done():
                item.future.set_result(False)
            raise
        except Exception as e:
            LOGGER.error("Gateway: 명령 실행 오류: %s", e)
            return False

    def on_device_state(self, dev: DeviceState) -> None:
        """디바이스 상태 변경 이벤트 핸들러."""
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .const import DeviceType

        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("Gateway: 새 디바이스 감지됨. 등록 -> %s", dev.key)
            async_dispatcher_send(self.hass, self.async_signal_new_device(dev.platform), [dev])
            self._notify_pendings(dev)
            return

        if changed:
            LOGGER.debug("Gateway: 상태 변경됨. 업데이트 -> %s", dev.key)
            async_dispatcher_send(self.hass, self.async_signal_device_updated(dev.key.unique_id), dev)
        self._notify_pendings(dev)

    def async_signal_new_device(self, platform: Platform) -> str:
        from .const import DOMAIN
        return f"{DOMAIN}_new_{platform.value}_{self.host}"

    def async_signal_device_updated(self, unique_id: str) -> str:
        from .const import DOMAIN
        return f"{DOMAIN}_updated_{unique_id}"

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        from homeassistant.helpers import entity_registry as er, restore_state
        state = restore_state.async_get(self.hass).last_states.get(entity_id)
        if not (state and state.extra_data):
            return
        packet = state.extra_data.as_dict().get("packet")
        if not packet:
            return
        ent_reg = er.async_get(self.hass)
        ent_entry = ent_reg.async_get(entity_id)
        if ent_entry and ent_entry.unique_id:
            self._force_register_uid = ent_entry.unique_id.split(":")[0]
        self.controller._dispatch_packet(bytes.fromhex(packet))
        self._force_register_uid = None
        self.controller._device_storage = state.extra_data.as_dict().get("device_storage", {})

    async def async_get_entity_registry(self) -> None:
        """엔티티 레지스트리에서 이전 상태를 복원합니다."""
        from homeassistant.helpers import entity_registry as er
        self._restore_mode = True
        try:
            entity_registry = er.async_get(self.hass)
            entities = er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
            for entity in entities:
                await self._async_put_entity_dispatch_packet(entity.entity_id)
        finally:
            self._restore_mode = False

    def _notify_pendings(self, dev: DeviceState) -> None:
        if not self._pendings:
            return
        hit: list[_PendingWaiter] = []
        for p in self._pendings:
            try:
                if p.key.key == dev.key.key and p.predicate(dev):
                    hit.append(p)
            except Exception:
                continue
        if hit:
            for p in hit:
                if not p.future.done():
                    p.future.set_result(dev)
                try:
                    self._pendings.remove(p)
                except ValueError:
                    pass

    async def _wait_for_confirmation(
        self,
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        timeout: float,
    ) -> DeviceState:
        loop = asyncio.get_running_loop()
        waiter = _PendingWaiter(key, predicate, loop)
        self._pendings.append(waiter)
        try:
            return await asyncio.wait_for(waiter.future, timeout=timeout)
        finally:
            if waiter in self._pendings:
                try:
                    self._pendings.remove(waiter)
                except ValueError:
                    pass