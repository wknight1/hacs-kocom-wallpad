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
        self._last_reconn_delay: float = 0.0
        self._connected = True

    async def open(self) -> None:
        """연결을 수립합니다 (TCP 또는 Serial)."""
        LOGGER.debug("Transport: 연결 시도 중... (Host: %s, Port: %s)", self.host, self.port)
        try:
            if self.port is None:
                # Lazy import to prevent blocking issues on startup
                import serial_asyncio
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
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
        except asyncio.TimeoutError:
            LOGGER.error("Transport: 연결 타임아웃 발생 (%s초)", self.connect_timeout)
            await self.reconnect()
        except Exception as e:
            LOGGER.exception("Transport: 연결 중 오류 발생: %r", e)
            await self.reconnect()

    async def close(self) -> None:
        """연결을 종료합니다."""
        if self._writer is not None:
            LOGGER.debug("Transport: 연결 종료 시작")
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception as e:
                LOGGER.debug("Transport: 종료 중 예외 (무시됨): %r", e)
            finally:
                self._writer = None
        self._reader = None
        self._connected = False
        LOGGER.info("Transport: 연결이 완전히 종료되었습니다.")

    def _is_connected(self) -> bool:
        """현재 연결 상태를 반환합니다."""
        return self._connected and self._writer is not None

    def _touch(self) -> None:
        """마지막 활동 시간을 갱신합니다."""
        self._last_activity_mono = time.monotonic()

    def idle_since(self) -> float:
        """마지막 활동 이후 경과된 시간을 반환합니다 (초)."""
        return max(0.0, time.monotonic() - self._last_activity_mono)

    async def send(self, data: bytes) -> int:
        """데이터를 전송합니다."""
        if not self._is_connected():
            LOGGER.debug("Transport: 전송 시도 중 연결 끊김 발견 -> 재연결")
            await self.reconnect()
            return 0
        try:
            # LOGGER.debug("Transport: 전송 -> %s", data.hex())
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=2.0)
            self._touch()
            return len(data)
        except Exception as e:
            LOGGER.warning("Transport: 전송 실패: %r", e)
            await self.reconnect()
            return 0

    async def recv(self, nbytes: int, timeout: float = 0.05) -> bytes:
        """데이터를 수신합니다."""
        if not self._reader:
            return b""
        
        try:
            chunk = await asyncio.wait_for(self._reader.read(nbytes), timeout=timeout)
            
            if chunk == b"":
                # EOF(End of File)은 소켓 연결이 끊어졌음을 의미
                LOGGER.warning("Transport: 원격 호스트에서 연결 종료 감지 (EOF)")
                await self.reconnect()
                return b""
                
            self._touch()
            return chunk
            
        except asyncio.TimeoutError:
            return b""
        except Exception as e:
            LOGGER.warning("Transport: 수신 오류 발생: %r", e)
            await self.reconnect()
            return b""

    async def reconnect(self) -> None:
        """연결을 재수립합니다 (지수 백오프 적용)."""
        if not self._connected and self._writer is None:
            # 이미 재연결 루틴이 진행 중임
            return

        self._connected = False
        delay_min, delay_max = self.reconnect_backoff
        delay = self._last_reconn_delay if self._last_reconn_delay > 0.0 else delay_min

        await self.close()
        
        LOGGER.info("Transport: %.1f초 후 재연결을 시도합니다. (백오프 진행 중)", delay)
        await asyncio.sleep(delay)
        
        self._last_reconn_delay = min(delay * 2, delay_max)
        await self.open()

        if self._is_connected():
            LOGGER.info("Transport: 재연결에 성공했습니다.")
            self._last_reconn_delay = delay_min
