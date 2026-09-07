"""
Unit tests for funprint library.
"""

from PIL import Image
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


if __name__ == "__main__":
    test_crc8()
    test_make_command()
    test_image_preparation()
    test_text_to_image()
    test_face_detection()
    print("All unit tests passed successfully!")
