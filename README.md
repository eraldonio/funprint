# funprint

A Python library and CLI tool for **Fun Print / Yintibao / MXW01** mini Bluetooth thermal printers ("Cat Printers").

Reverse-engineered from the official `com.fun.mxw` (*Fun Print by Yintibao*) Android application and firmware specs.

---

## Features

* **Zero Cloud / Offline**: Direct Bluetooth Low Energy (BLE) GATT communication.
* **Sync & Async APIs**: Supports both simple scripts (`FunPrinter`) and asyncio applications (`AsyncFunPrinter`).
* **Paced Transfers**: Sends raster rows with a conservative 12 ms delay and respects the BLE write size.
* **Confirmed Jobs**: Waits for acceptance and completion notifications, checks reported errors, and waits for idle before the next image.
* **Image Settings**: Adjustable hardware density, gamma, contrast, and dithering.
* **High Quality Dithering**: Automatic Floyd-Steinberg dithering and Lanczos scaling for photos and graphics.
* **Unified Paper Margin**: Merges feed margins directly into the raster stream to prevent job aborts.
* **Self-Healing Connection**: Automatically detects and resets stale BlueZ adapter states on Linux.

---

## Installation

Install directly into your Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

---

## CLI Usage

With the virtual environment activated, the `funprint` command is available:

Run these commands from the cloned repository's root directory. Choose your own
printer with the global `--mac` option before the subcommand. On macOS this value
is the device UUID reported by BLE discovery, rather than its hardware MAC
address; the repository's default address belongs to an example device.

For a fresh Mac setup, see [QUICKSTART_FOR_FRIENDS.md](QUICKSTART_FOR_FRIENDS.md).
It covers installing Python and FunPrint, finding the printer, converting a
folder to JPEG, previewing a batch, and printing it.

```bash
# Find nearby Fun Print printers and show their BLE addresses
funprint scan

# Print text
funprint text "Hello World!\nPrinted from Linux CLI."
# Print an image (auto-scaled to 384px with Floyd-Steinberg dithering)
funprint image /path/to/photo.png

# Print with Smart Face & Bust Focus (auto-crops to faces + bust, picks best orientation)
funprint image /path/to/portrait.jpg --face-focus

# Choose dithering algorithm: floyd (default), atkinson, or none
funprint image /path/to/graphic.png --dither atkinson
# Advance paper roll
funprint feed 100

# Keep printer permanently awake (prevents auto-sleep)
funprint keepalive
```

### Print all pictures from a local folder

The helper script `scripts/convert_folder_to_jpeg.py` makes JPEG copies of a
folder of images (originals stay untouched). It saves them into a `JPEG`
subfolder by default:

```bash
python3 scripts/convert_folder_to_jpeg.py "/path/to/photos"
```

Then use `funprint folder` to preview or print that `JPEG` subfolder.

```bash
# List the pictures without connecting to the printer
funprint folder "/path/to/photos" --dry-run

# Print the whole folder as one batch
funprint folder "/path/to/photos"

# Include subfolders, or print only the first 3 pictures
funprint folder "/path/to/photos" --recursive
funprint folder "/path/to/photos" --limit 3 --feed 40
```

Files are printed in natural filename order (`photo2` before `photo10`), ignoring
case. Supported file extensions are PNG, JPEG/JPG/JPE/JFIF, WebP, GIF, BMP/DIB,
TIFF/TIF, and AVIF (when supported by your Pillow installation). Hidden files,
hidden folders, and other file types are excluded. Subfolders are included only
with `--recursive`; their relative paths determine print order.

The command checks and prepares the entire batch before connecting to Bluetooth,
then prints using one connection. Camera orientation is applied, transparency is
placed on white, and animated images use their first frame. Preparation uses
temporary copies and leaves your originals untouched. A damaged or unsupported
image stops the batch before printing begins. `--dither`, `--face-focus`, `--feed`,
and the global `--mac` option also work with this command.

### Adjust image settings

The `image`, `folder`, and `url` commands accept:

| Option | Default | Effect |
| --- | --- | --- |
| `--density 150` | `93` | Sets the printer's heat/intensity from 0 to 255; higher is darker. |
| `--gamma 1.2` | `1.0` | Lightens midtones above 1; values below 1 darken them. |
| `--contrast 1.2` | `1.0` | Increases contrast above 1; values below 1 soften it. |
| `--dither atkinson` | `floyd` | Chooses how grayscale becomes black and white dots. |
| `--feed 40` | `80` | Sets blank raster rows after each picture. |

For example, to print this folder with a darker hardware setting:

```bash
funprint --mac "YOUR_PRINTER_ADDRESS" folder "/path/to/photos" --density 150
```

For a short settings check, add `--limit 1`. Density changes heat, not the
printer's physical resolution, and more heat may slow the printer down. When
face focus is off, temporary photos are reduced to the 384-pixel print width
before PNG staging. The transfer retains conservative row pacing; the old fixed
sleep after every image is replaced by printer responses.

`Confirmed N/total` is shown only after the printer reports completion and idle.
Known paper/error flags and firmware-provided duplicated raster checksums are
checked. A timeout or rejection stops the batch and reports how many earlier
images were confirmed, without automatically reprinting a possibly partial job.
Firmware responses are reverse-engineered, so the first run on a device still
needs a visual check of the paper output.

Protocol references: [MXW01 protocol](https://github.com/jeremy46231/MXW01-catprinter/blob/main/PROTOCOL.md)
and [measured firmware behavior](https://github.com/eliorpom-cmd/print-on-my-desk/blob/main/docs/09-protocol.md).

### Print all pictures from a webpage

Give the `url` command a public webpage URL to print its pictures in page order:

```bash
# List the image URLs without connecting to the printer
funprint url "https://example.com/gallery" --dry-run

# Download all pictures, then print the whole batch
funprint url "https://example.com/gallery"

# Print only the first 3 unique images, with a smaller gap between them
funprint url "https://example.com/gallery" --limit 3 --feed 40

# Choose a specific printer and dithering method
funprint --mac "YOUR_PRINTER_ADDRESS" url "https://example.com/gallery" --dither atkinson
```

The command resolves relative image URLs, handles common lazy-loading attributes
(`data-src`, `data-original`, `data-lazy-src`, `data-srcset`), and chooses the
largest declared image from `srcset`. Duplicate URLs are printed once. Images are
downloaded and checked before printing begins, then printed one after another
through a single Bluetooth connection. Temporary downloads are removed afterward.
If any download fails or contains an unsupported image, the batch stops before
connecting to the printer. A printer error stops the batch; pictures already
printed cannot be undone. Press Ctrl+C to cancel.

This reads images from the page's HTML; it does not run JavaScript, sign into
websites, follow pagination, or load more images by scrolling. Logos and other
`<img>` elements on the page are included, so use `--dry-run` to review the list.
CSS background images and embedded `data:` images are excluded. A direct image URL
also works. Animated images print their first frame. Each image is scaled to
384 pixels wide and converted to black and white by the existing print pipeline.

Downloads time out after 20 seconds per network operation, with limits of 5 MiB
for the initial URL and 25 MiB for each subsequent image. Access restrictions and
server errors are reported as download errors.

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

---

## Development

From the repository root, activate a virtual environment and install the test
dependencies:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

The automated tests use generated images and simulated HTTP/BLE responses;
they do not access the internet or print on a physical device. Printer status
and notification behavior can vary by firmware, so hardware checks are still
needed when changing the protocol.
