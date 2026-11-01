"""Build small documents with known text at known locations."""

import zipfile
from pathlib import Path


def write_pdf(path: Path, pages: list[str]) -> None:
    """Write a valid text PDF by hand, so tests need no PDF writer."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * index} 0 R"
            " /Resources << /Font << /F1 3 0 R >> >> >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    body, offsets = b"%PDF-1.4\n", []
    for number, item in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{item}\nendobj\n".encode("latin-1")
    start = len(body)
    table = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    table += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    table += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    path.write_bytes(body + table.encode("latin-1"))


def write_epub(path: Path, title: str, chapters: list[tuple[str, str]]) -> None:
    items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
                    for i in range(len(chapters)))
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", (
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>"))
        archive.writestr("OEBPS/book.opf", (
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata '
            f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title></metadata>'
            f"<manifest>{items}</manifest><spine>{spine}</spine></package>"))
        for index, (heading, text) in enumerate(chapters):
            archive.writestr(f"OEBPS/c{index}.xhtml", (
                f"<html><head><title>{heading}</title><script>evil()</script></head><body>"
                f'<h1>{heading}</h1><p>{text}</p><img src="pic.png"/>'
                '<img src="http://remote.example/x.png"/></body></html>'))
        archive.writestr("OEBPS/pic.png", b"\x89PNG fake")


def build(root: Path) -> None:
    medical = root / "medical_survival"
    medical.mkdir(parents=True)
    write_pdf(medical / "first-aid.pdf", [
        "Introduction to emergency care",
        "Apply direct pressure to control bleeding from a wound",
        "Water purification by boiling for one minute",
    ])
    write_epub(medical / "field.epub", "Field Manual", [
        ("Shelter", "Build a lean-to against the prevailing wind"),
        ("Fire", "Tinder must be kept perfectly dry before striking"),
    ])
    radio = root / "radio"
    radio.mkdir()
    (radio / "bands.md").write_text("# Band Plan\n\nThe **two metre** band carries local repeaters.\n")
    (root / "notes.txt").write_text("Generator oil was changed in March.\n")
    (root / "page.html").write_text(
        "<html><head><title>Knots</title><style>p{color:red}</style></head><body>"
        "<p>The bowline makes a fixed loop.</p><script>alert('rope')</script></body></html>")
