"""Sensor platform for SIGNALduino SOMFY devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_CONNECTION_CHANGED, SIGNAL_DEVICE_UPDATED
from .entity import SIGNALduinoEntity

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice


@dataclass(frozen=True, kw_only=True)
class SIGNALduinoSensorDescription(SensorEntityDescription):
    """Describes a SIGNALduino sensor entity."""

    value_fn: Callable[[SomfyDevice], str | int]


SENSOR_DESCRIPTIONS: tuple[SIGNALduinoSensorDescription, ...] = (
    SIGNALduinoSensorDescription(
        key="rolling_code",
        translation_key="rolling_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:counter",
        value_fn=lambda d: d.rolling_code,
    ),
    SIGNALduinoSensorDescription(
        key="enc_key",
        translation_key="enc_key",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:key-variant",
        value_fn=lambda d: f"0x{d.enc_key:02X}",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SIGNALduino sensor entities."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    # Child device sensors
    entities: list[SensorEntity] = [
        SIGNALduinoSensor(hub, device, description)
        for device in hub.store.devices.values()
        for description in SENSOR_DESCRIPTIONS
    ]

    # Hub sensor
    entities.append(SIGNALduinoHubConnectionSensor(hub))

    async_add_entities(entities)


class SIGNALduinoSensor(SIGNALduinoEntity, SensorEntity):
    """Diagnostic sensor for a SOMFY device."""

    entity_description: SIGNALduinoSensorDescription

    def __init__(
        self,
        hub: SIGNALduinoHub,
        device: SomfyDevice,
        description: SIGNALduinoSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(hub, device)
        self.entity_description = description
        self._attr_unique_id = f"{hub.entry_id}_{device.address}_{description.key}"

    @property
    def native_value(self) -> str | int:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self._device)

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


class SIGNALduinoHubConnectionSensor(SensorEntity):
    """Connection state sensor for the SIGNALduino hub device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:connection"
    _attr_translation_key = "connection_state"

    def __init__(self, hub: SIGNALduinoHub) -> None:
        """Initialize the hub connection sensor."""
        self._hub = hub
        self._attr_unique_id = f"{hub.entry_id}_hub_connection_state"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the hub device."""
        return self._hub.device_info

    @property
    def native_value(self) -> str:
        """Return current connection state."""
        return self._hub.protocol.state.value

    async def async_added_to_hass(self) -> None:
        """Register dispatcher listener for connection changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_CONNECTION_CHANGED}_{self._hub.entry_id}",
                self._on_connection_changed,
            )
        )

    @callback
    def _on_connection_changed(self, _connected: bool) -> None:
        """Handle connection state change."""
        self.async_write_ha_state()
