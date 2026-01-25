"""Kocom 월패드를 위한 전송 계층."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import asyncio
import time

from .const import LOGGER


@dataclass
class AsyncConnection:
    """비동기 연결 관리자 (TCP/Serial)."""
    host: str
    port: Optional[int]
    serial_baud: int = 9600
    connect_timeout: float = 5.0
    reconnect_backoff: Tuple[float, float] = (1.0, 30.0)  # min, max seconds

    def __post_init__(self) -> None:
        """연결 객체를 초기화합니다."""
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_activity_mono: float = time.monotonic()
        self._last_recv_mono: float = time.monotonic()
        self._last_reconn_delay: float = 0.0
        self._connected = False
        self._reconnect_lock = asyncio.Lock()

    async def open(self) -> None:
        """연결을 수립합니다 (TCP 또는 Serial)."""
        if self._is_connected():
            return

        # 이전 연결이 완전히 닫히고 서버(EW11) 측 세션이 정리될 시간을 확보
        await asyncio.sleep(0.1)
        
        LOGGER.debug("Transport: 연결 시도 중... (Host: %s, Port: %s)", self.host, self.port)
        try:
            if self.port is None:
                # 성능 개선된 fast 라이브러리 사용
                import serial_asyncio_fast
                self._reader, self._writer = await serial_asyncio_fast.open_serial_connection(
                    url=self.host, baudrate=self.serial_baud
                )
                LOGGER.info("Transport: 시리얼 연결 성공: %s", self.host)
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.connect_timeout,
                )
                LOGGER.info("Transport: 소켓 연결 성공: %s:%s", self.host, self.port)
            self._connected = True
            self._touch()
            self._touch_recv()
        except Exception as e:
            LOGGER.error("Transport: 연결 실패 (%s): %r", self.host, e)
            await self.close()
            raise

    async def close(self) -> None:
        """연결을 종료하고 자원을 정리합니다."""
        self._connected = False
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=1.0)
            except Exception:
                pass
            finally:
                self._writer = None
        self._reader = None
        LOGGER.debug("Transport: 자원 정리 완료 (%s)", self.host)

    def _is_connected(self) -> bool:
        """연결이 유효한지 확인합니다."""
        return self._connected and self._reader is not None and self._writer is not None

    def _touch(self) -> None:
        """활동 시간을 업데이트합니다."""
        self._last_activity_mono = time.monotonic()

    def _touch_recv(self) -> None:
        """수신 시간을 업데이트합니다."""
        self._last_recv_mono = time.monotonic()

    def idle_since(self) -> float:
        """마지막 활동 이후 시간(초)을 반환합니다."""
        return max(0.0, time.monotonic() - self._last_activity_mono)

    def recv_idle_since(self) -> float:
        """마지막 유효 패킷 수신 이후 시간(초)을 반환합니다."""
        return max(0.0, time.monotonic() - self._last_recv_mono)

    async def send(self, data: bytes) -> int:
        """데이터를 전송합니다."""
        if not self._is_connected():
            return 0
        try:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=2.0)
            self._touch()
            return len(data)
        except Exception as e:
            LOGGER.warning("Transport: 전송 실패 (%s): %r", self.host, e)
            await self.close()
            return 0

    async def recv(self, nbytes: int, timeout: float = 0.05) -> bytes:
        """데이터를 수신합니다."""
        if not self._is_connected():
            return b""
        
        try:
            chunk = await asyncio.wait_for(self._reader.read(nbytes), timeout=timeout)
            
            if chunk == b"":
                # EOF 감지 시 즉시 자원 정리 및 상태 변경
                LOGGER.debug("Transport: 원격 호스트에서 세션 종료 (EOF) - %s", self.host)
                await self.close()
                return b""
                
            self._touch()
            self._touch_recv()
            return chunk
            
        except asyncio.TimeoutError:
            return b""
        except Exception as e:
            if self._connected:
                LOGGER.warning("Transport: 수신 오류 (%s): %r", self.host, e)
                await self.close()
            return b""

    async def reconnect(self) -> None:
        """연결을 안전하게 재수립합니다."""
        if self._reconnect_lock.locked():
            return

        async with self._reconnect_lock:
            if self._is_connected():
                return

            await self.close()
            
            delay_min, delay_max = self.reconnect_backoff
            delay = self._last_reconn_delay if self._last_reconn_delay > 0.0 else delay_min
            
            LOGGER.info("Transport: %.1f초 후 재연결 시도 (%s)", delay, self.host)
            await asyncio.sleep(delay)
            
            self._last_reconn_delay = min(delay * 2, delay_max)
            
            try:
                await self.open()
                if self._is_connected():
                    LOGGER.info("Transport: 재연결 성공 (%s)", self.host)
                    self._last_reconn_delay = delay_min
            except Exception:
                pass
