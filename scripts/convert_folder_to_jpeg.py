#!/usr/bin/env python3
"""Convert the images in a folder to JPEGs in a separate output folder."""

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {
    ".avif", ".bmp", ".dib", ".gif", ".jfif", ".jpe", ".jpeg", ".jpg",
    ".png", ".tif", ".tiff", ".webp",
}


def convert(source: Path, destination: Path) -> None:
    with Image.open(source) as original:
        # Animated formats use their first frame, matching FunPrint's print flow.
        original.seek(0)
        image = ImageOps.exif_transpose(original).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        background.convert("RGB").save(destination, "JPEG", quality=92, optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert images in one folder to JPEGs, keeping originals untouched."
    )
    parser.add_argument("folder", type=Path, help="Folder containing images")
    parser.add_argument(
        "--output", type=Path,
        help="Where to save JPEGs (default: a 'JPEG' folder inside the input folder)",
    )
    parser.add_argument(
        "--recursive", action="store_true",
        help="Also convert images in subfolders (output is still a single flat folder)",
    )
    args = parser.parse_args()

    folder = args.folder.expanduser().resolve()
    if not folder.is_dir():
        parser.error(f"not a folder: {folder}")

    output = (args.output.expanduser().resolve() if args.output else folder / "JPEG")
    candidates = folder.rglob("*") if args.recursive else folder.iterdir()
    files = sorted(
        path for path in candidates
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and not any(part.startswith(".") for part in path.relative_to(folder).parts)
    )

    if not files:
        print(f"No supported images found in {folder}")
        return 0

    # Avoid silently replacing a different source that shares the same filename stem.
    targets: dict[Path, Path] = {}
    collisions = []
    for source in files:
        target = output / f"{source.stem}.jpg"
        if target in targets:
            collisions.append((targets[target], source, target))
        targets[target] = source
    if collisions:
        print("Some images have the same filename stem and would overwrite each other:", file=sys.stderr)
        for first, second, target in collisions:
            print(f"  {first.name} and {second.name} -> {target.name}", file=sys.stderr)
        print("Rename the source files, then run the command again.", file=sys.stderr)
        return 1

    output.mkdir(parents=True, exist_ok=True)
    converted = 0
    failed = 0
    for source in files:
        target = output / f"{source.stem}.jpg"
        try:
            convert(source, target)
            converted += 1
            print(f"Converted: {source.name} -> {target}")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            failed += 1
            print(f"Could not convert {source}: {exc}", file=sys.stderr)

    print(f"Finished: {converted} converted, {failed} failed. JPEGs are in {output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
