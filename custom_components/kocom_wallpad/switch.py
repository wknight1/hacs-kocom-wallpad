"""Switch platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom switch platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_switch(devices=None):
        """Add switch entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.SWITCH)

        entities: List[KocomSwitch] = []
        for dev in devices:
            entity = KocomSwitch(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.SWITCH), async_add_switch
        )
    )
    async_add_switch()


class KocomSwitch(KocomBaseEntity, SwitchEntity):
    """Representation of a Kocom switch."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the switch."""
        super().__init__(gateway, device)
        
    @property
    def device_class(self) -> SwitchDeviceClass:
        return self._device.attribute.get("device_class", SwitchDeviceClass.SWITCH)

    @property
    def is_on(self) -> bool:
        return self._device.state

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.gateway.async_send_action(self._device.key, "turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.gateway.async_send_action(self._device.key, "turn_off")
