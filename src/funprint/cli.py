"""
Command-line interface for funprint.
"""

import argparse
import asyncio
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from PIL import Image

from .client import AsyncFunPrinter, FunPrinter, FunPrintConnectionError, FunPrintJobError
from .image import save_normalized_image
from .protocol import PRINTER_WIDTH
from .web import WebImageError, discover_image_urls, download_image


IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".dib", ".gif", ".jfif", ".jpe", ".jpeg", ".jpg",
    ".png", ".tif", ".tiff", ".webp",
}


def _positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def _density(value):
    number = int(value)
    if not 0 <= number <= 255:
        raise argparse.ArgumentTypeError("must be between 0 and 255")
    return number


def _positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def _add_image_settings(parser):
    parser.add_argument("--density", type=_density, default=93, help="Printer heat/intensity, 0–255; higher is darker (default: 93)")
    parser.add_argument("--gamma", "-g", type=_positive_float, default=1.0, help="Brightness correction: above 1 lightens, below 1 darkens (default: 1)")
    parser.add_argument("--contrast", type=_positive_float, default=1.0, help="Contrast multiplier; above 1 increases contrast (default: 1)")


def _add_batch_options(parser):
    parser.add_argument("--dry-run", action="store_true", help="List the images without printing or connecting to Bluetooth")
    parser.add_argument("--limit", type=_positive_int, help="Print only the first N images")
    parser.add_argument("--feed", "-f", type=_nonnegative_int, default=80, help="Blank lines after each picture (default: 80)")
    parser.add_argument("--dither", "-d", choices=["floyd", "atkinson", "none"], default="floyd", help="Dithering algorithm (default: floyd)")
    parser.add_argument("--face-focus", action="store_true", help="Auto-crop pictures around faces")
    _add_image_settings(parser)


async def _print_batch(paths, args):
    print("Connecting to printer...", flush=True)
    async with AsyncFunPrinter(address=args.mac) as printer:
        for index, path in enumerate(paths, 1):
            print(f"Printing {index}/{len(paths)}...", flush=True)
            try:
                await printer.print_image(
                    path, feed=args.feed, dither=args.dither, face_focus=args.face_focus,
                    density=args.density, gamma=args.gamma, contrast=args.contrast,
                )
            except FunPrintJobError as exc:
                raise FunPrintJobError(
                    f"Image {index}/{len(paths)} was not confirmed; {index - 1} previous image(s) confirmed. {exc}"
                ) from exc
            print(f"Confirmed {index}/{len(paths)}.", flush=True)


def _print_url(args):
    print(f"Finding images on {args.url}...", flush=True)
    urls = discover_image_urls(args.url)
    if args.limit is not None:
        urls = urls[:args.limit]
    if not urls:
        raise WebImageError(
            "No HTTP image sources found in the page HTML. "
            "Pages that load images only through JavaScript or require a login are not supported."
        )
    print(f"Found {len(urls)} unique image URL(s).", flush=True)
    if args.dry_run:
        for index, url in enumerate(urls, 1):
            print(f"{index}. {url}")
        return

    # Download and validate the entire batch before connecting to the printer.
    with TemporaryDirectory(prefix="funprint-") as directory:
        paths = []
        for index, url in enumerate(urls, 1):
            print(f"Downloading {index}/{len(urls)}: {url}", flush=True)
            path = Path(directory) / f"{index:05d}.png"
            download_image(url, path, referer=args.url, max_width=None if args.face_focus else PRINTER_WIDTH)
            paths.append(path)
        asyncio.run(_print_batch(paths, args))
    print(f"Done! Printed {len(urls)} image(s).")


def _print_folder(args):
    folder = Path(args.path).expanduser()
    if not folder.is_dir():
        raise FunPrintJobError(f"Folder does not exist or is not a directory: {folder}")

    def sort_key(path):
        relative = path.relative_to(folder).as_posix()
        parts = re.split(r"(\d+)", relative.casefold())
        return [int(part) if part.isdecimal() else part for part in parts], relative

    try:
        entries = folder.rglob("*") if args.recursive else folder.iterdir()
        paths = sorted((
            path for path in entries
            if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(folder).parts)
        ), key=sort_key)
    except OSError as exc:
        raise FunPrintJobError(f"Could not read folder {folder}: {exc}") from exc

    if args.limit is not None:
        paths = paths[:args.limit]
    if not paths:
        raise FunPrintJobError(f"No supported image files found in: {folder}")
    print(f"Found {len(paths)} image(s) in {folder}.", flush=True)
    if args.dry_run:
        for index, path in enumerate(paths, 1):
            print(f"{index}. {path}")
        return

    # Stage copies so decoding failures happen before paper is used.
    with TemporaryDirectory(prefix="funprint-") as directory:
        prepared = []
        for index, path in enumerate(paths, 1):
            print(f"Preparing {index}/{len(paths)}: {path.name}", flush=True)
            destination = Path(directory) / f"{index:05d}.png"
            try:
                save_normalized_image(path, destination, max_width=None if args.face_focus else PRINTER_WIDTH)
            except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
                raise FunPrintJobError(f"Could not prepare image {path}: {exc}") from exc
            prepared.append(destination)
        asyncio.run(_print_batch(prepared, args))
    print(f"Done! Printed {len(paths)} image(s).")


async def _scan_printers():
    """Show nearby Fun Print printers and the BLE addresses used by this CLI."""
    from bleak import BleakScanner
    from bleak.exc import BleakError

    try:
        devices = await BleakScanner.discover(timeout=6.0)
    except (BleakError, OSError) as exc:
        raise FunPrintConnectionError(f"Bluetooth scan failed: {exc}") from exc

    printers = [
        device for device in devices
        if device.name and ("MX" in device.name or "Fun" in device.name)
    ]
    if not printers:
        print("No nearby Fun Print printers found. Turn the printer on and try again.")
        return

    print("Nearby Fun Print printers (use the address with --mac):")
    for device in printers:
        print(f"  {device.name}\t{device.address}")


def main():
    parser = argparse.ArgumentParser(
        prog="funprint",
        description="Print to Fun Print / Yintibao (MXW01) Thermal Printers via BLE"
    )
    parser.add_argument("--mac", "-m", type=str, default="48:0F:57:28:B4:FD", help="Printer Bluetooth MAC address")
    
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # text subcommand
    text_parser = subparsers.add_parser("text", help="Print formatted text")
    text_parser.add_argument("content", type=str, help="Text to print (supports \\n)")
    text_parser.add_argument("--font-size", "-s", type=int, default=22, help="Font size (default: 22)")
    text_parser.add_argument("--align", "-a", choices=["left", "center", "right"], default="center", help="Text alignment")
    text_parser.add_argument("--feed", "-f", type=int, default=80, help="Paper feed lines (default: 80)")

    # image subcommand
    img_parser = subparsers.add_parser("image", help="Print an image file")
    img_parser.add_argument("path", type=str, help="Path to image file (PNG, JPG, BMP)")
    img_parser.add_argument("--feed", "-f", type=int, default=80, help="Paper feed lines (default: 80)")
    img_parser.add_argument("--dither", "-d", choices=["floyd", "atkinson", "none"], default="floyd", help="Dithering algorithm (default: floyd)")
    img_parser.add_argument("--face-focus", action="store_true", help="Auto-detect faces, frame with bust, and choose best orientation")
    _add_image_settings(img_parser)

    # webpage batch subcommand
    url_parser = subparsers.add_parser("url", help="Print all images from a webpage in order")
    url_parser.add_argument("url", help="Public webpage URL or direct image URL")
    _add_batch_options(url_parser)

    folder_parser = subparsers.add_parser("folder", help="Print images from a local folder in filename order")
    folder_parser.add_argument("path", help="Folder containing image files")
    folder_parser.add_argument("--recursive", "-r", action="store_true", help="Include images in subfolders")
    _add_batch_options(folder_parser)

    subparsers.add_parser("scan", help="Find nearby Fun Print printers and show their BLE addresses")


    # feed subcommand
    feed_parser = subparsers.add_parser("feed", help="Advance blank paper")
    feed_parser.add_argument("lines", nargs="?", type=int, default=80, help="Number of blank lines to feed")

    # keepalive subcommand
    keepalive_parser = subparsers.add_parser("keepalive", help="Run background keepalive daemon to prevent printer sleep")
    keepalive_parser.add_argument("--interval", "-i", type=int, default=25, help="Heartbeat interval in seconds (default: 25)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "url":
            _print_url(args)
            return
        if args.command == "folder":
            _print_folder(args)
            return
        if args.command == "scan":
            asyncio.run(_scan_printers())
            return

        printer = FunPrinter(address=args.mac)
        if args.command == "text":
            print(f"Printing text: {args.content[:40]}...")
            printer.print_text(args.content, font_size=args.font_size, align=args.align, feed=args.feed)
            print("Done!")
        elif args.command == "image":
            print(f"Printing image: {args.path} (dither={args.dither}, face_focus={args.face_focus})...")
            printer.print_image(
                args.path, feed=args.feed, dither=args.dither, face_focus=args.face_focus,
                density=args.density, gamma=args.gamma, contrast=args.contrast,
            )
            print("Done!")
        elif args.command == "feed":
            printer.feed_paper(lines=args.lines)
            print("Done!")
        elif args.command == "keepalive":
            import time
            from .protocol import make_command, Command, CTRL_CHAR_UUID

            async def run_daemon():
                print(f"Starting keepalive daemon for {args.mac} (ping every {args.interval}s)...")
                print("While running, your printer will NEVER shut off. Press Ctrl+C to stop.")
                async with AsyncFunPrinter(address=args.mac) as client:
                    pings = 0
                    while client.is_connected:
                        pings += 1
                        cmd = make_command(Command.GET_STATUS, [0x00])
                        await client._client.write_gatt_char(CTRL_CHAR_UUID, cmd, response=False)
                        print(f"[{time.strftime('%H:%M:%S')}] Heartbeat ping #{pings} sent. Printer awake.", end="\r", flush=True)
                        await asyncio.sleep(args.interval)
            asyncio.run(run_daemon())
    except (FunPrintConnectionError, FunPrintJobError, WebImageError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
