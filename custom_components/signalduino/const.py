"""Constants for the SIGNALduino integration."""

from homeassistant.const import Platform

DOMAIN = "signalduino"

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Serial defaults
DEFAULT_BAUD_RATE = 57600
KEEPALIVE_INTERVAL = 60  # seconds
KEEPALIVE_MAX_RETRIES = 3
INIT_WAIT_AFTER_XQ = 1.5  # seconds

# Reconnect backoff
RECONNECT_DELAYS = [5, 10, 30, 60]  # seconds

# SIGNALduino commands
CMD_VERSION = "V"
CMD_PING = "P"
CMD_DISABLE_RECEIVER = "XQ"
CMD_ENABLE_RECEIVER = "XE"
CMD_SEND_MSG = "sendMsg"

# SOMFY RTS command codes (upper nibble)
SOMFY_CMD_MY = 0x10
SOMFY_CMD_STOP = 0x10
SOMFY_CMD_UP = 0x20
SOMFY_CMD_DOWN = 0x40
SOMFY_CMD_PROG = 0x80
SOMFY_CMD_WIND_SUN = 0x90
SOMFY_CMD_WIND_ONLY = 0xA0

SOMFY_COMMANDS = {
    "my": SOMFY_CMD_MY,
    "stop": SOMFY_CMD_STOP,
    "up": SOMFY_CMD_UP,
    "down": SOMFY_CMD_DOWN,
    "prog": SOMFY_CMD_PROG,
    "wind_sun": SOMFY_CMD_WIND_SUN,
    "wind_only": SOMFY_CMD_WIND_ONLY,
}

SOMFY_COMMAND_NAMES = {v: k for k, v in SOMFY_COMMANDS.items()}

# SOMFY protocol
SOMFY_PROTOCOL_ID = "P43"
SOMFY_DEFAULT_REPEATS = 6
SOMFY_DEFAULT_ENC_KEY = 0xA0
SOMFY_ENC_KEY_MASK = 0xAF

# SOMFY device models
MODEL_SHUTTER = "somfyshutter"
MODEL_BLIND = "somfyblinds"

SOMFY_MODELS = {
    MODEL_SHUTTER: "Shutter",
    MODEL_BLIND: "Blind",
}

# Position constants
DEFAULT_DRIVE_TIME_DOWN = 20.0  # seconds
DEFAULT_DRIVE_TIME_UP = 22.0  # seconds
POSITION_UPDATE_INTERVAL = 1.0  # seconds

# Config keys
CONF_SERIAL_PORT = "serial_port"
CONF_ADDRESS = "address"
CONF_MODEL = "model"
CONF_DRIVE_TIME_DOWN = "drive_time_down"
CONF_DRIVE_TIME_UP = "drive_time_up"
CONF_REPEATS = "repeats"
CONF_FIXED_ENC_KEY = "fixed_enc_key"
CONF_INVERT_POSITION = "invert_position"

# Dispatcher signals
SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"
SIGNAL_CONNECTION_CHANGED = f"{DOMAIN}_connection"

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = "signalduino.devices"
