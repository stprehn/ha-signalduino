"""Config flow for SIGNALduino integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_ADDRESS,
    CONF_SERIAL_PORT,
    DOMAIN,
)
from .protocol import validate_connection, validate_port_accessible

_LOGGER = logging.getLogger(__name__)

ADDRESS_PATTERN = re.compile(r"^[0-9A-Fa-f]{6}$")


class SIGNALduinoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SIGNALduino."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: serial port selection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            port = user_input[CONF_SERIAL_PORT]

            port_error = await validate_port_accessible(port)
            if port_error:
                errors["base"] = port_error
            else:
                firmware = await validate_connection(port)
                if firmware is None:
                    errors["base"] = "no_version_response"
                else:
                    await self.async_set_unique_id(port)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"SIGNALduino ({firmware})",
                        data={CONF_SERIAL_PORT: port},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL_PORT,
                        default=(self.hass.data.get(DOMAIN, {}).get("last_port", "")),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the serial port."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            port = user_input[CONF_SERIAL_PORT]

            port_error = await validate_port_accessible(port)
            if port_error:
                errors["base"] = port_error
            else:
                firmware = await validate_connection(port)
                if firmware is None:
                    errors["base"] = "no_version_response"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=port,
                        title=f"SIGNALduino ({firmware})",
                        data={CONF_SERIAL_PORT: port},
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERIAL_PORT,
                        default=entry.data.get(CONF_SERIAL_PORT, ""),
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SIGNALduinoOptionsFlow:
        """Return the options flow handler."""
        return SIGNALduinoOptionsFlow(config_entry)


class SIGNALduinoOptionsFlow(OptionsFlow):
    """Handle options flow for SIGNALduino (device management)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_device"],
        )

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new SOMFY device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].upper()

            if not ADDRESS_PATTERN.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                hub = self.hass.data.get(DOMAIN, {}).get(
                    self._config_entry.entry_id
                )
                if hub and hub.store.get_device(address):
                    errors[CONF_ADDRESS] = "device_exists"

                if not errors:
                    devices = dict(self._config_entry.options.get("devices", {}))
                    devices[address] = {
                        "name": user_input.get("name", f"SOMFY {address}"),
                    }

                    return self.async_create_entry(
                        title="",
                        data={**self._config_entry.options, "devices": devices},
                    )

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required(CONF_ADDRESS): str,
                }
            ),
            errors=errors,
        )
