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
from .transport import AsyncConnection
from .controller import KocomController


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
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None
        self._consecutive_failures: int = 0

    async def async_start(self) -> None:
        """게이트웨이를 시작하고 통신 루프를 가동합니다."""
        LOGGER.info("Gateway: 서비스를 시작합니다. (%s:%s)", self.host, self.port or "Serial")
        await self.conn.open()
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())

    async def async_stop(self, event: Event | None = None) -> None:
        """게이트웨이를 중지하고 모든 자원을 해제합니다."""
        LOGGER.info("Gateway: 서비스를 중지합니다.")
        
        # 송신 루프 중지
        if self._task_sender:
            self._task_sender.cancel()
            try:
                await asyncio.wait_for(self._task_sender, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task_sender = None

        # 수신 루프 중지
        if self._task_reader:
            self._task_reader.cancel()
            try:
                await asyncio.wait_for(self._task_reader, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task_reader = None

        # 대기 중인 모든 Future 취소
        for p in self._pendings:
            if not p.future.done():
                p.future.set_exception(asyncio.CancelledError())
        self._pendings.clear()

        # 연결 종료
        await self.conn.close()

    def is_idle(self) -> bool:
        """연결이 유휴 상태인지 확인합니다."""
        return self.conn.idle_since() >= IDLE_GAP_SEC

    async def async_send_action(self, key: DeviceKey, action: str, **kwargs) -> bool:
        """디바이스 제어 명령을 전송 큐에 추가합니다.

        Args:
            key (DeviceKey): 대상 디바이스 키
            action (str): 수행할 동작
            **kwargs: 동작 인자

        Returns:
            bool: 명령 수행 성공 여부
        """
        if self._tx_queue.full():
            LOGGER.warning("Gateway: 송신 큐가 가득 찼습니다 (Backpressure). 명령을 거부합니다: %s", action)
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
            LOGGER.error("Gateway: 명령 실행 중 예외 발생: %s", e)
            return False

    def on_device_state(self, dev: DeviceState) -> None:
        """디바이스 상태 변경 이벤트 핸들러."""
        from .const import DeviceType
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("Gateway: 새로운 디바이스 감지됨. 등록 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_new_device(dev.platform),
                [dev],
            )
            self._notify_pendings(dev)
            return

        if changed:
            LOGGER.debug("Gateway: 디바이스 상태 변경됨. 업데이트 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_device_updated(dev.key.unique_id),
                dev,
            )
        self._notify_pendings(dev)

    def async_signal_new_device(self, platform: Platform) -> str:
        """새 디바이스 신호 이름을 생성합니다."""
        from .const import DOMAIN
        return f"{DOMAIN}_new_{platform.value}_{self.host}"

    def async_signal_device_updated(self, unique_id: str) -> str:
        """디바이스 업데이트 신호 이름을 생성합니다."""
        from .const import DOMAIN
        return f"{DOMAIN}_updated_{unique_id}"

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        """플랫폼별 디바이스 목록을 가져옵니다."""
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        """엔티티의 복원된 상태 패킷을 처리합니다."""
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
        LOGGER.debug("Gateway: 상태 복원 -> 패킷: %s", packet)
        self.controller._dispatch_packet(bytes.fromhex(packet))
        self._force_register_uid = None
        device_storage = state.extra_data.as_dict().get("device_storage", {})
        LOGGER.debug("Gateway: 상태 복원 -> 저장소: %s", device_storage)
        self.controller._device_storage = device_storage

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
        """대기 중인 명령에 상태 업데이트를 알립니다."""
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
        """명령 수행 후 상태 변경을 기다립니다."""
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

    async def _read_loop(self) -> None:
        """데이터 수신 루프 (안전 모드 적용)."""
        LOGGER.info("Gateway: 수신(Read) 루프가 시작되었습니다.")
        try:
            while True:
                try:
                    # 연결 상태 확인 및 재연결
                    if not self.conn._is_connected():
                        LOGGER.debug("Gateway: 연결이 끊겨 있습니다. 재연결 시도...")
                        await self.conn.reconnect()
                        continue
                    
                    # 수신 대기 (블로킹 방지)
                    chunk = await self.conn.recv(512, RECV_POLL_SEC)
                    if chunk:
                        self._last_rx_monotonic = asyncio.get_running_loop().time()
                        self.controller.feed(chunk)
                    else:
                        # 데이터가 없거나 EOF 발생 시 (recv에서 _connected=False 처리됨)
                        # 아주 짧게 대기하여 CPU 과점유 방지
                        await asyncio.sleep(0.01)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    LOGGER.exception("Gateway: 수신 루프 중 치명적 오류 발생: %s", e)
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            LOGGER.info("Gateway: 수신 루프가 정상적으로 종료되었습니다.")
            raise

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
                    
                    # generate packet & expect predicate
                    packet, expect_predicate, timeout = self.controller.generate_command(
                        item.key, item.action, **item.kwargs
                    )
                except Exception as e:
                    LOGGER.error("Gateway: 명령 생성 실패 (건너뜀): %s", e)
                    if not item.future.done():
                        item.future.set_result(False)
                    self._tx_queue.task_done()
                    continue

                # 재시도 루프
                success = False
                for attempt in range(1, SEND_RETRY_MAX + 1):
                    try:
                        # idle 대기 (최대 1초)
                        t0 = asyncio.get_running_loop().time()
                        while not self.is_idle():
                            await asyncio.sleep(0.01)
                            if asyncio.get_running_loop().time() - t0 > 1.0:
                                LOGGER.debug("Gateway: 유휴 대기 타임아웃")
                                break

                        # 연결 확인
                        if not self.conn._is_connected():
                            LOGGER.warning("Gateway: 연결 미수립 상태. 명령 중단.")
                            break

                        # 전송
                        await self.conn.send(packet)
                        self._last_tx_monotonic = asyncio.get_running_loop().time()

                        # 확인 대기
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

                # 결과 처리
                if success:
                    self._consecutive_failures = 0
                    if item.action != "query":
                        # 즉시 동기화 시도 (실패해도 무방하도록 try-except 감싸기)
                        try:
                            q_packet, q_expect, q_timeout = self.controller.generate_command(item.key, "query")
                            await self.conn.send(q_packet)
                            await self._wait_for_confirmation(item.key, q_expect, q_timeout)
                        except Exception:
                            pass # 동기화 실패는 무시
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
            LOGGER.info("Gateway: 송신 루프가 정상적으로 종료되었습니다.")
            raise
        except Exception as e:
            LOGGER.critical("Gateway: 송신 루프 붕괴 (재시작 필요): %s", e)
            # 여기서 raise하면 태스크가 죽음. 필요 시 self-healing 로직 추가 가능.
