"""SOMFY RTS protocol encoding, decoding, and cryptography.

All functions are pure (no side effects) and operate on raw data types 
for testability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .const import (
    DEFAULT_DRIVE_TIME_DOWN,
    DEFAULT_DRIVE_TIME_UP,
    MODEL_SHUTTER,
    SOMFY_CMD_DOWN,
    SOMFY_CMD_MY,
    SOMFY_CMD_PROG,
    SOMFY_CMD_STOP,
    SOMFY_CMD_UP,
    SOMFY_CMD_WIND_ONLY,
    SOMFY_CMD_WIND_SUN,
    SOMFY_COMMAND_NAMES,
    SOMFY_DEFAULT_ENC_KEY,
    SOMFY_DEFAULT_REPEATS,
    SOMFY_ENC_KEY_MASK,
    SOMFY_PROTOCOL_ID,
)

SOMFY_FRAME_LENGTH = 7  # bytes


@dataclass
class SomfyFrame:
    """Decoded SOMFY RTS frame."""

    enc_key: int
    command: int
    rolling_code: int
    address: str  # 6 hex digit string, e.g. "AB1234"

    @property
    def command_name(self) -> str:
        """Return human-readable command name."""
        return SOMFY_COMMAND_NAMES.get(self.command, f"unknown_{self.command:02X}")


@dataclass
class SomfyDevice:
    """Runtime state for a SOMFY device."""

    address: str
    name: str
    model: str = MODEL_SHUTTER
    rolling_code: int = 0
    enc_key: int = SOMFY_DEFAULT_ENC_KEY
    position: int = 0  # 0=closed, 100=open (HA convention)
    drive_time_down: float = DEFAULT_DRIVE_TIME_DOWN
    drive_time_up: float = DEFAULT_DRIVE_TIME_UP
    repeats: int = SOMFY_DEFAULT_REPEATS
    fixed_enc_key: bool = False
    invert_position: bool = False

    def to_dict(self) -> dict:
        """Serialize to storage dict."""
        return {
            "name": self.name,
            "model": self.model,
            "rolling_code": self.rolling_code,
            "enc_key": self.enc_key,
            "position": self.position,
            "drive_time_down": self.drive_time_down,
            "drive_time_up": self.drive_time_up,
            "repeats": self.repeats,
            "fixed_enc_key": self.fixed_enc_key,
            "invert_position": self.invert_position,
        }

    @classmethod
    def from_dict(cls, address: str, data: dict) -> SomfyDevice:
        """Deserialize from storage dict."""
        return cls(
            address=address,
            name=data.get("name", address),
            model=data.get("model", MODEL_SHUTTER),
            rolling_code=data.get("rolling_code", 0),
            enc_key=data.get("enc_key", SOMFY_DEFAULT_ENC_KEY),
            position=data.get("position", 0),
            drive_time_down=data.get("drive_time_down", DEFAULT_DRIVE_TIME_DOWN),
            drive_time_up=data.get("drive_time_up", DEFAULT_DRIVE_TIME_UP),
            repeats=data.get("repeats", SOMFY_DEFAULT_REPEATS),
            fixed_enc_key=data.get("fixed_enc_key", False),
            invert_position=data.get("invert_position", False),
        )


def compute_checksum(frame_bytes: bytes) -> int:
    """Compute SOMFY RTS checksum over 7-byte frame.

    XORs all bytes and their shifted nibbles, masking the command byte
    to upper nibble only at index 1. Returns lower 4 bits.
    """
    checksum = 0
    for i, byte_val in enumerate(frame_bytes):
        val = byte_val & 0xF0 if i == 1 else byte_val
        checksum ^= val ^ (val >> 4)
    return checksum & 0x0F


def xor_encrypt(data: bytes) -> bytes:
    """Apply SOMFY RTS XOR obfuscation (encryption).

    First byte is unencrypted. Each subsequent byte is XORed with
    the previous encrypted byte.
    """
    result = bytearray(len(data))
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] ^ result[i - 1]
    return bytes(result)


def xor_decrypt(data: bytes) -> bytes:
    """Reverse SOMFY RTS XOR obfuscation (decryption).

    First byte is unencrypted. Each subsequent byte is XORed with
    the previous byte from the encrypted input.
    """
    result = bytearray(len(data))
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] ^ data[i - 1]
    return bytes(result)


def encode_frame(
    enc_key: int, command: int, rolling_code: int, address: str
) -> str:
    """Encode a SOMFY RTS frame and return encrypted hex string.

    Args:
        enc_key: Encryption key byte (e.g. 0xA7).
        command: Command code (upper nibble, e.g. 0x20 for UP).
        rolling_code: 16-bit rolling code counter.
        address: 6 hex digit device address (e.g. "AB1234").

    Returns:
        14-character hex string of the encrypted frame.
    """
    # Build 7-byte plaintext frame
    # Byte 0: enc_key
    # Byte 1: command (upper nibble), checksum will go in lower nibble
    # Byte 2-3: rolling_code (big-endian)
    # Byte 4-6: address bytes (reversed for wire format)
    addr_bytes = bytes.fromhex(address)
    frame = bytearray(SOMFY_FRAME_LENGTH)
    frame[0] = enc_key & 0xFF
    frame[1] = command & 0xF0  # command in upper nibble, checksum placeholder
    frame[2] = (rolling_code >> 8) & 0xFF
    frame[3] = rolling_code & 0xFF
    # Address bytes reversed for SIGNALduino wire format
    frame[4] = addr_bytes[2]
    frame[5] = addr_bytes[1]
    frame[6] = addr_bytes[0]

    # Compute and insert checksum
    checksum = compute_checksum(bytes(frame))
    frame[1] = (frame[1] & 0xF0) | (checksum & 0x0F)

    # Encrypt
    encrypted = xor_encrypt(bytes(frame))
    return encrypted.hex().upper()


def decode_frame(hex_data: str) -> SomfyFrame | None:
    """Decode an encrypted SOMFY RTS frame from hex string.

    Args:
        hex_data: Hex string (14 characters) of encrypted frame data.

    Returns:
        Decoded SomfyFrame or None if checksum validation fails.
    """
    if len(hex_data) < 14:
        return None

    encrypted = bytes.fromhex(hex_data[:14])
    decrypted = xor_decrypt(encrypted)

    # Verify checksum
    expected_checksum = decrypted[1] & 0x0F
    # Zero out checksum nibble for verification
    verify_frame = bytearray(decrypted)
    verify_frame[1] = verify_frame[1] & 0xF0
    computed = compute_checksum(bytes(verify_frame))
    if computed != expected_checksum:
        return None

    enc_key = decrypted[0]
    command = decrypted[1] & 0xF0
    rolling_code = (decrypted[2] << 8) | decrypted[3]
    # Reverse address bytes back to original order
    address = f"{decrypted[6]:02X}{decrypted[5]:02X}{decrypted[4]:02X}"

    return SomfyFrame(
        enc_key=enc_key,
        command=command,
        rolling_code=rolling_code,
        address=address,
    )


def build_send_command(
    encrypted_hex: str,
    repeats: int = SOMFY_DEFAULT_REPEATS,
    has_cc1101: bool = True,
) -> list[str]:
    """Build the firmware commands to send a SOMFY RTS frame.

    The SIGNALduino firmware needs the raw SR/SM commands, not "sendMsg".
    SOMFY RTS uses manchester encoding with a hardware wakeup preamble.

    Protocol 43 definition (from https://github.com/fhem/fhem-mirror/blob/master/fhem/FHEM/lib/SD_ProtocolData.pm):
    - format: manchester
    - clockrange: [610, 680] -> clock = 645
    - msgIntro: SR;P0=-2560;P1=2560;P3=-640;D=10101010101010113;
    - frequency: 10AB85550A (433.42 MHz)

    Returns a list of command strings to send sequentially.
    """
    # SOMFY RTS clock: midpoint of clockrange [610, 680]
    clock = 645

    # Frequency register for 433.42 MHz (SOMFY uses 433.42, not 433.92)
    # CC1101 register value: 10AB85550A
    freq_setting = "F=10AB85550A;" if has_cc1101 else ""

    # The complete send sequence:
    # 1. SC (Send Combined): wakeup preamble + manchester data
    #    The SC command chains an SR (raw send) intro with SM (manchester) data
    commands = [
        f"SC;R={repeats};"
        f"SR;P0=-2560;P1=2560;P3=-640;D=10101010101010113;"
        f"SM;C={clock};D={encrypted_hex};"
        f"{freq_setting}",
    ]
    return commands


def increment_enc_key(key: int) -> int:
    """Increment encryption key with SOMFY mask.

    The upper nibble is preserved (stays 0xA_) by masking with 0xAF.
    """
    return (key + 1) & SOMFY_ENC_KEY_MASK


def increment_rolling_code(code: int) -> int:
    """Increment rolling code, wrapping at 16-bit boundary."""
    return (code + 1) & 0xFFFF
