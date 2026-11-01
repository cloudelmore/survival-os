"""Turn a document into plain text, one location at a time.

A location is what the viewer can open directly: a PDF page, an EPUB spine item, or the whole of
a TXT, Markdown or HTML file.
"""

import io
import posixpath
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import pypdfium2
from markdown_it import MarkdownIt

MAX_CHUNK = 2000
OVERLAP = 200
MAX_EPUB_MEMBER = 64 * 1024 * 1024
MAX_TEXT_FILE = 64 * 1024 * 1024
# Below this a PDF page is treated as having no usable text layer.
MIN_PAGE_TEXT = 20
OCR_DPI = 200
OCR_TIMEOUT = 120

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"o": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
SKIPPED_TAGS = {"script", "style", "head", "template", "noscript", "svg"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
              "article", "blockquote", "pre", "hr", "td", "th"}

markdown = MarkdownIt("commonmark", {"html": False}).enable("table")


class ExtractionError(Exception):
    """The document cannot be read, and the message is safe to show the user."""


@dataclass
class Location:
    page: int
    label: str
    text: str
    no_text: bool = False


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self.heading = ""
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIPPED_TAGS:
            if tag == "head":
                return
            self.skip += 1
        elif tag == "title":
            self._capture = "title"
        elif tag in ("h1", "h2") and not self.heading:
            self._capture = "heading"
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and tag != "head" and self.skip:
            self.skip -= 1
        if tag in ("title", "h1", "h2"):
            self._capture = None
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self._capture == "title":
            self.title += data
            return
        if self._capture == "heading":
            self.heading += data
        self.parts.append(data)


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    return re.sub(r"\n\s*\n\s*", "\n\n", text).strip()


def html_to_text(html: str) -> tuple[str, str, str]:
    """Return the text, the <title> and the first heading."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return clean_text("".join(parser.parts)), clean_text(parser.title), clean_text(parser.heading)


def chunks(text: str) -> list[str]:
    """Split text into overlapping passages, so a phrase on a boundary is still found."""
    if len(text) <= MAX_CHUNK:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = start + MAX_CHUNK
        if end < len(text):
            cut = max(text.rfind("\n", start + MAX_CHUNK // 2, end),
                      text.rfind(". ", start + MAX_CHUNK // 2, end))
            if cut > start:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - OVERLAP
    return parts


def read_text(path: Path) -> str:
    if path.stat().st_size > MAX_TEXT_FILE:
        raise ExtractionError("File is too large to read as text")
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _open_pdf(path: Path) -> pypdfium2.PdfDocument:
    try:
        return pypdfium2.PdfDocument(path)
    except pypdfium2.PdfiumError as error:
        if "password" in str(error).lower():
            raise ExtractionError("PDF is password protected") from error
        raise ExtractionError("PDF could not be opened") from error


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_page(page: pypdfium2.PdfPage) -> str:
    buffer = io.BytesIO()
    page.render(scale=OCR_DPI / 72, grayscale=True).to_pil().save(buffer, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--dpi", str(OCR_DPI)],
            input=buffer.getvalue(), capture_output=True, timeout=OCR_TIMEOUT, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return clean_text(result.stdout.decode("utf-8", "replace"))


def _pdf_title(pdf: pypdfium2.PdfDocument) -> str:
    try:
        return clean_text(pdf.get_metadata_value("Title"))
    except pypdfium2.PdfiumError:
        return ""


def pdf_locations(path: Path, start: int, ocr: bool) -> Iterator[Location]:
    pdf = _open_pdf(path)
    try:
        for index in range(start, len(pdf)):
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                text = clean_text(textpage.get_text_bounded())
                textpage.close()
                no_text = len(text) < MIN_PAGE_TEXT
                if no_text and ocr:
                    text = _ocr_page(page) or text
                    no_text = len(text) < MIN_PAGE_TEXT
            finally:
                page.close()
            yield Location(index + 1, f"Page {index + 1}", text, no_text)
    finally:
        pdf.close()


def _opf(archive: zipfile.ZipFile) -> tuple[str, ET.Element]:
    container = ET.fromstring(_member(archive, "META-INF/container.xml"))
    rootfile = container.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is None or not rootfile.get("full-path"):
        raise ExtractionError("EPUB has no package file")
    name = rootfile.get("full-path")
    return name, ET.fromstring(_member(archive, name))


def _member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise ExtractionError("EPUB is missing a file it lists") from error
    if info.file_size > MAX_EPUB_MEMBER:
        raise ExtractionError("EPUB holds an oversized file")
    return archive.read(info)


def epub_spine(path: Path) -> tuple[zipfile.ZipFile, list[str], str]:
    """Open an EPUB and return it with its reading order and title. The caller closes it."""
    try:
        archive = zipfile.ZipFile(path)
        name, package = _opf(archive)
    except (zipfile.BadZipFile, ET.ParseError) as error:
        raise ExtractionError("EPUB could not be opened") from error
    if any(info.filename == "META-INF/encryption.xml" for info in archive.infolist()):
        if b"font" not in _member(archive, "META-INF/encryption.xml").lower():
            archive.close()
            raise ExtractionError("EPUB is DRM protected")
    base = posixpath.dirname(name)
    manifest = {item.get("id"): item.get("href", "")
                for item in package.findall("o:manifest/o:item", OPF_NS)}
    spine = []
    for item in package.findall("o:spine/o:itemref", OPF_NS):
        href = manifest.get(item.get("idref"))
        if href:
            spine.append(posixpath.normpath(posixpath.join(base, href)))
    title = package.findtext("o:metadata/dc:title", default="", namespaces=OPF_NS)
    return archive, spine, clean_text(title)


def epub_chapter_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    return _member(archive, name)


def epub_chapter(archive: zipfile.ZipFile, name: str) -> str:
    return _member(archive, name).decode("utf-8", "replace")


def epub_locations(path: Path, start: int) -> Iterator[Location]:
    archive, spine, _ = epub_spine(path)
    with archive:
        for index in range(start, len(spine)):
            text, title, heading = html_to_text(epub_chapter(archive, spine[index]))
            label = heading or title or f"Section {index + 1}"
            yield Location(index + 1, label[:120], text)


def document_info(path: Path, fmt: str) -> tuple[str, int]:
    """Return the title, or an empty string, and the number of locations."""
    if fmt == "pdf":
        pdf = _open_pdf(path)
        try:
            return _pdf_title(pdf), len(pdf)
        finally:
            pdf.close()
    if fmt == "epub":
        archive, spine, title = epub_spine(path)
        archive.close()
        return title, len(spine)
    if fmt == "html":
        _, title, heading = html_to_text(read_text(path))
        return title or heading, 1
    if fmt == "md":
        source = read_text(path)
        match = re.search(r"^#\s+(.+)$", source, re.MULTILINE)
        return clean_text(match.group(1)) if match else "", 1
    read_text(path)
    return "", 1


def locations(path: Path, fmt: str, start: int = 0, ocr: bool = False) -> Iterator[Location]:
    """Yield locations after the first `start`, so indexing can resume part way through."""
    if fmt == "pdf":
        yield from pdf_locations(path, start, ocr)
    elif fmt == "epub":
        yield from epub_locations(path, start)
    elif start == 0:
        source = read_text(path)
        if fmt == "html":
            text = html_to_text(source)[0]
        elif fmt == "md":
            text = html_to_text(markdown.render(source))[0]
        else:
            text = clean_text(source)
        yield Location(1, PurePosixPath(path.name).suffix[1:].upper(), text)
