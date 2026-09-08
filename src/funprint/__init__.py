"""
FunPrint - Thermal Printer Driver & Client Library
Reverse-engineered for Fun Print / Yintibao / MXW01 devices.
"""

from .client import (
    FunPrinter,
    AsyncFunPrinter,
    FunPrintConnectionError,
    FunPrintJobError,
)
from .image import prepare_image, text_to_image
from .protocol import (
    PRINTER_WIDTH,
    PRINTER_WIDTH_BYTES,
    Command,
    make_command,
    crc8,
)

__version__ = "0.1.0"
__all__ = [
    "FunPrinter",
    "AsyncFunPrinter",
    "FunPrintConnectionError",
    "FunPrintJobError",
    "prepare_image",
    "text_to_image",
    "PRINTER_WIDTH",
    "PRINTER_WIDTH_BYTES",
    "Command",
    "make_command",
    "crc8",
]
