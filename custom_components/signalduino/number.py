"""Number platform for SIGNALduino SOMFY devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DEVICE_UPDATED
from .entity import SIGNALduinoEntity

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice


@dataclass(frozen=True, kw_only=True)
class SIGNALduinoNumberDescription(NumberEntityDescription):
    """Describes a SIGNALduino number entity."""

    value_fn: Callable[[SomfyDevice], float]
    attr_name: str


NUMBER_DESCRIPTIONS: tuple[SIGNALduinoNumberDescription, ...] = (
    SIGNALduinoNumberDescription(
        key="drive_time_down",
        translation_key="drive_time_down",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-down-bold",
        native_min_value=1.0,
        native_max_value=120.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: d.drive_time_down,
        attr_name="drive_time_down",
    ),
    SIGNALduinoNumberDescription(
        key="drive_time_up",
        translation_key="drive_time_up",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:arrow-up-bold",
        native_min_value=1.0,
        native_max_value=120.0,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: d.drive_time_up,
        attr_name="drive_time_up",
    ),
    SIGNALduinoNumberDescription(
        key="repeats",
        translation_key="repeats",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:repeat",
        native_min_value=1,
        native_max_value=20,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: float(d.repeats),
        attr_name="repeats",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SIGNALduino number entities."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SIGNALduinoNumber(hub, device, description)
        for device in hub.store.devices.values()
        for description in NUMBER_DESCRIPTIONS
    ]
    async_add_entities(entities)


class SIGNALduinoNumber(SIGNALduinoEntity, NumberEntity):
    """Configuration number for a SOMFY device."""

    entity_description: SIGNALduinoNumberDescription

    def __init__(
        self,
        hub: SIGNALduinoHub,
        device: SomfyDevice,
        description: SIGNALduinoNumberDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(hub, device)
        self.entity_description = description
        self._attr_unique_id = f"{hub.entry_id}_{device.address}_{description.key}"

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.entity_description.value_fn(self._device)

    async def async_set_native_value(self, value: float) -> None:
        """Update the device configuration value."""
        attr_name = self.entity_description.attr_name
        if attr_name == "repeats":
            value = int(value)
        await self._hub.async_update_device_config(
            self._device.address, **{attr_name: value}
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
