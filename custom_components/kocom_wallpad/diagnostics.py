"""Kocom Wallpad 진단 도구."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .gateway import KocomGateway


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """통합구성요소의 현재 상태를 진단 데이터로 반환합니다."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    # 보안상 민감할 수 있는 정보(IP 등)는 자동으로 마스킹 처리됨을 전제로 함
    return {
        "gateway_info": {
            "host": gateway.host,
            "port": gateway.port,
            "connected": gateway.conn._is_connected(),
            "reconnect_count": gateway.conn._reconnect_count,
            "idle_since": f"{gateway.conn.idle_since():.1f}s",
            "recv_idle_since": f"{gateway.conn.recv_idle_since():.1f}s",
            "consecutive_failures": gateway._consecutive_failures,
        },
        "registry_stats": {
            "total_entities": len(gateway.registry._states),
            "platforms": {
                p.value: len(devs) for p, devs in gateway.registry.by_platform.items()
            },
        },
        "queue_info": {
            "tx_queue_size": gateway._tx_queue.qsize(),
            "pending_waiters": len(gateway._pendings),
        },
        "system_info": {
            "last_discovery_time": gateway._last_discovery_time,
        }
    }
