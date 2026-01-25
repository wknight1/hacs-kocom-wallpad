"""Kocom 월패드 통합 구성요소."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry로부터 통합 구성요소를 설정합니다."""
    # 실행 시점에만 필요한 모듈을 임포트하여 부팅 블로킹 방지
    from .gateway import KocomGateway
    from .const import DOMAIN, PLATFORMS
    
    host: str = entry.data[CONF_HOST]
    port: int = entry.data.get(CONF_PORT)

    gateway = KocomGateway(hass, entry, host=host, port=port)
    
    # 엔티티 복원 및 시작
    await gateway.async_get_entity_registry()
    await gateway.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    # 시스템 종료 시 자원 정리 등록
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.async_stop)
    )
    
    # 각 플랫폼(light, switch 등) 설정 로드
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry를 언로드하고 자원을 정리합니다."""
    from .const import DOMAIN, PLATFORMS
    
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        from .gateway import KocomGateway
        gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.async_stop()
    return unload_ok
