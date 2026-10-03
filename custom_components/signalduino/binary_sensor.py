"""Binary sensors for SIGNALduino FLAMINGO devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .flamingo import FlamingoDevice


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

    @callback
    def update_from_device(self) -> None:
        """Update the entity from the FLAMINGO device state."""
        self.async_write_ha_state()
