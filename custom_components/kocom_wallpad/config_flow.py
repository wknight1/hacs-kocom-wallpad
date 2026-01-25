"""Config flow for Kocom Wallpad."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DOMAIN, DEFAULT_TCP_PORT


class KocomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Kocom Wallpad."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host: str = user_input[CONF_HOST]
            port: int = user_input[CONF_PORT]

            # 시리얼의 경우 host가 "/"로 시작하면 장치 경로로 간주하고 port 무시
            if host.startswith("/"):
                port = None

            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

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
