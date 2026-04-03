# SIGNALduino

Home Assistant integration for SIGNALduino RF receiver/transmitter hardware. Supports SOMFY RTS protocol for controlling blinds, shutters, and other RF devices via serial connection. I'm using this [SIGNALduino USB stick](https://in-circuit.de/shop/signalduino/), but you can also use a DIY variant (see [FHEM/SIGNALduino](https://wiki.fhem.de/wiki/SIGNALduino)).

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/thecodingdad/ha-signalduino)](https://github.com/thecodingdad/ha-signalduino/releases)

## Features

- Control SOMFY RTS blinds and shutters via SIGNALduino hardware
- Position tracking via drive time calculation
- Serial connection with automatic reconnection (5, 10, 30, 60s backoff)
- Local push-based architecture (event-driven)
- Configurable drive times, signal repeats, and encryption keys
- Invertible position reporting
- Support for all SOMFY RTS commands: MY, STOP, UP, DOWN, PROG, WIND_SUN, WIND_ONLY

## Prerequisites

- Home Assistant 2026.3.0 or newer
- SIGNALduino hardware connected via serial port (e.g. /dev/ttyUSB0)

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=thecodingdad&repository=ha-signalduino&category=integration)

Or add manually:
1. Open HACS in your Home Assistant instance
2. Click the three dots in the top right corner and select **Custom repositories**
3. Enter `https://github.com/thecodingdad/ha-signalduino` and select **Integration** as the category
4. Click **Add**, then search for "SIGNALduino" and download it
5. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/thecodingdad/ha-signalduino/releases)
2. Copy the `custom_components/signalduino` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Setup

1. Go to **Settings** -> **Devices & Services**
2. Click **Add Integration**
3. Search for "SIGNALduino"
4. Follow the setup wizard

### Integration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `serial_port` | string | required | Serial device path |

### Per-Device Options (via Options Flow)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | string | required | Device name |
| `address` | string | required | SOMFY address (6-char hex) |
| `model` | select | -- | `somfyshutter` or `somfyblinds` |
| `drive_time_up` | integer | 20 | Drive time up in seconds |
| `drive_time_down` | integer | 22 | Drive time down in seconds |
| `signal_repeats` | integer | 6 | Number of RF signal repeats |
| `encryption_key` | string | optional | Fixed encryption key |
| `invert_position` | boolean | false | Invert position reporting |

## Entities

The integration creates the following entities for each configured device.

### Covers

| Cover | Description |
|-------|-------------|
| Blind/Shutter | Control with position tracking based on configured drive times |

### Buttons

| Button | Description |
|--------|-------------|
| Custom RF Command | Send custom RF commands to the device |

### Sensors

| Sensor | Description |
|--------|-------------|
| Signal Strength | RF signal strength indicator |
| Device State | Current state of the device |

### Switches

| Switch | Description |
|--------|-------------|
| RF Relay | RF relay control for the device |

### Numbers

| Number | Description |
|--------|-------------|
| Numeric Control | Numeric control inputs for the device |

## Supported SOMFY RTS Commands

| Command | Description |
|---------|-------------|
| MY | Move to favorite position |
| STOP | Stop current movement |
| UP | Open blind/shutter |
| DOWN | Close blind/shutter |
| PROG | Enter programming mode |
| WIND_SUN | Wind and sun sensor mode |
| WIND_ONLY | Wind only sensor mode |

## Multilanguage Support

This integration supports English and German.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
