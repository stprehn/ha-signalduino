"""Persistent storage for SIGNALduino device configurations and rolling codes."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .somfy import SomfyDevice

_LOGGER = logging.getLogger(__name__)


class SIGNALduinoStore:
    """Manages persistent storage of SOMFY device data."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        self._devices: dict[str, SomfyDevice] = {}

    @property
    def devices(self) -> dict[str, SomfyDevice]:
        """Return all stored devices keyed by address."""
        return self._devices

    async def async_load(self) -> None:
        """Load device data from storage."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._devices = {
                addr: SomfyDevice.from_dict(addr, dev_data)
                for addr, dev_data in data.items()
            }
            _LOGGER.debug("Loaded %d devices from storage", len(self._devices))
        else:
            self._devices = {}

    async def async_save(self) -> None:
        """Save device data to storage."""
        data = {addr: dev.to_dict() for addr, dev in self._devices.items()}
        await self._store.async_save(data)

    def get_device(self, address: str) -> SomfyDevice | None:
        """Get device by address."""
        return self._devices.get(address.upper())

    async def async_add_device(self, device: SomfyDevice) -> None:
        """Add a new device and persist."""
        self._devices[device.address.upper()] = device
        await self.async_save()

    async def async_remove_device(self, address: str) -> None:
        """Remove a device and persist."""
        self._devices.pop(address.upper(), None)
        await self.async_save()

    async def async_update_rolling_code(self, address: str, rolling_code: int, enc_key: int) -> None:
        """Update rolling code and encryption key, then persist immediately."""
        device = self._devices.get(address.upper())
        if device:
            device.rolling_code = rolling_code
            device.enc_key = enc_key
            await self.async_save()

    async def async_update_position(self, address: str, position: int) -> None:
        """Update device position and persist."""
        device = self._devices.get(address.upper())
        if device:
            device.position = position
            await self.async_save()

    async def async_remove(self) -> None:
        """Remove the storage file entirely."""
        await self._store.async_remove()
