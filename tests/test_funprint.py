"""
Unit tests for funprint library.
"""

from PIL import Image
import pytest
from funprint.protocol import crc8, make_command, Command, PRINTER_WIDTH, PRINTER_WIDTH_BYTES
from funprint.image import prepare_image, text_to_image


def test_crc8():
    # Empty data
    assert crc8(b"") == 0
    # Dallas Maxim CRC-8 test vector
    data = b"\x01\x02\x03\x04"
    assert isinstance(crc8(data), int)
    assert 0 <= crc8(data) <= 255


def test_make_command():
    pkt = make_command(Command.INIT, [0x00])
    assert pkt[0] == 0x22
    assert pkt[1] == 0x21
    assert pkt[2] == 0xB1  # Command.INIT
    assert pkt[3] == 0x00
    assert pkt[4] == 0x01  # Length LO
    assert pkt[5] == 0x00  # Length HI
    assert pkt[6] == 0x00  # Payload
    assert pkt[-1] == 0xFF  # Terminator


def test_image_preparation():
    # Create test image of arbitrary size
    img = Image.new("RGB", (100, 50), color="white")
    byte_data, lines = prepare_image(img, feed_lines=20, dither=True)
    
    # Check width bytes
    assert len(byte_data) % PRINTER_WIDTH_BYTES == 0
    # Lines should include original scaled height + feed lines
    assert lines > 20
    assert len(byte_data) == lines * PRINTER_WIDTH_BYTES


def test_text_to_image():
    img = text_to_image("Hello World\nLine 2")
    assert img.width == PRINTER_WIDTH
    assert img.height >= 100
    assert img.mode == "L"

def test_face_detection():
    from funprint.faces import detect_and_frame_faces
    img = Image.new("RGB", (200, 200), color="white")
    framed, orient = detect_and_frame_faces(img)
    assert framed is not None
    assert isinstance(orient, str)


@pytest.mark.parametrize("dither", ["none", "floyd", "atkinson"])
def test_gamma_and_contrast_change_the_print_raster(dither):
    gradient = Image.new("L", (384, 1))
    gradient.putdata([round(x * 255 / 383) for x in range(384)])
    normal, _ = prepare_image(gradient, feed_lines=0, dither=dither)
    lighter, _ = prepare_image(gradient, feed_lines=0, dither=dither, gamma=1.8)
    higher_contrast, _ = prepare_image(gradient, feed_lines=0, dither=dither, contrast=2.0)
    assert lighter != normal
    assert sum(byte.bit_count() for byte in lighter) < sum(byte.bit_count() for byte in normal)
    if dither != "none":
        assert higher_contrast != normal


def test_print_staging_reduces_large_photos_and_preserves_orientation(tmp_path):
    from funprint.image import save_normalized_image
    image_path = tmp_path / "phone.jpg"
    image = Image.new("RGB", (1600, 1200), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(image_path, exif=exif)
    destination = tmp_path / "staged.png"
    save_normalized_image(image_path, destination, max_width=384)
    with Image.open(destination) as staged:
        assert staged.size == (384, 512)
    with Image.open(image_path) as original:
        assert original.size == (1600, 1200)


if __name__ == "__main__":
    test_crc8()
    test_make_command()
    test_image_preparation()
    test_text_to_image()
    test_face_detection()
    print("All unit tests passed successfully!")
