# funprint

A Python library and CLI tool for **Fun Print / Yintibao / MXW01** mini Bluetooth thermal printers ("Cat Printers").

Reverse-engineered from the official `com.fun.mxw` (*Fun Print by Yintibao*) Android application and firmware specs.

---

## Features

* **Zero Cloud / Offline**: Direct Bluetooth Low Energy (BLE) GATT communication.
* **Sync & Async APIs**: Supports both simple scripts (`FunPrinter`) and asyncio applications (`AsyncFunPrinter`).
* **Hardware-Paced Pacing**: Transmits at the native ~12ms/line burn rate to prevent buffer overflow and print truncation.
* **High Quality Dithering**: Automatic Floyd-Steinberg dithering and Lanczos scaling for photos and graphics.
* **Unified Paper Margin**: Merges feed margins directly into the raster stream to prevent job aborts.
* **Self-Healing Connection**: Automatically detects and resets stale BlueZ adapter states on Linux.
* **Built-in Weather Receipts**: Pulls live weather from `wttr.in` and formats ready-to-tear receipts.

---

## Installation

Install directly into your Python environment:

```bash
pip install -e /home/joe/funprint
```

---

## CLI Usage

Once installed, the `funprint` command is available system-wide:

```bash
# Print text
funprint text "Hello World!\nPrinted from Linux CLI."
# Print an image (auto-scaled to 384px with Floyd-Steinberg dithering)
funprint image /path/to/photo.png

# Print with Smart Face & Bust Focus (auto-crops to faces + bust, picks best orientation)
funprint image /path/to/portrait.jpg --face-focus

# Choose dithering algorithm: floyd (default), atkinson, or none
funprint image /path/to/graphic.png --dither atkinson
# Print live weather forecast (defaults to Rennes, or specify any city)
funprint weather Rennes
# Advance paper roll
funprint feed 100

# Keep printer permanently awake (prevents auto-sleep)
funprint keepalive
```

---

## Python API Usage

### 1. Synchronous Quickstart

```python
from funprint import FunPrinter

printer = FunPrinter()

# Print text
printer.print_text("Groceries:\n- Apples\n- Coffee\n- Oat Milk")

# Print an image
printer.print_image("badge.png", feed=80)

# Print weather ticket
printer.print_weather("Rennes")

# Advance paper
printer.feed_paper(lines=60)
```

### 2. Asynchronous API

```python
import asyncio
from funprint import AsyncFunPrinter

async def main():
    async with AsyncFunPrinter() as printer:
        await printer.print_text("Async printing is fast!")
        await printer.print_image("cat.png")

asyncio.run(main())
```

---

## Hardware LED Indicator Guide

| LED State | Meaning | Action |
| :--- | :--- | :--- |
| **Blinking Slowly Green** | **Ready & Pairing Mode** | Ready to print. |
| **Solid Green** | **Connected to another device** | Connected to phone app in background. Force-close phone app. |
| **Blinking Red & Green** | **Hardware Error / Open Cover** | Re-seat paper roll and firmly snap cover shut. |
| **Solid Red** | **Low Battery / Charging Standby** | Hold power button for 2–3s to turn ON. |
| **Light is Off** | **Asleep / Powered Off** | Press power button to wake up. |

---

## Protocol Specification

* **MAC Address**: `48:0F:57:28:B4:FD` (Default)
* **Primary Service**: `0000ae30-0000-1000-8000-00805f9b34fb` (macOS: `0000af30`)
* **Control Characteristic**: `0000ae01-0000-1000-8000-00805f9b34fb`
* **Data Characteristic**: `0000ae03-0000-1000-8000-00805f9b34fb`
* **Packet Framing**:
  `0x22 0x21 [CMD] 0x00 [LEN_LO] [LEN_HI] ... [PAYLOAD] [CRC-8] 0xFF`
* **CRC**: Dallas/Maxim CRC-8 (Polynomial `0x07`, Initial `0x00`)
