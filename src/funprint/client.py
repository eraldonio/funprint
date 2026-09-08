"""
High-level client interfaces (both Async and Sync) for Fun Print / Yintibao / MXW01 thermal printers.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Union
from PIL import Image

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from .protocol import (
    CTRL_CHAR_UUID,
    DATA_CHAR_UUID,
    PRINTER_WIDTH_BYTES,
    Command,
    make_command,
)
from .image import prepare_image, text_to_image

logger = logging.getLogger("funprint")


class FunPrintConnectionError(Exception):
    """Raised when connection to the printer fails."""
    pass


class FunPrintJobError(Exception):
    """Raised when a print job fails."""
    pass


class AsyncFunPrinter:
    """
    Asynchronous client for Fun Print / Yintibao (MXW01) thermal printers.
    """

    def __init__(
        self,
        address: Optional[str] = "48:0F:57:28:B4:FD",
        timeout: float = 15.0,
        auto_reset_adapter: bool = True
    ):
        self.address = address
        self.timeout = timeout
        self.auto_reset_adapter = auto_reset_adapter
        self._client: Optional[BleakClient] = None
        self._device: Optional[BLEDevice] = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self) -> "AsyncFunPrinter":
        """
        Scans for and connects to the printer. Automatically clears stale BlueZ cache if needed.
        """
        if self.is_connected:
            return self

        logger.info(f"Connecting to printer {self.address}...")
        self._device = None

        for attempt in range(4):
            devices = await BleakScanner.discover(timeout=3.0)
            for d in devices:
                if self.address and d.address.upper() == self.address.upper():
                    self._device = d
                    break
                elif not self.address and d.name and ("MX" in d.name or "Fun" in d.name):
                    self._device = d
                    break

            if self._device:
                break

            # Self-healing: if device is not seen on first pass, reset adapter cache
            if attempt == 1 and self.auto_reset_adapter:
                logger.info("Resetting Bluetooth adapter cache to clear stale state...")
                try:
                    subprocess.run(
                        "bluetoothctl power off && sleep 0.5 && bluetoothctl power on",
                        shell=True,
                        capture_output=True,
                        timeout=5.0
                    )
                except Exception as e:
                    logger.warning(f"Failed to reset adapter: {e}")

            await asyncio.sleep(0.5)

        if not self._device:
            raise FunPrintConnectionError(
                f"Printer {self.address or ''} not found. "
                "Ensure the printer is powered ON and its LED is blinking slowly green."
            )

        self._client = BleakClient(self._device, timeout=self.timeout)
        try:
            await self._client.connect()
            logger.info(f"Connected to {self._device.name} ({self._device.address})")
            return self
        except Exception as e:
            raise FunPrintConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnects from the printer."""
        if self._client and self._client.is_connected:
            await self._client.disconnect()
        self._client = None
        self._device = None

    async def __aenter__(self) -> "AsyncFunPrinter":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def print_image(
        self,
        image: Union[str, Path, Image.Image],
        feed: int = 80,
        dither: Union[bool, str] = "floyd",
        face_focus: bool = False
    ) -> None:
        """
        Prints an image (from file path or PIL Image object) with optional feed margin.
        """
        if not self.is_connected:
            await self.connect()

        byte_data, total_lines = prepare_image(image, feed_lines=feed, dither=dither, face_focus=face_focus)
        assert self._client is not None

        try:
            # 1. Initialize printer
            await self._client.write_gatt_char(
                CTRL_CHAR_UUID,
                make_command(Command.INIT, [0x00]),
                response=False
            )
            await asyncio.sleep(0.05)

            # 2. Declare print dimensions
            await self._client.write_gatt_char(
                CTRL_CHAR_UUID,
                make_command(
                    Command.PRINT_REQUEST,
                    [total_lines & 0xFF, (total_lines >> 8) & 0xFF, PRINTER_WIDTH_BYTES, 0]
                ),
                response=False
            )
            await asyncio.sleep(0.05)

            # 3. Stream raster data paced at the thermal burn rate (12ms / 48-byte row)
            line_count = len(byte_data) // PRINTER_WIDTH_BYTES
            for l in range(line_count):
                row = byte_data[l * PRINTER_WIDTH_BYTES : (l + 1) * PRINTER_WIDTH_BYTES]
                await self._client.write_gatt_char(DATA_CHAR_UUID, row[:24], response=False)
                await self._client.write_gatt_char(DATA_CHAR_UUID, row[24:], response=False)
                await asyncio.sleep(0.012)

            # 4. Flush buffer
            await self._client.write_gatt_char(
                CTRL_CHAR_UUID,
                make_command(Command.FLUSH, [0x00]),
                response=False
            )

            # 5. Allow physical hardware time to finish burning lines
            burn_wait = max(2.5, total_lines * 0.014)
            await asyncio.sleep(burn_wait)

        except Exception as e:
            raise FunPrintJobError(f"Error during print job: {e}") from e

    async def print_text(
        self,
        text: str,
        font_size: int = 22,
        align: str = "center",
        feed: int = 80
    ) -> None:
        """
        Renders and prints text.
        """
        img = text_to_image(text, font_size=font_size, align=align)
        await self.print_image(img, feed=feed, dither=False)


    async def feed_paper(self, lines: int = 80) -> None:
        """
        Advances blank paper by the specified number of lines.
        """
        blank_img = Image.new('L', (PRINTER_WIDTH_BYTES * 8, lines), color=255)
        await self.print_image(blank_img, feed=0, dither=False)


class FunPrinter:
    """
    Synchronous wrapper for Fun Print thermal printers.
    """

    def __init__(
        self,
        address: Optional[str] = "48:0F:57:28:B4:FD",
        timeout: float = 15.0,
        auto_reset_adapter: bool = True
    ):
        self._async_printer = AsyncFunPrinter(
            address=address,
            timeout=timeout,
            auto_reset_adapter=auto_reset_adapter
        )

    def print_image(
        self,
        image: Union[str, Path, Image.Image],
        feed: int = 80,
        dither: Union[bool, str] = "floyd",
        face_focus: bool = False
    ) -> None:
        asyncio.run(self._async_printer.print_image(image, feed=feed, dither=dither, face_focus=face_focus))

    def print_text(
        self,
        text: str,
        font_size: int = 22,
        align: str = "center",
        feed: int = 80
    ) -> None:
        asyncio.run(self._async_printer.print_text(text, font_size=font_size, align=align, feed=feed))


    def feed_paper(self, lines: int = 80) -> None:
        asyncio.run(self._async_printer.feed_paper(lines=lines))
