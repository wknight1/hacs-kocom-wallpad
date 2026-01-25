"""Kocom 월패드 게이트웨이."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List, Callable

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import (
    LOGGER,
    RECV_POLL_SEC,
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
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None
        self._consecutive_failures: int = 0

    async def async_start(self) -> None:
        """게이트웨이를 시작하고 통신 루프를 가동합니다."""
        LOGGER.info("Gateway: 서비스를 시작합니다. (%s:%s)", self.host, self.port or "Serial")
        try:
            await self.conn.open()
        except Exception as e:
            LOGGER.error("Gateway: 초기 연결 실패 (백그라운드에서 재시도): %s", e)
            
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())
        
        # 기기 탐색 강제 실행 (연결 후 잠시 대기)
        asyncio.create_task(self._force_discovery())

    async def _force_discovery(self) -> None:
        """시스템 부팅 시 모든 기기 상태를 강제로 조회하여 탐색합니다."""
        await asyncio.sleep(5)  # 연결 안정화 대기
        if not self.conn._is_connected():
            return
            
        LOGGER.info("Gateway: 기기 탐색(Discovery)을 시작합니다.")
        from .models import DeviceKey, SubType
        from .const import DeviceType
        
        # 주요 기기 타입들에 대해 룸 0번부터 조회를 날림 (일반적인 구성 기준)
        # 실제 환경에 맞춰 확장이 필요할 수 있음
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
                    if not self.conn._is_connected():
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
