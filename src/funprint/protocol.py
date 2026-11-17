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


class NotificationParser:
    """Reassemble response headers/payloads across BLE notification chunks.

    Firmware variants use different trailers. The length field covers the
    payload only; trailer bytes are skipped while looking for the next header.
    """

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes | bytearray) -> list[tuple[int, bytes]]:
        self.buffer.extend(data)
        packets = []
        while self.buffer:
            start = self.buffer.find(b"\x22\x21")
            if start < 0:
                self.buffer[:] = b"\x22" if self.buffer[-1] == 0x22 else b""
                break
            del self.buffer[:start]
            if len(self.buffer) < 6:
                break
            length = int.from_bytes(self.buffer[4:6], "little")
            if length > 4096:
                del self.buffer[:2]
                continue
            end = 6 + length
            if len(self.buffer) < end:
                break
            packets.append((self.buffer[2], bytes(self.buffer[6:end])))
            del self.buffer[:end]
        return packets


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
