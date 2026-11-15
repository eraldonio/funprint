"""Local folder batches without printer hardware."""

from PIL import Image
import pytest

from funprint import cli


@pytest.mark.parametrize("options, expected", [
    ([], ["photo1.PNG", "photo2.jpg", "photo10.webp"]),
    (["--recursive"], ["album/photo3.png", "photo1.PNG", "photo2.jpg", "photo10.webp"]),
    (["--recursive", "--limit", "2"], ["album/photo3.png", "photo1.PNG"]),
])
def test_folder_preview_sorts_filters_and_never_connects(tmp_path, monkeypatch, capsys, options, expected):
    folder = tmp_path / "fun images"
    folder.mkdir()
    for name in ["photo10.webp", "photo2.jpg", "photo1.PNG", "notes.txt", ".hidden.png"]:
        (folder / name).touch()
    (folder / "album").mkdir()
    (folder / "album" / "photo3.png").touch()
    (folder / ".hidden").mkdir()
    (folder / ".hidden" / "secret.jpg").touch()
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: pytest.fail("Unexpected Bluetooth connection"))
    monkeypatch.setattr(cli, "save_normalized_image", lambda *a: pytest.fail("Unexpected image decoding in dry run"))
    monkeypatch.setattr("sys.argv", ["funprint", "folder", str(folder), "--dry-run", *options])
    cli.main()
    lines = capsys.readouterr().out.splitlines()
    assert lines[1:] == [f"{index}. {folder / name}" for index, name in enumerate(expected, 1)]


def test_folder_prepares_all_images_then_prints_with_one_connection(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "fun images"
    folder.mkdir()
    Image.new("RGBA", (20, 10), (0, 0, 0, 0)).save(folder / "photo2.png")
    original = Image.new("RGB", (20, 10), "black")
    exif = original.getexif()
    exif[274] = 6
    original.save(folder / "photo10.jpg", exif=exif)
    original_bytes = {path: path.read_bytes() for path in folder.iterdir()}
    prepared = []
    printed = []
    events = []
    normalize = cli.save_normalized_image

    def track_preparation(source, destination, **kwargs):
        normalize(source, destination, **kwargs)
        prepared.append(destination)

    class Printer:
        def __init__(self, address):
            assert address == "test-printer"

        async def __aenter__(self):
            assert len(prepared) == 2
            assert all(path.exists() for path in prepared)
            events.append("connected")
            return self

        async def __aexit__(self, *exc):
            events.append("disconnected")

        async def print_image(self, path, **options):
            assert options == {
                "feed": 30, "dither": "atkinson", "face_focus": True,
                "density": 150, "gamma": 1.2, "contrast": 1.3,
            }
            with Image.open(path) as image:
                if not printed:
                    assert image.size == (20, 10)
                    assert image.getpixel((0, 0)) == (255, 255, 255)
                else:
                    assert image.size == (10, 20)
                    assert image.getpixel((0, 0)) == (0, 0, 0)
            printed.append(path)

    monkeypatch.setattr(cli, "save_normalized_image", track_preparation)
    monkeypatch.setattr(cli, "AsyncFunPrinter", Printer)
    monkeypatch.setattr("sys.argv", [
        "funprint", "--mac", "test-printer", "folder", str(folder),
        "--feed", "30", "--dither", "atkinson", "--face-focus",
        "--density", "150", "--gamma", "1.2", "--contrast", "1.3",
    ])
    cli.main()
    assert events == ["connected", "disconnected"]
    assert printed == prepared
    assert all(not path.parent.exists() for path in prepared)
    assert {path: path.read_bytes() for path in folder.iterdir()} == original_bytes
    assert "Done! Printed 2 image(s)." in capsys.readouterr().out


def test_invalid_image_aborts_before_printing_and_cleans_up(tmp_path, monkeypatch, capsys):
    Image.new("RGB", (10, 10), "white").save(tmp_path / "one.png")
    (tmp_path / "two.jpg").write_bytes(b"invalid image")
    prepared = []
    normalize = cli.save_normalized_image

    def track_preparation(source, destination, **kwargs):
        prepared.append(destination)
        normalize(source, destination, **kwargs)

    monkeypatch.setattr(cli, "save_normalized_image", track_preparation)
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: pytest.fail("Unexpected Bluetooth connection"))
    monkeypatch.setattr("sys.argv", ["funprint", "folder", str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert len(prepared) == 2
    assert all(not path.parent.exists() for path in prepared)
    assert "Could not prepare image" in capsys.readouterr().err


@pytest.mark.parametrize("kind, message", [
    ("empty", "No supported image files"),
    ("missing", "Folder does not exist or is not a directory"),
    ("file", "Folder does not exist or is not a directory"),
])
def test_unusable_folder_is_a_readable_error(tmp_path, monkeypatch, capsys, kind, message):
    folder = tmp_path / "images"
    if kind == "empty":
        folder.mkdir()
        (folder / "notes.txt").touch()
    elif kind == "file":
        folder.touch()
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: pytest.fail("Unexpected Bluetooth connection"))
    monkeypatch.setattr("sys.argv", ["funprint", "folder", str(folder), "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("options", [
    ["--density", "256"], ["--density", "-1"], ["--gamma", "0"],
    ["--gamma", "nan"], ["--contrast", "inf"], ["--contrast", "-2"],
])
def test_invalid_image_settings_are_rejected_before_printing(monkeypatch, options):
    monkeypatch.setattr("sys.argv", ["funprint", "folder", "/unused", *options])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
