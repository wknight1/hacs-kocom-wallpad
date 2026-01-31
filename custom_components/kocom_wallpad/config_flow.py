"""Kocom 월패드 설정 흐름."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, DEFAULT_TCP_PORT

_LOGGER = logging.getLogger(__name__)

class KocomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Kocom 설정 흐름을 처리합니다."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """사용자가 초기 설정을 입력할 때 호출됩니다."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"]
            # 중복 설정 방지
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(title=host, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host"): str,
                vol.Required("port", default=DEFAULT_TCP_PORT): int,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """옵션 흐름 핸들러를 반환합니다."""
        return KocomOptionsFlowHandler(config_entry)


class KocomOptionsFlowHandler(config_entries.OptionsFlow):
    """Kocom 옵션 흐름 핸들러."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """옵션 흐름을 초기화합니다."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """옵션 초기화 단계."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    "scan_interval", 
                    default=options.get("scan_interval", 0)
                ): cv.positive_int,
                # 고급 사용자를 위한 연결 타임아웃 설정
                vol.Optional(
                    "connection_timeout",
                    default=options.get("connection_timeout", 10.0)
                ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=60.0)),
                # 하트비트 간격 설정 (0=비활성)
                vol.Optional(
                    "heartbeat_interval",
                    default=options.get("heartbeat_interval", 5)
                ): cv.positive_int,
            })
        )