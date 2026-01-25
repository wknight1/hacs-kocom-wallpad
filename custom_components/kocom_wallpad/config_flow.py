"""Kocom 월패드 설정 흐름(Config Flow)."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DOMAIN, DEFAULT_TCP_PORT, LOGGER


class KocomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Kocom 월패드 설정을 처리하는 클래스."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """사용자 입력을 처리합니다."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = user_input[CONF_PORT]
            
            LOGGER.debug("ConfigFlow: 사용자 입력 수신 - Host: %s, Port: %s", host, port)

            # 시리얼의 경우 host가 "/"로 시작하면 장치 경로로 간주하고 port 무시
            if host.startswith("/"):
                port = None
                LOGGER.debug("ConfigFlow: 시리얼 장치 모드로 진입")

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            LOGGER.info("ConfigFlow: 새로운 설정 생성 완료 (Host: %s)", host)
            return self.async_create_entry(
                title=host,
                data={CONF_HOST: host, CONF_PORT: port}
            )

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): int,
        })
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
