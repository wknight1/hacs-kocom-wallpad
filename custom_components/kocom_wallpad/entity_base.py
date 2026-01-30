"""Kocom 월패드 기본 엔티티."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity, RestoredExtraData
from homeassistant.core import callback
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.components.light import LightEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.fan import FanEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.binary_sensor import BinarySensorEntityDescription

from .const import DOMAIN, DeviceType, SubType


ENTITY_DESCRIPTION_MAP = {
    Platform.LIGHT: LightEntityDescription,
    Platform.SWITCH: SwitchEntityDescription,
    Platform.CLIMATE: ClimateEntityDescription,
    Platform.FAN: FanEntityDescription,
    Platform.SENSOR: SensorEntityDescription,
    Platform.BINARY_SENSOR: BinarySensorEntityDescription
}


class KocomBaseEntity(RestoreEntity):
    """모든 Kocom 엔티티의 기본 클래스."""

    def __init__(self, gateway, device) -> None:
        """기본 엔티티를 초기화합니다."""
        super().__init__()
        self.gateway = gateway
        self._device = device
        self._unsubs: list[callable] = []

        self._attr_unique_id = f"{device.key.unique_id}:{self.gateway.host}"
        self.entity_description = ENTITY_DESCRIPTION_MAP[self._device.platform](
            key=self.format_key,
            has_entity_name=True,
            translation_key=self.format_key,
            translation_placeholders={"id": self.format_translation_placeholders}
        )
        self._attr_device_info = DeviceInfo(
            connections={(self.gateway.host, self.unique_id)},
            identifiers={(DOMAIN, f"{self.format_identifiers}")},
            manufacturer="KOCOM Co., Ltd",
            model="Smart Wallpad",
            name=f"{self.format_identifiers}",
            via_device=(DOMAIN, self.gateway.host),  # Gateway 호스트와 일치시킴
        )
        
    @property
    def format_key(self) -> str:
        """엔티티 키를 포맷팅합니다."""
        if self._device.key.sub_type == SubType.NONE:
            return self._device.key.device_type.name.lower()
        else:
            return f"{self._device.key.device_type.name.lower()}-{self._device.key.sub_type.name.lower()}"

    @property
    def format_translation_placeholders(self) -> str:
        """번역 플레이스홀더를 포맷팅합니다."""
        if self._device.key.sub_type == SubType.NONE:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"
        else:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"

    @property
    def format_identifiers(self) -> str:
        """디바이스 식별자를 포맷팅합니다."""
        if self._device.key.device_type in {
            DeviceType.VENTILATION, DeviceType.GASVALVE, DeviceType.ELEVATOR, DeviceType.MOTION
        }:
            return "KOCOM"
        elif self._device.key.device_type in {
            DeviceType.LIGHT, DeviceType.LIGHTCUTOFF, DeviceType.DIMMINGLIGHT
        }:
            return "KOCOM LIGHT"
        else:
            return f"KOCOM {self._device.key.device_type.name}"

    async def async_added_to_hass(self):
        """HA에 엔티티가 추가될 때 호출됩니다."""
        sig = self.gateway.async_signal_device_updated(self._device.key.unique_id)

        @callback
        def _handle_update(dev):
            self._device = dev
            self.update_from_state()
        self._unsubs.append(async_dispatcher_connect(self.hass, sig, _handle_update))

    async def async_will_remove_from_hass(self) -> None:
        """HA에서 엔티티가 제거될 때 호출됩니다."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()

    @callback
    def update_from_state(self) -> None:
        """디바이스 상태로부터 엔티티 상태를 업데이트합니다."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """게이트웨이 연결 및 월패드 응답 상태에 따른 가용성을 반환합니다."""
        return self.gateway.is_available()

    @property
    def should_poll(self) -> bool:
        """HA의 폴링을 비활성화합니다. (Local Push 방식)"""
        return False

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        """복원 시 필요한 추가 데이터를 저장합니다."""
        return RestoredExtraData({
            "packet": getattr(self._device, "_packet", bytes()).hex(),
            "device_storage": self.gateway.controller._device_storage
        })
