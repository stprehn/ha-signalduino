"""Cover platform for SIGNALduino SOMFY devices."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    DOMAIN,
    MODEL_BLIND,
    MODEL_SHUTTER,
    POSITION_UPDATE_INTERVAL,
    SOMFY_CMD_DOWN,
    SOMFY_CMD_STOP,
    SOMFY_CMD_UP,
)
from .entity import SIGNALduinoEntity

if TYPE_CHECKING:
    from . import SIGNALduinoHub
    from .somfy import SomfyDevice

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SOMFY cover entities from a config entry."""
    hub: SIGNALduinoHub = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SomfyCover(hub, device)
        for device in hub.store.devices.values()
    ]
    async_add_entities(entities)


class SomfyCover(SIGNALduinoEntity, CoverEntity):
    """Representation of a SOMFY RTS cover (shutter or blind)."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_assumed_state = True
    _attr_translation_key = "somfy_cover"

    def __init__(self, hub: SIGNALduinoHub, device: SomfyDevice) -> None:
        """Initialize the cover entity."""
        super().__init__(hub, device)
        self._position = device.position  # 0=closed, 100=open
        self._moving: str | None = None  # "opening" | "closing" | None
        self._move_start_time: float | None = None
        self._move_start_position: int | None = None
        self._target_position: int | None = None
        self._update_timer_cancel: asyncio.TimerHandle | None = None
        self._stop_timer_cancel: callback | None = None

        if device.model == MODEL_BLIND:
            self._attr_device_class = CoverDeviceClass.BLIND
        elif device.model == MODEL_SHUTTER:
            self._attr_device_class = CoverDeviceClass.SHUTTER
        else:
            self._attr_device_class = CoverDeviceClass.AWNING

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0=closed, 100=open)."""
        return self._position

    @property
    def is_closed(self) -> bool | None:
        """Return True if cover is fully closed."""
        return self._position == 0

    @property
    def is_closing(self) -> bool:
        """Return True if cover is currently closing."""
        return self._moving == "closing"

    @property
    def is_opening(self) -> bool:
        """Return True if cover is currently opening."""
        return self._moving == "opening"

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self._start_move("opening", 100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self._start_move("closing", 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        if not self._hub.is_connected:
            _LOGGER.warning("Cannot stop cover, SIGNALduino not connected")
            return
        await self._hub.async_send_somfy_command(self._device.address, SOMFY_CMD_STOP)
        self._finalize_move()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover to a specific position."""
        target = kwargs[ATTR_POSITION]
        if target == self._position:
            return
        direction = "opening" if target > self._position else "closing"
        await self._start_move(direction, target)

    async def _start_move(self, direction: str, target: int) -> None:
        """Start moving the cover in the given direction."""
        if not self._hub.is_connected:
            _LOGGER.warning("Cannot move cover, SIGNALduino not connected")
            return

        # Cancel any existing movement
        self._cancel_timers()

        self._moving = direction
        self._move_start_time = time.monotonic()
        self._move_start_position = self._position
        self._target_position = target

        # Send RF command (inverted for awnings: open=extend=DOWN, close=retract=UP)
        if self._device.invert_position:
            command = SOMFY_CMD_DOWN if direction == "opening" else SOMFY_CMD_UP
        else:
            command = SOMFY_CMD_UP if direction == "opening" else SOMFY_CMD_DOWN
        await self._hub.async_send_somfy_command(self._device.address, command)

        # Calculate movement duration
        distance = abs(target - self._position)
        if direction == "opening":
            duration = (distance / 100.0) * self._device.drive_time_up
        else:
            duration = (distance / 100.0) * self._device.drive_time_down

        # Schedule auto-stop for intermediate positions
        if target not in (0, 100):
            self._stop_timer_cancel = async_call_later(
                self.hass, duration, self._auto_stop_callback
            )

        # Schedule periodic position updates for UI
        self._schedule_position_update()

        self.async_write_ha_state()

    @callback
    def _auto_stop_callback(self, _now: Any) -> None:
        """Send stop when target position is reached."""
        self._stop_timer_cancel = None
        self.hass.async_create_task(self._auto_stop())

    async def _auto_stop(self) -> None:
        """Send stop command and finalize position."""
        await self._hub.async_send_somfy_command(self._device.address, SOMFY_CMD_STOP)
        self._finalize_move()

    @callback
    def _schedule_position_update(self) -> None:
        """Schedule the next position update tick."""
        if self._moving:
            self._update_timer_cancel = self.hass.loop.call_later(
                POSITION_UPDATE_INTERVAL, self._position_update_tick
            )

    @callback
    def _position_update_tick(self) -> None:
        """Update estimated position during movement."""
        self._update_timer_cancel = None
        if not self._moving or self._move_start_time is None:
            return

        self._update_estimated_position()

        # Finalize if endstop reached
        if self._position in (0, 100) and self._target_position in (0, 100):
            self._finalize_move()
            return

        self.async_write_ha_state()
        self._schedule_position_update()

    def _update_estimated_position(self) -> None:
        """Calculate current position based on elapsed time."""
        if self._move_start_time is None or self._move_start_position is None:
            return

        elapsed = time.monotonic() - self._move_start_time

        if self._moving == "opening":
            travel = (elapsed / self._device.drive_time_up) * 100
            self._position = min(100, int(self._move_start_position + travel))
        elif self._moving == "closing":
            travel = (elapsed / self._device.drive_time_down) * 100
            self._position = max(0, int(self._move_start_position - travel))

    def _finalize_move(self) -> None:
        """Finalize movement and persist position."""
        self._update_estimated_position()

        # Snap to target if close enough
        if self._target_position is not None:
            if abs(self._position - self._target_position) <= 2:
                self._position = self._target_position

        self._moving = None
        self._move_start_time = None
        self._move_start_position = None
        self._target_position = None
        self._cancel_timers()

        # Persist position
        self.hass.async_create_task(
            self._hub.store.async_update_position(
                self._device.address, self._position
            )
        )
        self.async_write_ha_state()

    def _cancel_timers(self) -> None:
        """Cancel all pending timers."""
        if self._update_timer_cancel is not None:
            self._update_timer_cancel.cancel()
            self._update_timer_cancel = None
        if self._stop_timer_cancel is not None:
            self._stop_timer_cancel()
            self._stop_timer_cancel = None

    @callback
    def on_external_command(self, command: int) -> None:
        """Handle a command received from an external remote.

        When the SIGNALduino receives a SOMFY frame from another remote,
        update state accordingly.
        """
        # Map RF commands to logical direction (inverted for awnings)
        invert = self._device.invert_position
        open_cmd = SOMFY_CMD_DOWN if invert else SOMFY_CMD_UP
        close_cmd = SOMFY_CMD_UP if invert else SOMFY_CMD_DOWN

        if command == open_cmd:
            self._cancel_timers()
            self._moving = "opening"
            self._move_start_time = time.monotonic()
            self._move_start_position = self._position
            self._target_position = 100
            self._schedule_position_update()
            self.async_write_ha_state()
        elif command == close_cmd:
            self._cancel_timers()
            self._moving = "closing"
            self._move_start_time = time.monotonic()
            self._move_start_position = self._position
            self._target_position = 0
            self._schedule_position_update()
            self.async_write_ha_state()
        elif command == SOMFY_CMD_STOP:
            self._finalize_move()

    async def async_added_to_hass(self) -> None:
        """Register with hub and set up connection listener."""
        await super().async_added_to_hass()
        self._hub.register_cover(self._device.address, self)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up timers when entity is removed."""
        self._cancel_timers()
