"""SIGNALduino serial protocol handler.

Manages the async serial connection to a SIGNALduino USB stick,
including initialization, keepalive, message parsing, and reconnection.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from enum import Enum

from serial_asyncio_fast import open_serial_connection

from .const import (
    CMD_DISABLE_RECEIVER,
    CMD_ENABLE_RECEIVER,
    CMD_PING,
    CMD_SEND_MSG,
    CMD_VERSION,
    DEFAULT_BAUD_RATE,
    INIT_WAIT_AFTER_XQ,
    KEEPALIVE_INTERVAL,
    KEEPALIVE_MAX_RETRIES,
    RECONNECT_DELAYS,
)

_LOGGER = logging.getLogger(__name__)

# Pattern for SOMFY messages received from SIGNALduino
SOMFY_MSG_PATTERN = re.compile(r"^Ys([0-9A-Fa-f]+)$")

# Pattern for version response — flexible to match various firmware variants:
# "V 3.3.1-dev SIGNALduino cc1101 (433Mhz )- compiled at ..."
# "V 3.5.0 SIGNALduino cc1101 - compiled at ..."
# "V 3.5.7 SIGNALDuino_ESP 868MHz ..."
VERSION_PATTERN = re.compile(
    r"V\s+([\d.][\w.\-]*)\s+SIGNAL[Dd]uino.*", re.IGNORECASE
)


class ConnectionState(Enum):
    """Connection state machine states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class SIGNALduinoProtocol:
    """Async serial protocol handler for SIGNALduino USB stick."""

    def __init__(
        self,
        port: str,
        baud_rate: int = DEFAULT_BAUD_RATE,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Initialize protocol handler."""
        self._port = port
        self._baud_rate = baud_rate
        self._loop = loop

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._state = ConnectionState.DISCONNECTED
        self._firmware_version: str | None = None
        self._has_cc1101: bool = False

        self._keepalive_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._keepalive_retries = 0
        self._reconnect_attempt = 0

        # Callbacks
        self._on_somfy_frame: Callable[[str], None] | None = None
        self._on_flamingo_frame: Callable[[str, str], None] | None = None
        self._on_connection_change: Callable[[bool], None] | None = None

        self._closing = False

    @property
    def is_connected(self) -> bool:
        """Return True if connected and initialized."""
        return self._state == ConnectionState.CONNECTED

    @property
    def firmware_version(self) -> str | None:
        """Return firmware version string."""
        return self._firmware_version

    @property
    def has_cc1101(self) -> bool:
        """Return True if CC1101 transceiver is detected."""
        return self._has_cc1101

    @property
    def state(self) -> ConnectionState:
        """Return current connection state."""
        return self._state

    def set_somfy_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for received SOMFY frames."""
        self._on_somfy_frame = callback

    def set_flamingo_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register callback for FLAMINGO frames."""
        self._on_flamingo_frame = callback

    def set_connection_callback(self, callback: Callable[[bool], None]) -> None:
        """Set callback for connection state changes."""
        self._on_connection_change = callback

    async def async_connect(self) -> bool:
        """Connect to the SIGNALduino and run initialization sequence."""
        self._closing = False
        self._state = ConnectionState.CONNECTING
        try:
            url = self._port
            if url.startswith("tcp://"):
                url = "socket://" + url[6:]

            self._reader, self._writer = await open_serial_connection(
                url=url, baudrate=self._baud_rate
            )
        except Exception:
            _LOGGER.error("Failed to open serial port %s", self._port)
            self._state = ConnectionState.DISCONNECTED
            return False

        self._state = ConnectionState.INITIALIZING
        success = await self._run_init_sequence()
        if not success:
            await self._close_serial()
            self._state = ConnectionState.DISCONNECTED
            return False

        self._state = ConnectionState.CONNECTED
        self._reconnect_attempt = 0
        self._keepalive_retries = 0

        # Start background tasks
        self._read_task = asyncio.ensure_future(self._read_loop())
        self._keepalive_task = asyncio.ensure_future(self._keepalive_loop())

        self._notify_connection(True)
        _LOGGER.info(
            "SIGNALduino connected on %s (firmware %s, CC1101: %s)",
            self._port,
            self._firmware_version,
            self._has_cc1101,
        )
        return True

    async def async_disconnect(self) -> None:
        """Disconnect from the SIGNALduino."""
        self._closing = True
        self._cancel_tasks()
        await self._close_serial()
        self._state = ConnectionState.DISCONNECTED
        self._notify_connection(False)

    async def async_send_command(self, command: str) -> None:
        """Send a command string to the SIGNALduino."""
        if self._writer is None or self._state != ConnectionState.CONNECTED:
            _LOGGER.warning("Cannot send command, not connected: %s", command)
            return
        try:
            self._writer.write(f"{command}\n".encode())
            await self._writer.drain()
            _LOGGER.debug("Sent: %s", command)
        except Exception:
            _LOGGER.error("Failed to send command: %s", command)
            await self._trigger_reconnect()

    async def async_send_somfy(self, send_msg: str) -> None:
        """Send a SOMFY protocol message via sendMsg command."""
        await self.async_send_command(f"{CMD_SEND_MSG} {send_msg}")

    async def _run_init_sequence(self) -> bool:
        """Run the SIGNALduino initialization sequence.

        1. Send XQ (disable receiver)
        2. Wait 1.5s
        3. Send V (version query)
        4. Parse version response
        5. Send XE (enable receiver)
        """
        try:
            # Disable receiver
            self._writer.write(f"{CMD_DISABLE_RECEIVER}\n".encode())
            await self._writer.drain()

            await asyncio.sleep(INIT_WAIT_AFTER_XQ)

            # Flush any buffered data
            while self._reader and not self._reader.at_eof():
                try:
                    await asyncio.wait_for(self._reader.readline(), timeout=0.5)
                except asyncio.TimeoutError:
                    break

            # Query version
            self._writer.write(f"{CMD_VERSION}\n".encode())
            await self._writer.drain()

            # Wait for version response
            version_found = False
            for _ in range(10):  # Try up to 10 lines
                try:
                    line = await asyncio.wait_for(
                        self._reader.readline(), timeout=3.0
                    )
                    text = line.decode("utf-8", errors="replace").strip()
                    _LOGGER.debug("Init received: %s", text)

                    if text.startswith("V "):
                        match = VERSION_PATTERN.match(text)
                        if match:
                            self._firmware_version = match.group(1)
                            self._has_cc1101 = "cc1101" in text.lower()
                            version_found = True
                            break
                except asyncio.TimeoutError:
                    break

            if not version_found:
                _LOGGER.error("SIGNALduino did not respond with version")
                return False

            # Enable receiver
            self._writer.write(f"{CMD_ENABLE_RECEIVER}\n".encode())
            await self._writer.drain()

            return True

        except Exception:
            _LOGGER.exception("Init sequence failed")
            return False

    async def _read_loop(self) -> None:
        """Continuously read and dispatch messages from the serial port."""
        buffer = b""
        while not self._closing and self._reader:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(4096), timeout=KEEPALIVE_INTERVAL + 30
                )
                if not data:
                    _LOGGER.warning("Serial connection lost (EOF)")
                    await self._trigger_reconnect()
                    return

                buffer += data
                # Process complete lines
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._process_line(line.decode("utf-8", errors="replace").strip())

                # Process binary-framed messages (\x02...\x03)
                while b"\x02" in buffer and b"\x03" in buffer:
                    start = buffer.index(b"\x02")
                    end = buffer.index(b"\x03", start)
                    frame = buffer[start + 1 : end]
                    buffer = buffer[end + 1 :]
                    self._process_line(frame.decode("utf-8", errors="replace").strip())

            except asyncio.TimeoutError:
                _LOGGER.debug("Read timeout, will be handled by keepalive")
            except asyncio.CancelledError:
                return
            except Exception:
                if not self._closing:
                    _LOGGER.exception("Error in read loop")
                    await self._trigger_reconnect()
                return

    def _process_line(self, line: str) -> None:
        """Process a single line received from SIGNALduino."""
        if not line:
            return

        _LOGGER.debug("Received: %s", line)

        # Reset keepalive counter on any received data
        self._keepalive_retries = 0

        # Check for OK response (keepalive pong)
        if line == "OK":
            return

        # Check for SOMFY message (Ys prefix)
        somfy_match = SOMFY_MSG_PATTERN.match(line)
        if somfy_match:
            hex_data = somfy_match.group(1)
            _LOGGER.debug("SOMFY frame received: %s", hex_data)
            if self._on_somfy_frame:
                self._on_somfy_frame(hex_data)
            return

        if line.startswith(("P13#", "P13.1#", "P13.2#")):
            protocol, hex_data = line.split("#", 1)
            _LOGGER.debug(
                "FLAMINGO %s frame received: %s",
                protocol,
                hex_data,
            )
            if self._on_flamingo_frame:
                self._on_flamingo_frame(protocol, hex_data)
            return

        # Check for dispatched protocol message (P43#...)
        if line.startswith("P43#"):
            hex_data = line.split("#")[1] if "#" in line else ""
            _LOGGER.debug("SOMFY P43 frame received: %s", hex_data)
            if self._on_somfy_frame:
                self._on_somfy_frame(hex_data)
            return

        # Log other messages for debugging
        if line.startswith("V "):
            _LOGGER.debug("Version info: %s", line)
        elif line.startswith("M"):
            _LOGGER.debug("Raw message: %s", line[:80])

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive pings."""
        while not self._closing and self._state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)

                if self._closing:
                    return

                self._keepalive_retries += 1
                if self._keepalive_retries > KEEPALIVE_MAX_RETRIES:
                    _LOGGER.warning(
                        "Keepalive failed after %d retries, reconnecting",
                        KEEPALIVE_MAX_RETRIES,
                    )
                    await self._trigger_reconnect()
                    return

                if self._writer:
                    self._writer.write(f"{CMD_PING}\n".encode())
                    await self._writer.drain()
                    _LOGGER.debug(
                        "Keepalive ping sent (retry %d/%d)",
                        self._keepalive_retries,
                        KEEPALIVE_MAX_RETRIES,
                    )

            except asyncio.CancelledError:
                return
            except Exception:
                if not self._closing:
                    _LOGGER.exception("Keepalive error")
                    await self._trigger_reconnect()
                return

    async def _trigger_reconnect(self) -> None:
        """Initiate reconnection."""
        if self._closing or self._state == ConnectionState.RECONNECTING:
            return

        self._state = ConnectionState.RECONNECTING
        self._notify_connection(False)
        self._cancel_tasks(cancel_reconnect=False)
        await self._close_serial()

        # Start reconnect loop
        self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        while not self._closing:
            delay_idx = min(self._reconnect_attempt, len(RECONNECT_DELAYS) - 1)
            delay = RECONNECT_DELAYS[delay_idx]
            self._reconnect_attempt += 1

            _LOGGER.info(
                "Reconnect attempt %d in %ds", self._reconnect_attempt, delay
            )
            await asyncio.sleep(delay)

            if self._closing:
                return

            success = await self.async_connect()
            if success:
                return

        self._state = ConnectionState.DISCONNECTED

    def _cancel_tasks(self, cancel_reconnect: bool = True) -> None:
        """Cancel background tasks."""
        for task_attr in ("_read_task", "_keepalive_task"):
            task = getattr(self, task_attr, None)
            if task and not task.done():
                task.cancel()
            setattr(self, task_attr, None)

        if cancel_reconnect and self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

    async def _close_serial(self) -> None:
        """Close the serial connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    def _notify_connection(self, connected: bool) -> None:
        """Notify connection state change."""
        if self._on_connection_change:
            self._on_connection_change(connected)


async def validate_port_accessible(port: str) -> str | None:
    """Check if a serial port exists and is accessible.

    Returns an error key string if there's a problem, or None if accessible.
    """
    import os
    import errno

    if not os.path.exists(port):
        _LOGGER.error("Serial port does not exist: %s", port)
        return "port_not_found"

    try:
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        os.close(fd)
    except OSError as err:
        if err.errno == errno.EBUSY:
            _LOGGER.error(
                "Serial port %s is busy (another process is using it)", port
            )
            return "port_busy"
        if err.errno == errno.EACCES:
            _LOGGER.error("Permission denied for serial port %s", port)
            return "port_permission"
        _LOGGER.error("Cannot access serial port %s: %s", port, err)
        return "cannot_connect"

    return None


async def validate_connection(port: str, baud_rate: int = DEFAULT_BAUD_RATE) -> str | None:
    """Validate a serial connection and return firmware version.

    Used during config flow to verify the device is a SIGNALduino.
    Returns firmware version string on success, None on failure.
    """
    try:
        url = port
        if url.startswith("tcp://"):
            url = "socket://" + url[6:]

        reader, writer = await open_serial_connection(
            url=url, baudrate=baud_rate
        )
    except Exception:
        _LOGGER.error(
            "Cannot open serial port %s (is another process using it?)", port, exc_info=True
        )
        return None

    try:
        _LOGGER.debug("Validating SIGNALduino on %s...", port)

        # Disable receiver
        writer.write(f"{CMD_DISABLE_RECEIVER}\n".encode())
        await writer.drain()
        await asyncio.sleep(INIT_WAIT_AFTER_XQ)

        # Flush any buffered data
        while True:
            try:
                await asyncio.wait_for(reader.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                break

        # Query version
        writer.write(f"{CMD_VERSION}\n".encode())
        await writer.drain()

        received_lines: list[str] = []

        for attempt in range(10):
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                text = line.decode("utf-8", errors="replace").strip()
                received_lines.append(text)
                if not text:
                    continue
                _LOGGER.debug("Validate received: %r", text)
                match = VERSION_PATTERN.match(text)
                if match:
                    writer.write(f"{CMD_ENABLE_RECEIVER}\n".encode())
                    await writer.drain()
                    _LOGGER.info("SIGNALduino version detected: %s", match.group(1))
                    return match.group(1)
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout on attempt %d", attempt)
                break

        _LOGGER.error(
            "SIGNALduino on %s did not respond with a valid version string. "
            "Received lines: %r", port, received_lines
        )
        return None

    except Exception:
        _LOGGER.error("Error during validation of %s", port, exc_info=True)
        return None

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
