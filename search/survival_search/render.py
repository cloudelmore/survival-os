"""Prepare stored documents for the built-in viewers.

Library files are untrusted. HTML reaches the dashboard's origin only after sanitising here, and
the Content-Security-Policy header stands behind this as a second layer.
"""

import posixpath
from pathlib import Path
from urllib.parse import quote, unquote

import nh3

from . import extract

ALLOWED_TAGS = {
    "article", "b", "blockquote", "br", "caption", "code", "dd", "div", "dl", "dt", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "kbd", "li",
    "ol", "p", "pre", "s", "section", "small", "span", "strong", "sub", "sup", "table", "tbody",
    "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
ALLOWED_ATTRIBUTES = {"img": {"src", "alt"}, "td": {"colspan", "rowspan"},
                      "th": {"colspan", "rowspan"}}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}


def sanitize(html: str, image_url=None) -> str:
    """Keep document structure only: no scripts, styles, links or remote content."""
    def attribute_filter(tag: str, attribute: str, value: str) -> str | None:
        if tag == "img" and attribute == "src":
            return image_url(value) if image_url else None
        return value

    return nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
                     attribute_filter=attribute_filter, url_schemes=set(), link_rel=None,
                     clean_content_tags={"script", "style", "title"}, strip_comments=True)


def view(path: Path, doc: dict, page: int) -> dict:
    """Return what the viewer shows for one location."""
    fmt = doc["format"]
    if fmt == "txt":
        return {"kind": "text", "text": extract.read_text(path)}
    if fmt == "md":
        return {"kind": "html", "html": sanitize(extract.markdown.render(extract.read_text(path)))}
    if fmt == "html":
        return {"kind": "html", "html": sanitize(extract.read_text(path))}
    if fmt == "epub":
        archive, spine, _ = extract.epub_spine(path)
        with archive:
            if not 1 <= page <= len(spine):
                raise LookupError(page)
            chapter = spine[page - 1]

            def image_url(source: str) -> str | None:
                target = posixpath.normpath(posixpath.join(
                    posixpath.dirname(chapter), unquote(source.split("#")[0])))
                if target.startswith("../") or posixpath.splitext(target)[1].lower() \
                        not in IMAGE_TYPES:
                    return None
                return f"/api/library/documents/{doc['id']}/asset?path={quote(target, safe='')}"

            return {"kind": "html", "html": sanitize(extract.epub_chapter(archive, chapter),
                                                     image_url)}
    return {"kind": "pdf"}


def epub_asset(path: Path, name: str) -> tuple[bytes, str]:
    media_type = IMAGE_TYPES.get(posixpath.splitext(name)[1].lower())
    if media_type is None:
        raise LookupError(name)
    archive, _, _ = extract.epub_spine(path)
    with archive:
        try:
            return extract.epub_chapter_bytes(archive, name), media_type
        except extract.ExtractionError as error:
            raise LookupError(name) from error
