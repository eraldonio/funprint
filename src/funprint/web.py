"""Find and download webpage images before starting a print batch."""

from html.parser import HTMLParser
from http.client import HTTPException
from io import BytesIO
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from .image import save_normalized_image


class WebImageError(Exception):
    """Raised when a page or one of its images cannot be loaded."""


def _http_url(value: str, base_url: str = "") -> str | None:
    try:
        url = urldefrag(urljoin(base_url, value.strip()))[0]
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return url
    except ValueError:
        pass
    return None


def _best_srcset(value: str) -> str:
    """Choose the largest declared width/density, retaining commas in URLs."""
    candidates = []
    remaining = value.strip()
    while remaining:
        remaining = remaining.lstrip(" ,\t\r\n\f")
        if not remaining:
            break
        parts = remaining.split(None, 1)
        url = parts[0]
        remaining = parts[1] if len(parts) == 2 else ""
        if url.endswith(","):
            url = url.rstrip(",")
            descriptor = ""
        else:
            descriptor, _, remaining = remaining.partition(",")
            descriptor = descriptor.strip()
        if descriptor:
            try:
                if descriptor[-1] not in {"w", "x"}:
                    continue
                size = float(descriptor[:-1])
                if size <= 0:
                    continue
            except ValueError:
                continue
        else:
            size = 1.0
        if url and not url.startswith("data:"):
            candidates.append((size, url))
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else ""


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images: list[str] = []
        self.base_href: str | None = None
        self.picture_sources: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "base" and self.base_href is None and attributes.get("href"):
            self.base_href = attributes["href"]
        elif tag == "picture":
            self.picture_sources = []
        elif tag == "source" and self.picture_sources is not None:
            # Prefer broadly supported raster formats to AVIF/SVG-only sources.
            if attributes.get("type", "").lower() in {"", "image/jpeg", "image/png", "image/webp"}:
                source = _best_srcset(attributes.get("data-srcset") or attributes.get("srcset") or "")
                if source:
                    self.picture_sources.append(source)
        elif tag == "img":
            source = _best_srcset(attributes.get("data-srcset") or attributes.get("srcset") or "")
            if not source and self.picture_sources:
                source = self.picture_sources[0]
            if not source:
                source = next((attributes[key] for key in (
                    "data-src", "data-original", "data-lazy-src", "src"
                ) if attributes.get(key)), "")
            if source:
                self.images.append(source)

    def handle_endtag(self, tag):
        if tag == "picture":
            self.picture_sources = None


def extract_image_urls(html: str, base_url: str) -> list[str]:
    """Resolve HTML image sources and deduplicate them in document order."""
    parser = _ImageParser()
    parser.feed(html)
    if parser.base_href:
        base_url = _http_url(parser.base_href, base_url) or base_url
    urls = []
    seen = set()
    for source in parser.images:
        url = _http_url(source, base_url)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _fetch(url: str, *, timeout: float, max_bytes: int, referer: str | None = None):
    if not _http_url(url):
        raise WebImageError(f"Expected an http:// or https:// URL: {url}")
    headers = {"User-Agent": "FunPrint/0.1 (+https://github.com/eraldonio/funprint)"}
    if referer:
        headers["Referer"] = referer
    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise WebImageError(f"Download exceeds {max_bytes // (1024 * 1024)} MiB: {url}")
            return data, response.headers, response.geturl()
    except (OSError, ValueError, HTTPException) as exc:
        raise WebImageError(f"Could not download {url}: {exc}") from exc


def discover_image_urls(url: str, *, timeout: float = 20.0) -> list[str]:
    """Fetch an HTML page (or a direct image URL) and return its image URLs."""
    data, headers, final_url = _fetch(url, timeout=timeout, max_bytes=5 * 1024 * 1024)
    content_type = headers.get_content_type()
    if content_type.startswith("image/"):
        return [final_url]
    if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise WebImageError(f"Expected an HTML page or image, received {content_type}: {final_url}")
    try:
        html = data.decode(headers.get_content_charset() or "utf-8", errors="replace")
    except LookupError as exc:
        raise WebImageError(f"Unsupported page encoding: {exc}") from exc
    return extract_image_urls(html, final_url)


def download_image(url: str, destination: Path, *, referer: str, timeout: float = 20.0, max_width: int | None = None) -> None:
    """Decode an image and save an upright PNG with a white background."""
    data, _, _ = _fetch(url, timeout=timeout, max_bytes=25 * 1024 * 1024, referer=referer)
    try:
        save_normalized_image(BytesIO(data), destination, max_width=max_width)
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise WebImageError(f"Could not decode image {url}: {exc}") from exc
