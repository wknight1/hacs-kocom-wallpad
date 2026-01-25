"""Kocom 월패드 컴포넌트 설정."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP

from .const import DOMAIN, PLATFORMS
from .gateway import KocomGateway


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry로부터 Kocom 월패드를 설정합니다."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    gateway = KocomGateway(hass, entry, host=host, port=port)
    await gateway.async_get_entity_registry()
    await gateway.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.async_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry를 언로드합니다."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.async_stop()
    return unload_ok
