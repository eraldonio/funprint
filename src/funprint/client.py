"""
High-level client interfaces (both Async and Sync) for Fun Print / Yintibao / MXW01 thermal printers.
"""

import asyncio
import logging
import math
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union
from PIL import Image

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .protocol import (
    CTRL_CHAR_UUID,
    DATA_CHAR_UUID,
    NOTIFY_CHAR_UUID,
    PRINTER_WIDTH_BYTES,
    Command,
    NotificationParser,
    crc8,
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
        self._notifications = NotificationParser()
        self._waiters: dict[int, asyncio.Future] = {}
        self._job_lock = asyncio.Lock()

    def _on_notification(self, sender, data):
        for command, payload in self._notifications.feed(data):
            logger.debug("Printer response 0x%02X: %s", command, payload.hex())
            waiter = self._waiters.get(command)
            if waiter is not None and not waiter.done():
                waiter.set_result(payload)

    def _on_disconnect(self, client):
        for waiter in self._waiters.values():
            if not waiter.done():
                waiter.set_exception(FunPrintJobError("Printer disconnected before confirming the job."))

    def _arm_response(self, command):
        future = asyncio.get_running_loop().create_future()
        self._waiters[int(command)] = future
        return future

    async def _wait_response(self, command, future, timeout):
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise FunPrintJobError(
                f"Timed out waiting for printer response 0x{int(command):02X}. "
                "The current image may be incomplete; its print is not confirmed."
            ) from exc
        finally:
            if self._waiters.get(int(command)) is future:
                self._waiters.pop(int(command), None)

    async def _request(self, command, payload=b"\x00", timeout=None):
        future = self._arm_response(command)
        try:
            await self._client.write_gatt_char(CTRL_CHAR_UUID, make_command(command, payload), response=False)
            return await self._wait_response(command, future, timeout or self.timeout)
        finally:
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()
            self._waiters.pop(int(command), None)

    async def _wait_ready(self, timeout):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise FunPrintJobError("Printer stayed busy; the next image was not sent.")
            status = await self._request(Command.GET_STATUS, timeout=min(self.timeout, remaining))
            # Observed A1 fields are frame offsets 6, 12, 15, which become
            # payload offsets 0 (state), 6 (error), 9 (paper), respectively.
            if len(status) < 7:
                raise FunPrintJobError(f"Unrecognized printer status: {status.hex()}")
            if len(status) >= 10 and status[9] == 0x07:
                raise FunPrintJobError("Printer reports no paper. Load the roll and close the cover.")
            if status[6] != 0:
                raise FunPrintJobError(
                    f"Printer reports an error (0x{status[6]:02X}, status {status.hex()}). "
                    "Check the paper, cover, battery, and printer temperature."
                )
            if status[0] == 0:
                return
            if status[0] not in (1, 3):
                raise FunPrintJobError(f"Unrecognized printer state 0x{status[0]:02X}: {status.hex()}")
            await asyncio.sleep(0.25)

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
            try:
                if self.address:
                    device = await BleakScanner.find_device_by_address(self.address, timeout=3.0)
                    devices = [device] if device else []
                else:
                    devices = await BleakScanner.discover(timeout=3.0)
            except (BleakError, OSError) as exc:
                raise FunPrintConnectionError(f"Bluetooth scan failed: {exc}") from exc
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
            if attempt == 1 and self.auto_reset_adapter and sys.platform.startswith("linux"):
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

        self._client = BleakClient(self._device, timeout=self.timeout, disconnected_callback=self._on_disconnect)
        try:
            await self._client.connect()
            self._notifications = NotificationParser()
            await self._client.start_notify(NOTIFY_CHAR_UUID, self._on_notification)
            logger.info(f"Connected to {self._device.name} ({self._device.address})")
            return self
        except Exception as e:
            await self.disconnect()
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
        face_focus: bool = False,
        density: int = 93,
        gamma: float = 1.0,
        contrast: float = 1.0
    ) -> None:
        """
        Prints an image (from file path or PIL Image object) with optional feed margin.
        """
        if not isinstance(density, int) or not 0 <= density <= 255:
            raise FunPrintJobError("Density must be an integer from 0 to 255.")
        if not all(math.isfinite(value) and value > 0 for value in (gamma, contrast)):
            raise FunPrintJobError("Gamma and contrast must be finite numbers greater than zero.")
        if feed < 0:
            raise FunPrintJobError("Paper feed must be zero or greater.")
        async with self._job_lock:
            byte_data, total_lines = prepare_image(
                image, feed_lines=feed, dither=dither, face_focus=face_focus,
                gamma=gamma, contrast=contrast,
            )
            if not 1 <= total_lines <= 65535:
                raise FunPrintJobError("An image including its margin must contain 1 to 65535 rows.")
            if not self.is_connected:
                await self.connect()
            assert self._client is not None
            completion = None
            try:
                await self._client.write_gatt_char(
                    CTRL_CHAR_UUID, make_command(Command.INIT, b"\x00"), response=False
                )
                await asyncio.sleep(0.01)
                await self._client.write_gatt_char(
                    CTRL_CHAR_UUID, make_command(Command.SET_INTENSITY, bytes([density])), response=False
                )
                await asyncio.sleep(0.01)
                await self._wait_ready(self.timeout)
                completion = self._arm_response(Command.PRINT_COMPLETE)
                accepted = await self._request(
                    Command.PRINT_REQUEST,
                    total_lines.to_bytes(2, "little") + bytes([PRINTER_WIDTH_BYTES, 0]),
                )
                if not accepted or accepted[0] != 0:
                    raise FunPrintJobError(f"Printer rejected the image (response {accepted.hex()}).")

                characteristic = self._client.services.get_characteristic(DATA_CHAR_UUID)
                if characteristic is None:
                    raise FunPrintJobError("Printer data characteristic was not found.")
                chunk_size = max(1, min(PRINTER_WIDTH_BYTES, characteristic.max_write_without_response_size))
                for start in range(0, len(byte_data), PRINTER_WIDTH_BYTES):
                    row = byte_data[start:start + PRINTER_WIDTH_BYTES]
                    for offset in range(0, len(row), chunk_size):
                        await self._client.write_gatt_char(DATA_CHAR_UUID, row[offset:offset + chunk_size], response=False)
                    # Retain conservative pacing; completion replaces the old fixed sleep.
                    await asyncio.sleep(0.012)
                await self._client.write_gatt_char(
                    CTRL_CHAR_UUID, make_command(Command.FLUSH, b"\x00"), response=False
                )
                completion_timeout = max(15.0, total_lines / 15.0 + 5.0)
                result = await self._wait_response(Command.PRINT_COMPLETE, completion, completion_timeout)
                if not result or result[0] != 0:
                    raise FunPrintJobError(f"Printer reported unsuccessful completion: {result.hex()}")
                # Some firmware returns a duplicated CRC of the full raster stream.
                if len(result) == 3 and result[1] == result[2] and result[1] != crc8(byte_data):
                    raise FunPrintJobError("Printer image checksum differs from the sent data; print may be truncated.")
                await self._wait_ready(completion_timeout)
            except FunPrintJobError:
                raise
            except Exception as e:
                raise FunPrintJobError(f"Error during print job: {e}") from e
            finally:
                if completion is not None:
                    if not completion.done():
                        completion.cancel()
                    elif not completion.cancelled():
                        completion.exception()  # Consume a disconnect error if another operation failed first.
                    self._waiters.pop(int(Command.PRINT_COMPLETE), None)

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
        face_focus: bool = False,
        density: int = 93,
        gamma: float = 1.0,
        contrast: float = 1.0
    ) -> None:
        asyncio.run(self._run_connected(
            "print_image", image, feed=feed, dither=dither, face_focus=face_focus,
            density=density, gamma=gamma, contrast=contrast,
        ))

    async def _run_connected(self, method, *args, **kwargs):
        async with self._async_printer as printer:
            await getattr(printer, method)(*args, **kwargs)

    def print_text(
        self,
        text: str,
        font_size: int = 22,
        align: str = "center",
        feed: int = 80
    ) -> None:
        asyncio.run(self._run_connected("print_text", text, font_size=font_size, align=align, feed=feed))


    def feed_paper(self, lines: int = 80) -> None:
        asyncio.run(self._run_connected("feed_paper", lines=lines))
