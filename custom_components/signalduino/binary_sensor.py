"""Binary sensors for SIGNALduino FLAMINGO devices."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .flamingo import FlamingoDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FLAMINGO binary sensors."""
    hub = hass.data[DOMAIN][entry.entry_id]
    hub.set_add_flamingo_entities_callback(async_add_entities)


class FlamingoBinarySensor(BinarySensorEntity):
    """Represent a FLAMINGO smoke detector."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.SMOKE

    def __init__(
        self,
        hub,
        device: FlamingoDevice,
    ) -> None:
        """Initialize the FLAMINGO binary sensor."""
        self._hub = hub
        self._device = device
        self._cancel_alarm_timer = None

        self._attr_unique_id = (
            f"{hub.entry_id}_flamingo_{device.device_id}"
        )
        self._attr_name = "Alarm"

    @property
    def is_on(self) -> bool:
        """Return true when the detector is in alarm state."""
        return self._device.is_alarm

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Return diagnostic attributes."""
        return {
            "device_id": self._device.device_id,
            "protocol": self._device.protocol,
            "alarm_counter": self._device.alarm_counter,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self._hub.entry_id}_flamingo_{self._device.device_id}",
                )
            },
            name=f"Flamingo {self._device.device_id}",
            manufacturer="FLAMINGO",
            model="Unknown",
            via_device=(DOMAIN, self._hub.entry_id),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the alarm timer when the entity is removed."""
        if self._cancel_alarm_timer:
            self._cancel_alarm_timer()
            self._cancel_alarm_timer = None

    def reset_alarm_timer(self) -> None:
        """Reset the alarm timeout timer."""
        if self._cancel_alarm_timer:
            self._cancel_alarm_timer()

        self._cancel_alarm_timer = async_call_later(
            self.hass,
            timedelta(seconds=15),
            self._alarm_timeout,
        )

    @callback
    def _alarm_timeout(self, _now) -> None:
        """Clear the alarm state after 15 seconds without a telegram."""
        self._cancel_alarm_timer = None
        self._device.is_alarm = False
        self.async_write_ha_state()

    @callback
    def update_from_device(self) -> None:
        """Update the entity from the FLAMINGO device state."""
        self.async_write_ha_state()
