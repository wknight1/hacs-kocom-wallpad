"""Kocom 월패드 게이트웨이."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List, Callable

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er, restore_state
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    LOGGER,
    DOMAIN,
    RECV_POLL_SEC,
    IDLE_GAP_SEC,
    SEND_RETRY_MAX,
    SEND_RETRY_GAP,
    DeviceType,
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
        self._tx_queue: asyncio.Queue[_CmdItem] = asyncio.Queue()
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
        LOGGER.info("게이트웨이 시작 - %s:%s", self.host, self.port or "")
        await self.conn.open()
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())

    async def async_stop(self, event: Event | None = None) -> None:
        """게이트웨이를 중지하고 연결을 해제합니다."""
        LOGGER.info("게이트웨이 중지 - %s:%s", self.host, self.port or "")
        if self._task_reader:
            self._task_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_reader
        if self._task_sender:
            self._task_sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_sender
        await self.conn.close()

    def is_idle(self) -> bool:
        """연결이 유휴 상태인지 확인합니다."""
        return self.conn.idle_since() >= IDLE_GAP_SEC

    async def _read_loop(self) -> None:
        """데이터 수신 루프."""
        try:
            LOGGER.debug("수신 루프 시작")
            while True:
                if not self.conn._is_connected():
                    await asyncio.sleep(5)
                    continue
                chunk = await self.conn.recv(512, RECV_POLL_SEC)
                if chunk:
                    self._last_rx_monotonic = asyncio.get_running_loop().time()
                    self.controller.feed(chunk)
        except asyncio.CancelledError:
            LOGGER.debug("수신 루프 취소됨")
            raise

    async def async_send_action(self, key: DeviceKey, action: str, **kwargs) -> bool:
        """디바이스 제어 명령을 전송 큐에 추가합니다.

        Args:
            key (DeviceKey): 대상 디바이스 키
            action (str): 수행할 동작
            **kwargs: 동작 인자

        Returns:
            bool: 명령 수행 성공 여부
        """
        item = _CmdItem(key=key, action=action, kwargs=kwargs)
        await self._tx_queue.put(item)
        try:
            res = await item.future   # 워커가 set_result(True/False)
            return bool(res)
        except asyncio.CancelledError:
            # 정지 중이라면 False로 정리
            if not item.future.done():
                item.future.set_result(False)
            raise

    def on_device_state(self, dev: DeviceState) -> None:
        """디바이스 상태 변경 이벤트 핸들러."""
        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("새로운 디바이스 감지됨. 등록 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_new_device(dev.platform),
                [dev],
            )
            self._notify_pendings(dev)
            return

        if changed:
            LOGGER.debug("디바이스 상태 변경됨. 업데이트 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_device_updated(dev.key.unique_id),
                dev,
            )
        self._notify_pendings(dev)

    @callback
    def async_signal_new_device(self, platform: Platform) -> str:
        """새 디바이스 신호 이름을 생성합니다."""
        return f"{DOMAIN}_new_{platform.value}_{self.host}"

    @callback
    def async_signal_device_updated(self, unique_id: str) -> str:
        """디바이스 업데이트 신호 이름을 생성합니다."""
        return f"{DOMAIN}_updated_{unique_id}"

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        """플랫폼별 디바이스 목록을 가져옵니다."""
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        """엔티티의 복원된 상태 패킷을 처리합니다."""
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
        LOGGER.debug("상태 복원 -> 패킷: %s", packet)
        self.controller._dispatch_packet(bytes.fromhex(packet))
        self._force_register_uid = None
        device_storage = state.extra_data.as_dict().get("device_storage", {})
        LOGGER.debug("상태 복원 -> 저장소: %s", device_storage)
        self.controller._device_storage = device_storage

    async def async_get_entity_registry(self) -> None:
        """엔티티 레지스트리에서 이전 상태를 복원합니다."""
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
                # predicate 내부 오류 방어
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
            # 타임아웃 등으로 끝났을 때 누수 방지
            if waiter in self._pendings:
                try:
                    self._pendings.remove(waiter)
                except ValueError:
                    pass

    async def _sender_loop(self) -> None:
        """송신 큐 처리 루프 (재시도 및 동기화 로직 포함)."""
        LOGGER.debug("송신 루프 시작")
        try:
            while True:
                item = await self._tx_queue.get()
                if item is None:
                    continue

                # generate packet & expect predicate
                try:
                    packet, expect_predicate, timeout = self.controller.generate_command(
                        item.key, item.action, **item.kwargs
                    )
                except Exception as e:
                    LOGGER.exception("명령 생성 실패: %s", e)
                    if not item.future.done():
                        item.future.set_result(False)
                    self._tx_queue.task_done()
                    continue

                # 재시도 루프
                success = False
                for attempt in range(1, SEND_RETRY_MAX + 1):
                    # idle 대기 (최대 1초)
                    LOGGER.debug("TX 유휴 대기 (최대 1.0s) - '%s'...", item.action)
                    t0 = asyncio.get_running_loop().time()
                    while not self.is_idle():
                        await asyncio.sleep(0.01)
                        if asyncio.get_running_loop().time() - t0 > 1.0:
                            LOGGER.debug("유휴 대기 타임아웃 (%.2fs).", asyncio.get_running_loop().time() - t0)
                            break

                    # 연결 확인
                    if not self.conn._is_connected():
                        LOGGER.warning("연결 준비 안됨. '%s' 중단.", item.action)
                        break

                    # 전송
                    try:
                        await self.conn.send(packet)
                    except Exception as e:
                        LOGGER.warning("전송 실패 (시도 %d): %s", attempt, e)
                        if attempt < SEND_RETRY_MAX:
                            await asyncio.sleep(SEND_RETRY_GAP)
                            continue
                        else:
                            break

                    self._last_tx_monotonic = asyncio.get_running_loop().time()

                    # 확인 대기
                    try:
                        _ = await self._wait_for_confirmation(item.key, expect_predicate, timeout)
                        LOGGER.debug("명령 '%s' 확인됨 (시도 %d).", item.action, attempt)
                        success = True
                        break
                    except asyncio.TimeoutError:
                        if attempt < SEND_RETRY_MAX:
                            LOGGER.warning(
                                "'%s' 응답 없음 (시도 %d/%d). %.2fs 후 재시도...",
                                item.action, attempt, SEND_RETRY_MAX, SEND_RETRY_GAP
                            )
                            await asyncio.sleep(SEND_RETRY_GAP)
                        else:
                            LOGGER.error("명령 '%s' 실패 (%d회 시도).", item.action, SEND_RETRY_MAX)

                if success:
                    self._consecutive_failures = 0
                    if item.action != "query":
                        # Immediate Polling: Force state sync after success
                        try:
                            q_packet, q_expect, q_timeout = self.controller.generate_command(item.key, "query")
                            LOGGER.debug("동기화를 위한 즉시 쿼리 패킷 전송...")
                            await self.conn.send(q_packet)
                            await self._wait_for_confirmation(item.key, q_expect, q_timeout)
                            LOGGER.debug("즉시 쿼리 확인됨.")
                        except Exception as e:
                            LOGGER.debug("즉시 쿼리 실패 (비치명적): %s", e)
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 5:
                        LOGGER.warning("연속 실패 과다 (%d). 연결 강제 재수립.", self._consecutive_failures)
                        await self.conn.reconnect()
                        self._consecutive_failures = 0

                if not item.future.done():
                    item.future.set_result(success)

                self._tx_queue.task_done()
        except asyncio.CancelledError:
            LOGGER.debug("송신 루프 취소됨")
            raise
