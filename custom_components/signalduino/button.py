"""Button platform for SIGNALduino SOMFY devices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SOMFY_CMD_PROG
from .entity import SIGNALduinoEntity

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice

PAIR_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="pair",
    translation_key="pair",
    entity_category=EntityCategory.CONFIG,
    device_class=ButtonDeviceClass.IDENTIFY,
    icon="mdi:link-variant-plus",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SIGNALduino button entities."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SIGNALduinoPairButton(hub, device)
        for device in hub.store.devices.values()
    ]
    async_add_entities(entities)


class SIGNALduinoPairButton(SIGNALduinoEntity, ButtonEntity):
    """Button to send PROG/pair command to a SOMFY device."""

    entity_description = PAIR_BUTTON_DESCRIPTION

    def __init__(self, hub: SIGNALduinoHub, device: SomfyDevice) -> None:
        """Initialize the pair button."""
        super().__init__(hub, device)
        self._attr_unique_id = f"{hub.entry_id}_{device.address}_pair"

    async def async_press(self) -> None:
        """Send the PROG command to pair this device."""
        await self._hub.async_send_somfy_command(
            self._device.address, SOMFY_CMD_PROG
        )
