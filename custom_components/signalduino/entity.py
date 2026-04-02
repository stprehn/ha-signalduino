"""Base entity for SIGNALduino integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_CONNECTION_CHANGED

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice


class SIGNALduinoEntity(Entity):
    """Base entity for SIGNALduino SOMFY devices."""

    _attr_has_entity_name = True

    def __init__(self, hub: SIGNALduinoHub, device: SomfyDevice) -> None:
        """Initialize base entity."""
        self._hub = hub
        self._device = device
        self._attr_unique_id = f"{hub.entry_id}_{device.address}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info linking to the SOMFY child device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._hub.entry_id}_{self._device.address}")},
            name=self._device.name,
            manufacturer="Somfy",
            model=self._device.model,
            serial_number=self._device.address,
            via_device=(DOMAIN, self._hub.entry_id),
        )

    @property
    def available(self) -> bool:
        """Return True if the hub is connected."""
        return self._hub.is_connected

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
        """Handle hub connection state change."""
        self.async_write_ha_state()
