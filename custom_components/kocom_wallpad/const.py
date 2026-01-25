"""Kocom 월패드 상수 정의."""

from __future__ import annotations

import logging
from enum import IntEnum
from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

DOMAIN = "kocom_wallpad"
PLATFORMS = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

PACKET_PREFIX = bytes([0xAA, 0x55])
PACKET_SUFFIX = bytes([0x0D, 0x0D])
PACKET_LEN = 21

DEFAULT_TCP_PORT = 8899
RECV_POLL_SEC = 0.03  # 30ms polling (EW11 Gap Time 50ms 고려)
IDLE_GAP_SEC = 0.10   # 보내기 전 라인 유휴로 보고 싶은 최소 간격 (100ms로 단축)
SEND_RETRY_MAX = 3
SEND_RETRY_GAP = 0.20 # 재시도 간격을 약간 넓혀 하드웨어 버퍼 정리 유도
CMD_CONFIRM_TIMEOUT = 1.2  # 고지연 환경 대비 타임아웃 약간 상향

class DeviceType(IntEnum):
    """디바이스 타입 정의."""
    UNKNOWN = 0
    LIGHT = 1
    LIGHTCUTOFF = 2
    DIMMINGLIGHT = 3
    OUTLET = 4
    THERMOSTAT = 5
    AIRCONDITIONER = 6
    VENTILATION = 7
    GASVALVE = 8
    ELEVATOR = 9
    MOTION = 10
    AIRQUALITY = 11


class SubType(IntEnum):
    """서브 타입 정의 (센서 종류 등)."""
    NONE = 0
    DIRECTION = 1
    FLOOR = 2
    ERRCODE = 3
    HEATTEMP = 4
    HOTTEMP = 5
    CO2 = 6
    PM10 = 7
    PM25 = 8
    VOC = 9
    TEMP = 10
    HUMIDITY = 11
