"""
Command-line interface for funprint.
"""

import argparse
import sys
from .client import FunPrinter, FunPrintConnectionError, FunPrintJobError


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
    img_parser.add_argument("--gamma", "-g", type=float, default=1.0, help="Gamma lift for thermal dot gain (default: 1.0)")


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

    printer = FunPrinter(address=args.mac)

    try:
        if args.command == "text":
            print(f"Printing text: {args.content[:40]}...")
            printer.print_text(args.content, font_size=args.font_size, align=args.align, feed=args.feed)
            print("Done!")
        elif args.command == "image":
            print(f"Printing image: {args.path} (dither={args.dither}, face_focus={args.face_focus})...")
            printer.print_image(args.path, feed=args.feed, dither=args.dither, face_focus=args.face_focus)
            print("Done!")
        elif args.command == "feed":
            printer.feed_paper(lines=args.lines)
            print("Done!")
        elif args.command == "keepalive":
            import asyncio
            import time
            from .client import AsyncFunPrinter
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
    except (FunPrintConnectionError, FunPrintJobError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
