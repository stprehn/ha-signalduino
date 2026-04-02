"""Switch platform for SIGNALduino SOMFY devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DEVICE_UPDATED
from .entity import SIGNALduinoEntity

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice


@dataclass(frozen=True, kw_only=True)
class SIGNALduinoSwitchDescription(SwitchEntityDescription):
    """Describes a SIGNALduino switch entity."""

    value_fn: Callable[[SomfyDevice], bool]
    attr_name: str


SWITCH_DESCRIPTIONS: tuple[SIGNALduinoSwitchDescription, ...] = (
    SIGNALduinoSwitchDescription(
        key="invert_position",
        translation_key="invert_position",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:swap-vertical",
        value_fn=lambda d: d.invert_position,
        attr_name="invert_position",
    ),
    SIGNALduinoSwitchDescription(
        key="fixed_enc_key",
        translation_key="fixed_enc_key",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:key-lock",
        value_fn=lambda d: d.fixed_enc_key,
        attr_name="fixed_enc_key",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SIGNALduino switch entities."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SIGNALduinoConfigSwitch(hub, device, description)
        for device in hub.store.devices.values()
        for description in SWITCH_DESCRIPTIONS
    ]
    async_add_entities(entities)


class SIGNALduinoConfigSwitch(SIGNALduinoEntity, SwitchEntity):
    """Configuration switch for a SOMFY device."""

    entity_description: SIGNALduinoSwitchDescription

    def __init__(
        self,
        hub: SIGNALduinoHub,
        device: SomfyDevice,
        description: SIGNALduinoSwitchDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(hub, device)
        self.entity_description = description
        self._attr_unique_id = f"{hub.entry_id}_{device.address}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return self.entity_description.value_fn(self._device)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        await self._hub.async_update_device_config(
            self._device.address, **{self.entity_description.attr_name: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        await self._hub.async_update_device_config(
            self._device.address, **{self.entity_description.attr_name: False}
        )

    async def async_added_to_hass(self) -> None:
        """Register dispatcher listener for device updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_DEVICE_UPDATED}_{self._hub.entry_id}_{self._device.address}",
                self._on_device_updated,
            )
        )

    @callback
    def _on_device_updated(self) -> None:
        """Handle device data update."""
        self.async_write_ha_state()
