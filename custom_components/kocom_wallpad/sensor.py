"""Sensor platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
)

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
    """Set up Kocom sensor platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_sensor(devices=None):
        """Add sensor entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.SENSOR)

        entities: List[KocomSensor] = []
        for dev in devices:
            entity = KocomSensor(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.SENSOR), async_add_sensor
        )
    )
    async_add_sensor()


class KocomSensor(KocomBaseEntity, SensorEntity):
    """Representation of a Kocom sensor."""
    
    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the sensor."""
        super().__init__(gateway, device)

    @property
    def native_value(self) -> Any:
        return self._device.state
    
    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._device.attribute.get("device_class", None)
    
    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._device.attribute.get("unit_of_measurement", None)
