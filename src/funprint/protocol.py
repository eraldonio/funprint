"""
Low-level binary protocol definition for Fun Print / Yintibao / MXW01 thermal printers.
"""

from enum import IntEnum

PRINTER_WIDTH = 384
PRINTER_WIDTH_BYTES = 48  # 384 pixels / 8 bits per byte

# BLE GATT Service and Characteristic UUIDs
SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
SERVICE_UUID_ALT = "0000af30-0000-1000-8000-00805f9b34fb"

CTRL_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"
DATA_CHAR_UUID = "0000ae03-0000-1000-8000-00805f9b34fb"


class Command(IntEnum):
    GET_STATUS = 0xA1
    SET_INTENSITY = 0xA2
    PRINT_REQUEST = 0xA9
    PRINT_COMPLETE = 0xAA
    INIT = 0xB1
    FLUSH = 0xAD


def crc8(data: bytes | bytearray) -> int:
    """Calculates Dallas/Maxim CRC-8 with polynomial 0x07."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def make_command(cmd_id: int | Command, payload: bytes | bytearray = b"") -> bytes:
    """
    Constructs an MXW01 command frame:
    Header (0x22, 0x21), Command ID, 0x00, Length (LE 16-bit), Payload, CRC-8, 0xFF.
    """
    cmd_val = int(cmd_id)
    payload_bytes = bytes(payload)
    length = len(payload_bytes)
    header = bytes([
        0x22,
        0x21,
        cmd_val,
        0x00,
        length & 0xFF,
        (length >> 8) & 0xFF
    ])
    checksum = crc8(payload_bytes)
    return header + payload_bytes + bytes([checksum, 0xFF])
