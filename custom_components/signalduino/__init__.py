"""SIGNALduino integration for Home Assistant.

Hub-based integration for the SIGNALduino RF USB stick
with SOMFY RTS protocol support.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ADDRESS,
    CONF_SERIAL_PORT,
    DOMAIN,
    PLATFORMS,
    SIGNAL_CONNECTION_CHANGED,
    SIGNAL_DEVICE_UPDATED,
    SOMFY_CMD_PROG,
    SOMFY_DEFAULT_ENC_KEY,
    SOMFY_DEFAULT_REPEATS,
)
from .cover import SomfyCover
from .flamingo import FlamingoDevice
from .binary_sensor import FlamingoBinarySensor
from .protocol import SIGNALduinoProtocol
from .somfy import (
    SomfyDevice,
    SomfyFrame,
    build_send_command,
    decode_frame,
    encode_frame,
    increment_enc_key,
    increment_rolling_code,
)
from .store import SIGNALduinoStore

_LOGGER = logging.getLogger(__name__)

SERVICE_PAIR_DEVICE = "pair_device"
SERVICE_SEND_RAW = "send_raw_command"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SIGNALduino from a config entry."""
    port = entry.data[CONF_SERIAL_PORT]

    hub = SIGNALduinoHub(hass, entry)
    try:
        await hub.async_setup()
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Failed to connect to SIGNALduino on {port}"
        ) from err

    if not hub.is_connected:
        raise ConfigEntryNotReady(f"SIGNALduino on {port} not responding")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    # Register the hub device in the device registry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="SIGNALduino",
        manufacturer="SIGNALduino",
        model="CC1101" if hub.protocol.has_cc1101 else "USB",
        sw_version=hub.protocol.firmware_version,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_PAIR_DEVICE):
        _register_services(hass)

    # Reload on options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Disconnect on HA shutdown
    async def _shutdown(_event: Any) -> None:
        await hub.async_teardown()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a SIGNALduino config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: SIGNALduinoHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_teardown()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a SOMFY device from the integration.

    Called when the user deletes a device from the HA device page.
    """
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    # Find the address for this device
    address: str | None = None
    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            # Format: "{entry_id}_{address}" for child devices
            parts = identifier[1].split("_", 1)
            if len(parts) == 2 and parts[0] == entry.entry_id:
                address = parts[1]
                break

    if not address:
        return False

    # Don't allow removing the hub device itself
    if address == entry.entry_id:
        return False

    # Remove from store
    await hub.store.async_remove_device(address)

    # Remove from options
    devices = dict(entry.options.get("devices", {}))
    devices.pop(address, None)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "devices": devices}
    )

    _LOGGER.info("Removed SOMFY device %s", address)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — sync devices from options to store."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]
    await hub.async_sync_devices_from_options()
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""

    async def _handle_pair_device(call: ServiceCall) -> None:
        address = call.data[CONF_ADDRESS].upper()
        entry_id = call.data.get("entry_id")
        hub = _find_hub(hass, entry_id)
        if not hub:
            _LOGGER.error("pair_device: No SIGNALduino hub found")
            return
        if not hub.is_connected:
            _LOGGER.error("pair_device: SIGNALduino hub is not connected")
            return
        _LOGGER.debug("pair_device: Sending PROG to %s", address)
        await hub.async_send_somfy_command(address, SOMFY_CMD_PROG)

    async def _handle_send_raw(call: ServiceCall) -> None:
        command = call.data["command"]
        entry_id = call.data.get("entry_id")
        hub = _find_hub(hass, entry_id)
        if not hub:
            _LOGGER.error("send_raw_command: No SIGNALduino hub found")
            return
        if not hub.is_connected:
            _LOGGER.error("send_raw_command: SIGNALduino hub is not connected")
            return
        _LOGGER.debug("send_raw_command: Sending %s", command)
        await hub.protocol.async_send_command(command)

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAIR_DEVICE,
        _handle_pair_device,
        schema=vol.Schema(
            {
                vol.Required(CONF_ADDRESS): cv.string,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RAW,
        _handle_send_raw,
        schema=vol.Schema(
            {
                vol.Required("command"): cv.string,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )


def _find_hub(hass: HomeAssistant, entry_id: str | None = None) -> SIGNALduinoHub | None:
    """Find a SIGNALduinoHub instance."""
    hubs = hass.data.get(DOMAIN, {})
    if entry_id:
        return hubs.get(entry_id)
    # Return first available hub
    for hub in hubs.values():
        if isinstance(hub, SIGNALduinoHub):
            return hub
    return None


class SIGNALduinoHub:
    """Manages the SIGNALduino connection and SOMFY devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the hub."""
        self.hass = hass
        self._entry = entry
        self.protocol = SIGNALduinoProtocol(
            port=entry.data[CONF_SERIAL_PORT],
        )
        self.store = SIGNALduinoStore(hass, entry.entry_id)
        self._cover_entities: dict[str, SomfyCover] = {}
        self._flamingo_devices: dict[str, FlamingoDevice] = {}
        self._flamingo_entities: dict[str, FlamingoBinarySensor] = {}
        self._add_flamingo_entities_callback = None
        self._add_entities_callback: AddEntitiesCallback | None = None

    @property
    def entry_id(self) -> str:
        """Return the config entry ID."""
        return self._entry.entry_id

    @property
    def is_connected(self) -> bool:
        """Return True if the protocol is connected."""
        return self.protocol.is_connected

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the SIGNALduino hub device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="SIGNALduino",
            manufacturer="SIGNALduino",
            model="CC1101" if self.protocol.has_cc1101 else "USB",
            sw_version=self.protocol.firmware_version,
        )

    def set_add_entities_callback(self, callback: AddEntitiesCallback) -> None:
        """Store the add_entities callback from the cover platform."""
        self._add_entities_callback = callback

    def register_cover(self, address: str, entity: SomfyCover) -> None:
        """Register a cover entity for SOMFY frame dispatch."""
        self._cover_entities[address.upper()] = entity

    async def async_setup(self) -> None:
        """Connect to the SIGNALduino and load stored devices."""
        import asyncio

        await self.store.async_load()
        await self._sync_devices_from_options_to_store()

        self.protocol.set_somfy_callback(self._on_somfy_frame)
        self.protocol.set_flamingo_callback(self._on_flamingo_frame)
        self.protocol.set_connection_callback(self._on_connection_change)
        
        # Small delay to let the serial port settle after config flow validation
        await asyncio.sleep(2)

        # Try connecting with one retry
        success = await self.protocol.async_connect()
        if not success:
            _LOGGER.warning("First connect attempt failed, retrying after 3s...")
            await asyncio.sleep(3)
            success = await self.protocol.async_connect()
        if not success:
            raise ConnectionError("Failed to connect to SIGNALduino")

    async def async_teardown(self) -> None:
        """Disconnect and clean up."""
        await self.protocol.async_disconnect()

    async def async_send_somfy_command(self, address: str, command: int) -> None:
        """Encode and send a SOMFY command, managing rolling code."""
        address = address.upper()
        device = self.store.get_device(address)

        if device is None:
            # For pairing, create a temporary device
            device = SomfyDevice(
                address=address,
                name=f"SOMFY {address}",
                rolling_code=0,
                enc_key=SOMFY_DEFAULT_ENC_KEY,
            )

        # Increment rolling code and enc key
        new_rolling_code = increment_rolling_code(device.rolling_code)
        new_enc_key = device.enc_key
        if not device.fixed_enc_key:
            new_enc_key = increment_enc_key(device.enc_key)

        # Encode and encrypt the frame
        encrypted_hex = encode_frame(
            enc_key=device.enc_key,
            command=command,
            rolling_code=device.rolling_code,
            address=address,
        )

        # Build firmware commands
        commands = build_send_command(
            encrypted_hex, device.repeats, self.protocol.has_cc1101
        )

        # Persist new rolling code BEFORE sending (safety first)
        await self.store.async_update_rolling_code(
            address, new_rolling_code, new_enc_key
        )

        # Send via serial
        for cmd in commands:
            _LOGGER.debug(
                "Sending SOMFY: cmd=0x%02X addr=%s rc=%d -> '%s'",
                command, address, device.rolling_code, cmd,
            )
            await self.protocol.async_send_command(cmd)

        # Notify sensor entities that rolling code / enc_key changed
        async_dispatcher_send(
            self.hass, f"{SIGNAL_DEVICE_UPDATED}_{self.entry_id}_{address}"
        )

    async def async_update_device_config(self, address: str, **kwargs: Any) -> None:
        """Update device configuration fields and persist."""
        device = self.store.get_device(address.upper())
        if device is None:
            return
        for key, value in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, value)
        await self.store.async_save()
        async_dispatcher_send(
            self.hass, f"{SIGNAL_DEVICE_UPDATED}_{self.entry_id}_{address.upper()}"
        )

    async def async_sync_devices_from_options(self) -> None:
        """Sync devices from config entry options to store."""
        await self._sync_devices_from_options_to_store()

    async def _sync_devices_from_options_to_store(self) -> None:
        """Add/remove devices in store based on options."""
        configured = self._entry.options.get("devices", {})
        stored_addresses = set(self.store.devices.keys())
        configured_addresses = {addr.upper() for addr in configured}

        # Add new devices from options (only initial values; runtime config via entities)
        for addr, config in configured.items():
            addr_upper = addr.upper()
            if addr_upper not in stored_addresses:
                device = SomfyDevice(
                    address=addr_upper,
                    name=config.get("name", f"SOMFY {addr_upper}"),
                )
                await self.store.async_add_device(device)
                _LOGGER.info("Added SOMFY device %s (%s)", device.name, addr_upper)

        # Remove devices no longer in options
        for addr in stored_addresses - configured_addresses:
            await self.store.async_remove_device(addr)
            _LOGGER.info("Removed SOMFY device %s", addr)

    @callback
    def _on_somfy_frame(self, hex_data: str) -> None:
        """Handle a received SOMFY frame from the SIGNALduino."""
        frame = decode_frame(hex_data)
        if frame is None:
            _LOGGER.debug("Invalid SOMFY frame: %s", hex_data)
            return

        _LOGGER.debug(
            "Decoded SOMFY frame: cmd=%s addr=%s rc=%d",
            frame.command_name,
            frame.address,
            frame.rolling_code,
        )

        # Dispatch to matching cover entity
        entity = self._cover_entities.get(frame.address)
        if entity:
            entity.on_external_command(frame.command)

    def set_add_flamingo_entities_callback(
        self,
        callback: AddEntitiesCallback,
    ) -> None:
        """Register callback for adding FLAMINGO entities."""
        self._add_flamingo_entities_callback = callback

        if self._flamingo_entities:
            callback(list(self._flamingo_entities.values()))
    
    @callback
    def _on_flamingo_frame(self, protocol: str, hex_data: str) -> None:
        """Handle a received FLAMINGO frame from the SIGNALduino."""

        device_id = hex_data.upper()

        device = self._flamingo_devices.get(device_id)

        if device is None:
            device = FlamingoDevice(
                device_id=device_id,
                protocol=protocol,
            )
            self._flamingo_devices[device_id] = device
            entity = FlamingoBinarySensor(self, device)
            self._flamingo_entities[device_id] = entity

            if self._add_flamingo_entities_callback:
                self._add_flamingo_entities_callback([entity])
            _LOGGER.info("Discovered FLAMINGO device %s", device_id)

        device.receive(protocol)

        _LOGGER.debug(
            "FLAMINGO frame: protocol=%s device=%s alarm_counter=%d",
            protocol,
            device_id,
            device.alarm_counter,
        )
    
    @callback
    def _on_connection_change(self, connected: bool) -> None:
        """Handle connection state change."""
        _LOGGER.info("SIGNALduino connection: %s", "connected" if connected else "disconnected")
        async_dispatcher_send(
            self.hass, f"{SIGNAL_CONNECTION_CHANGED}_{self.entry_id}", connected
        )
