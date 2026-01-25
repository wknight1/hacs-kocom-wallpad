"""Kocom 월패드를 위한 전송 계층."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import asyncio
import serial_asyncio
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
        try:
            if self.port is None:
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self.host, baudrate=self.serial_baud
                )
                LOGGER.info("시리얼 연결 성공: %s", self.host)
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.connect_timeout,
                )
                LOGGER.info("소켓 연결 성공: %s:%s", self.host, self.port)
            self._connected = True
            self._touch()
        except Exception as e:
            LOGGER.warning("연결 실패: %r", e)
            await self.reconnect()

    async def close(self) -> None:
        """연결을 종료합니다."""
        if self._writer is not None:
            LOGGER.info("연결 종료 중...")
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            finally:
                self._writer = None
        self._reader = None
        self._connected = False

    def _is_connected(self) -> bool:
        """현재 연결 상태를 반환합니다."""
        return self._connected

    def _touch(self) -> None:
        """마지막 활동 시간을 갱신합니다."""
        self._last_activity_mono = time.monotonic()

    def idle_since(self) -> float:
        """마지막 활동 이후 경과된 시간을 반환합니다 (초)."""
        return max(0.0, time.monotonic() - self._last_activity_mono)

    async def send(self, data: bytes) -> int:
        """데이터를 전송합니다.

        Args:
            data (bytes): 전송할 데이터

        Returns:
            int: 전송된 바이트 수 (실패 시 0)
        """
        if not self._writer:
            raise RuntimeError("연결이 열려있지 않습니다")
        try:
            LOGGER.debug("전송: %s", data.hex())
            self._writer.write(data)
            await self._writer.drain()
            self._touch()
            return len(data)
        except Exception as e:
            LOGGER.warning("전송 실패: %r", e)
            await self.reconnect()
            return 0

    async def recv(self, nbytes: int, timeout: float = 0.05) -> bytes:
        """데이터를 수신합니다.

        Args:
            nbytes (int): 수신할 최대 바이트 수
            timeout (float): 수신 대기 시간

        Returns:
            bytes: 수신된 데이터 (타임아웃 시 빈 바이트)
        """
        if not self._reader:
            raise RuntimeError("연결이 열려있지 않습니다")
        try:
            chunk = await asyncio.wait_for(self._reader.read(nbytes), timeout=timeout)
        except asyncio.TimeoutError:
            return b""
        except Exception as e:
            LOGGER.warning("수신 실패: %r", e)
            await self.reconnect()
            return b""
        if chunk:
            self._touch()
        return chunk

    async def reconnect(self) -> None:
        """연결을 재수립합니다 (지수 백오프 적용)."""
        self._connected = False
        delay_min, delay_max = self.reconnect_backoff
        if self._last_reconn_delay > 0.0:
            delay = self._last_reconn_delay
        else:
            delay = delay_min

        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
        
        LOGGER.info("연결 끊김. %.1f초 후 재연결 시도...", delay)
        await asyncio.sleep(delay)
        self._last_reconn_delay = min(delay * 2, delay_max)
        await self.open()

        if self._is_connected():
            LOGGER.info("재연결 성공")
            self._last_reconn_delay = delay_min
