"""
Image and text formatting engine for Fun Print thermal printers.
Features Atkinson dithering, gamma compensation, and edge enhancement.
"""

from typing import Union, Literal
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .protocol import PRINTER_WIDTH, PRINTER_WIDTH_BYTES
from .faces import detect_and_frame_faces

DitherType = Literal["atkinson", "floyd", "none", "threshold"]


def apply_gamma(img: Image.Image, gamma: float = 1.4) -> Image.Image:
    """Lifts midtones and shadows using a lookup table to counter thermal dot gain."""
    lut = [int(((i / 255.0) ** (1.0 / gamma)) * 255.0) for i in range(256)]
    return img.point(lut)


def atkinson_dither(img: Image.Image) -> Image.Image:
    """
    Atkinson dithering algorithm:
    Distributes 6/8 (75%) of quantization error across 6 neighbors.
    Discards 25% of error to keep shadow detail open and prevent thermal smudging.
    """
    w, h = img.size
    pixels = list(img.convert("L").getdata())

    for y in range(h):
        y_offset = y * w
        for x in range(w):
            idx = y_offset + x
            old_val = pixels[idx]
            new_val = 255 if old_val > 127 else 0
            pixels[idx] = new_val
            err = (old_val - new_val) // 8

            if err == 0:
                continue

            # +1, 0 and +2, 0
            if x + 1 < w: pixels[idx + 1] = max(0, min(255, pixels[idx + 1] + err))
            if x + 2 < w: pixels[idx + 2] = max(0, min(255, pixels[idx + 2] + err))

            # Row y + 1
            if y + 1 < h:
                y1_offset = (y + 1) * w
                if x - 1 >= 0: pixels[y1_offset + x - 1] = max(0, min(255, pixels[y1_offset + x - 1] + err))
                pixels[y1_offset + x] = max(0, min(255, pixels[y1_offset + x] + err))
                if x + 1 < w: pixels[y1_offset + x + 1] = max(0, min(255, pixels[y1_offset + x + 1] + err))

            # Row y + 2
            if y + 2 < h:
                y2_offset = (y + 2) * w
                pixels[y2_offset + x] = max(0, min(255, pixels[y2_offset + x] + err))

    out_img = Image.new("1", (w, h))
    out_img.putdata(pixels)
    return out_img


def prepare_image(
    image_input: Union[str, Path, Image.Image],
    feed_lines: int = 80,
    dither: Union[bool, DitherType] = "floyd",
    gamma: float = 1.0,
    sharpen: bool = False,
    face_focus: bool = False
) -> tuple[bytearray, int]:
    """
    Loads, scales to 384px, enhances contrast/gamma, dithers to 1-bit, and generates raster bytes.
    """
    if isinstance(image_input, (str, Path)):
        img = Image.open(str(image_input))
    elif isinstance(image_input, Image.Image):
        img = image_input.copy()
    else:
        raise TypeError(f"Expected file path or PIL.Image, got {type(image_input)}")

    # 1. Smart Face & Bust Framing (if requested)
    if face_focus:
        img, _ = detect_and_frame_faces(img, auto_orient=True)

    # 2. Scale width to PRINTER_WIDTH (384px) maintaining aspect ratio
    if img.width != PRINTER_WIDTH:
        ratio = PRINTER_WIDTH / img.width
        new_height = max(1, int(img.height * ratio))
        img = img.resize((PRINTER_WIDTH, new_height), Image.Resampling.LANCZOS)

    # 3. Process image according to dither method
    if dither is True:
        dither_method = "floyd"
    elif dither is False or dither == "none":
        dither_method = "none"
    else:
        dither_method = str(dither).lower()

    if dither_method == "atkinson":
        gray = img.convert("L")
        if gamma and gamma != 1.0:
            gray = apply_gamma(gray, gamma=gamma)
        if sharpen:
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1.5, percent=150, threshold=2))
        img_bw = atkinson_dither(gray)
    elif dither_method == "floyd":
        gray = img.convert("L")
        if gamma and gamma != 1.0:
            gray = apply_gamma(gray, gamma=gamma)
        img_bw = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        # None / Threshold
        img_bw = img.convert("L").convert("1", dither=Image.Dither.NONE)

    width, height = img_bw.size
    pixels = img_bw.load()
    byte_data = bytearray()

    for y in range(height):
        for x in range(0, width, 8):
            byte = 0
            for bit in range(8):
                if x + bit < width and pixels[x + bit, y] == 0:
                    byte |= (1 << bit)
            byte_data.append(byte)

    # 3. Append unified blank paper feed margin if requested
    if feed_lines > 0:
        blank_row = bytes(PRINTER_WIDTH_BYTES)
        for _ in range(feed_lines):
            byte_data.extend(blank_row)
        total_lines = height + feed_lines
    else:
        total_lines = height

    return byte_data, total_lines


def text_to_image(
    text: str,
    font_size: int = 22,
    align: str = "center",
    padding_y: int = 30
) -> Image.Image:
    """
    Renders multiline text onto a 384px wide PIL image.
    """
    lines = text.strip().split("\n")
    font = ImageFont.load_default()
    line_height = font_size + 8

    height = max(100, len(lines) * line_height + padding_y * 2)
    img = Image.new('L', (PRINTER_WIDTH, height), color=255)
    draw = ImageDraw.Draw(img)

    y = padding_y
    for line in lines:
        line_clean = line.rstrip()
        bbox = draw.textbbox((0, 0), line_clean, font=font)
        text_w = bbox[2] - bbox[0]
        
        if align == "center":
            x = max(10, (PRINTER_WIDTH - text_w) // 2)
        elif align == "right":
            x = max(10, PRINTER_WIDTH - text_w - 20)
        else:
            x = 20

        draw.text((x, y), line_clean, fill=0, font=font)
        y += line_height

    return img
