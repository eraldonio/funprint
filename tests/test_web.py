"""Webpage batches without internet access or printer hardware."""

from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.error import URLError

from PIL import Image
import pytest

from funprint import cli, web
from funprint.client import FunPrintJobError


class Response(BytesIO):
    def __init__(self, data, content_type, url):
        super().__init__(data)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.url = url

    def geturl(self):
        return self.url


def png_bytes(color="white"):
    stream = BytesIO()
    Image.new("RGBA", (20, 10), color).save(stream, "PNG")
    return stream.getvalue()


@pytest.fixture
def website(monkeypatch):
    requests = []
    resources = {
        "https://example.com/start": (
            b'<img src="one.png"><img data-src="two.png"><img src="one.png#again">',
            "text/html; charset=utf-8", "https://example.com/gallery/",
        ),
        "https://example.com/gallery/one.png": (
            png_bytes((0, 0, 0, 0)), "image/png", "https://example.com/gallery/one.png",
        ),
        "https://example.com/gallery/two.png": (
            png_bytes("black"), "image/png", "https://example.com/gallery/two.png",
        ),
    }

    def open_url(request, timeout):
        requests.append(request)
        data, content_type, final_url = resources[request.full_url]
        return Response(data, content_type, final_url)

    monkeypatch.setattr(web, "urlopen", open_url)
    return resources, requests


def test_discovery_resolves_lazy_responsive_picture_and_duplicate_sources():
    html = '''
        <img src="one.png#first">
        <img src="placeholder.gif" data-src="two.png?x=1&amp;y=2">
        <img src="small.png" srcset="small.png 200w, large.png 1200w">
        <img data-srcset="low.png 1x, high.png 2x" src="placeholder.gif">
        <picture>
            <source type="image/avif" srcset="photo.avif 2x">
            <source type="image/webp" srcset="photo.webp 1x, photo-hd.webp 2x">
            <img src="fallback.jpg">
        </picture>
        <img data-original="original.png"><img data-lazy-src="lazy.png">
        <img src="//cdn.example.com/photo.jpg"><img src="one.png#again">
        <img src="data:image/png;base64,123"><img src="javascript:alert(1)">
        <base href="/pictures/">
    '''
    assert web.extract_image_urls(html, "https://example.com/redirected/") == [
        "https://example.com/pictures/one.png",
        "https://example.com/pictures/two.png?x=1&y=2",
        "https://example.com/pictures/large.png",
        "https://example.com/pictures/high.png",
        "https://example.com/pictures/photo-hd.webp",
        "https://example.com/pictures/original.png",
        "https://example.com/pictures/lazy.png",
        "https://cdn.example.com/photo.jpg",
    ]


def test_srcset_keeps_commas_inside_image_urls():
    assert web.extract_image_urls(
        '<img srcset="small.jpg 100w, photo.jpg?crop=1,2 800w">',
        "https://example.com/",
    ) == ["https://example.com/photo.jpg?crop=1,2"]


def test_invalid_base_does_not_lose_relative_images():
    assert web.extract_image_urls(
        '<base href="data:text/html,test"><img src="photo.png">',
        "https://example.com/gallery/",
    ) == ["https://example.com/gallery/photo.png"]


def test_discovery_uses_redirect_url_and_accepts_direct_image(website):
    assert web.discover_image_urls("https://example.com/start") == [
        "https://example.com/gallery/one.png", "https://example.com/gallery/two.png",
    ]
    assert web.discover_image_urls("https://example.com/gallery/one.png") == [
        "https://example.com/gallery/one.png",
    ]


def test_download_flattens_transparency_and_sends_referer(website, tmp_path):
    _, requests = website
    destination = tmp_path / "photo.png"
    web.download_image(
        "https://example.com/gallery/one.png", destination,
        referer="https://example.com/start",
    )
    with Image.open(destination) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)
    assert requests[0].get_header("Referer") == "https://example.com/start"


def test_download_applies_camera_orientation(website, tmp_path):
    resources, _ = website
    original = Image.new("RGB", (20, 10), "white")
    exif = original.getexif()
    exif[274] = 6  # Rotate 90 degrees clockwise for display.
    stream = BytesIO()
    original.save(stream, "JPEG", exif=exif)
    url = "https://example.com/gallery/one.png"
    resources[url] = (stream.getvalue(), "image/jpeg", url)
    destination = tmp_path / "rotated.png"
    web.download_image(url, destination, referer="https://example.com/start")
    with Image.open(destination) as image:
        assert image.size == (10, 20)


def test_network_and_size_errors_are_readable(monkeypatch):
    def offline(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(web, "urlopen", offline)
    with pytest.raises(web.WebImageError, match="offline"):
        web.discover_image_urls("https://example.com/")
    with pytest.raises(web.WebImageError, match="http:// or https://"):
        web.discover_image_urls("file:///tmp/page.html")

    monkeypatch.setattr(web, "urlopen", lambda *a, **k: Response(b"12345", "text/html", "https://example.com/"))
    with pytest.raises(web.WebImageError, match="exceeds"):
        web._fetch("https://example.com/", timeout=1, max_bytes=4)


def test_cli_dry_run_does_not_download_images_or_connect(website, monkeypatch, capsys):
    _, requests = website
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: pytest.fail("Unexpected Bluetooth connection"))
    monkeypatch.setattr("sys.argv", ["funprint", "url", "https://example.com/start", "--dry-run"])
    cli.main()
    assert len(requests) == 1
    assert "2. https://example.com/gallery/two.png" in capsys.readouterr().out


@pytest.mark.parametrize("limit", [None, 1])
def test_cli_downloads_before_one_connection_and_prints_in_order(website, monkeypatch, capsys, limit):
    _, requests = website
    total = limit or 2
    paths = []
    events = []

    class Printer:
        def __init__(self, address):
            assert address == "test-printer"

        async def __aenter__(self):
            assert len(requests) == total + 1
            events.append("connected")
            return self

        async def __aexit__(self, *exc):
            events.append("disconnected")

        async def print_image(self, path, **options):
            assert path.is_file()
            assert options == {
                "feed": 40, "dither": "atkinson", "face_focus": False,
                "density": 93, "gamma": 1.0, "contrast": 1.0,
            }
            with Image.open(path) as image:
                assert image.getpixel((0, 0)) == ((255, 255, 255) if not paths else (0, 0, 0))
            paths.append(path)

    monkeypatch.setattr(cli, "AsyncFunPrinter", Printer)
    argv = ["funprint", "--mac", "test-printer", "url", "https://example.com/start", "--feed", "40", "--dither", "atkinson"]
    if limit:
        argv += ["--limit", str(limit)]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    assert len(paths) == total
    assert events == ["connected", "disconnected"]
    assert all(not path.exists() for path in paths)
    assert f"Done! Printed {total} image(s)." in capsys.readouterr().out


def test_bad_download_aborts_before_bluetooth_and_cleans_up(website, monkeypatch, capsys):
    resources, _ = website
    bad_url = "https://example.com/gallery/two.png"
    resources[bad_url] = (b"not an image", "text/html", bad_url)
    paths = []
    real_download = cli.download_image

    def track_download(url, destination, **kwargs):
        paths.append(destination)
        real_download(url, destination, **kwargs)

    monkeypatch.setattr(cli, "download_image", track_download)
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: pytest.fail("Unexpected Bluetooth connection"))
    monkeypatch.setattr("sys.argv", ["funprint", "url", "https://example.com/start"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert all(not path.parent.exists() for path in paths)
    assert "Could not decode image" in capsys.readouterr().err


def test_printer_failure_disconnects_and_cleans_up(website, monkeypatch, capsys):
    printer = AsyncMock()
    printer.__aenter__.return_value = printer
    printer.print_image.side_effect = FunPrintJobError("disconnected during print")
    monkeypatch.setattr(cli, "AsyncFunPrinter", lambda **kw: printer)
    monkeypatch.setattr("sys.argv", ["funprint", "url", "https://example.com/start"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    printer.__aexit__.assert_awaited_once()
    assert printer.print_image.await_count == 1
    path = printer.print_image.call_args.args[0]
    assert not Path(path).parent.exists()
    output = capsys.readouterr()
    assert "Done!" not in output.out
    assert "disconnected during print" in output.err


@pytest.mark.parametrize("arguments", [["--limit", "0"], ["--feed", "-1"]])
def test_cli_rejects_invalid_batch_options(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["funprint", "url", "https://example.com/start", *arguments])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
