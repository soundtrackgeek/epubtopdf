"""Convert EPUB files from an input folder into PDF files.

This keeps the tool intentionally small: EPUB structure is read with the
standard library, while PDF generation is handled by reportlab.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote
from xml.etree import ElementTree
from xml.sax.saxutils import escape

try:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
except ImportError as exc:  # pragma: no cover - exercised by users without deps
    raise SystemExit(
        "Missing dependency: reportlab. Install it with `python -m pip install .`."
    ) from exc

try:
    from tqdm import tqdm
except ImportError as exc:  # pragma: no cover - exercised by users without deps
    raise SystemExit(
        "Missing dependency: tqdm. Install it with `python -m pip install .`."
    ) from exc


EPUB_GLOB = "*.epub"
VERSION = "0.2.0"


@dataclass(frozen=True)
class TextBlock:
    text: str
    kind: str = "paragraph"
    level: int = 0


class EpubError(RuntimeError):
    """Raised when an EPUB cannot be read well enough to convert."""


class HTMLTextExtractor(HTMLParser):
    """Extract simple readable text blocks from XHTML/HTML content."""

    BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "header",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
    HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    SKIP_TAGS = {"head", "script", "style", "svg", "math"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[TextBlock] = []
        self._parts: list[str] = []
        self._kind = "paragraph"
        self._level = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.HEADING_TAGS:
            self._finish_block()
            self._kind = "heading"
            self._level = self.HEADING_TAGS[tag]
            return
        if tag == "li":
            self._finish_block()
            self._parts.append("* ")
            return
        if tag == "br":
            self._parts.append("\n")
            return
        if tag in self.BLOCK_TAGS:
            self._finish_block()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in self.HEADING_TAGS or tag == "li" or tag in self.BLOCK_TAGS:
            self._finish_block()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._finish_block()

    def _finish_block(self) -> None:
        text = _normalize_text(" ".join(self._parts))
        if text:
            self.blocks.append(TextBlock(text=text, kind=self._kind, level=self._level))
        self._parts = []
        self._kind = "paragraph"
        self._level = 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results = convert_folder(
            args.input_dir,
            args.output_dir,
            overwrite=args.overwrite,
            show_progress=not args.no_progress,
        )
    except EpubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for result in results:
        status, epub_path, pdf_path, message = result
        if status == "converted":
            print(f"converted: {epub_path.name} -> {pdf_path}")
        elif status == "skipped":
            print(f"skipped: {epub_path.name} ({message})")
        else:
            failures += 1
            print(f"failed: {epub_path.name} ({message})", file=sys.stderr)

    converted = sum(1 for status, *_ in results if status == "converted")
    skipped = sum(1 for status, *_ in results if status == "skipped")
    print(f"done: {converted} converted, {skipped} skipped, {failures} failed")
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert every EPUB in an input folder to PDFs in an output folder."
    )
    parser.add_argument(
        "--input-dir",
        "--epub-dir",
        dest="input_dir",
        type=Path,
        default=Path("epub"),
        help="Folder containing .epub files (default: epub).",
    )
    parser.add_argument(
        "--output-dir",
        "--pdf-dir",
        dest="output_dir",
        type=Path,
        default=Path("pdf"),
        help="Folder where .pdf files will be written (default: pdf).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing PDF files instead of skipping them.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Hide the tqdm progress bar.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    args = parser.parse_args(argv)
    args.epub_dir = args.input_dir
    args.pdf_dir = args.output_dir
    return args


def convert_folder(
    epub_dir: Path, pdf_dir: Path, *, overwrite: bool = False, show_progress: bool = False
) -> list[tuple[str, Path, Path, str]]:
    epub_dir = epub_dir.expanduser()
    pdf_dir = pdf_dir.expanduser()

    if not epub_dir.exists():
        raise EpubError(f"EPUB folder does not exist: {epub_dir}")
    if not epub_dir.is_dir():
        raise EpubError(f"EPUB path is not a folder: {epub_dir}")

    pdf_dir.mkdir(parents=True, exist_ok=True)
    epub_files = sorted(epub_dir.glob(EPUB_GLOB))
    if not epub_files:
        raise EpubError(f"No EPUB files found in {epub_dir}")

    results: list[tuple[str, Path, Path, str]] = []
    epub_iterable = (
        tqdm(epub_files, desc="Converting EPUBs", unit="file") if show_progress else epub_files
    )
    for epub_path in epub_iterable:
        pdf_path = pdf_dir / f"{_clean_filename(epub_path.stem)}.pdf"
        if pdf_path.exists() and not overwrite:
            results.append(("skipped", epub_path, pdf_path, "PDF already exists"))
            continue
        try:
            convert_epub(epub_path, pdf_path)
        except Exception as exc:  # noqa: BLE001 - keep batch conversion going
            results.append(("failed", epub_path, pdf_path, str(exc)))
        else:
            results.append(("converted", epub_path, pdf_path, ""))
    return results


def convert_epub(epub_path: Path, pdf_path: Path) -> None:
    blocks = list(read_epub_text_blocks(epub_path))
    if not blocks:
        raise EpubError("no readable text was found")
    write_pdf(blocks, pdf_path, title=epub_path.stem)


def read_epub_text_blocks(epub_path: Path) -> Iterable[TextBlock]:
    if not zipfile.is_zipfile(epub_path):
        raise EpubError("file is not a valid EPUB zip archive")

    with zipfile.ZipFile(epub_path) as book:
        opf_path = _find_opf_path(book)
        manifest, spine = _read_package(book, opf_path)
        html_paths = _spine_html_paths(manifest, spine, opf_path)
        if not html_paths:
            raise EpubError("EPUB spine did not contain HTML content")

        for html_path in html_paths:
            try:
                html_bytes = book.read(html_path)
            except KeyError:
                continue
            extractor = HTMLTextExtractor()
            extractor.feed(_decode_html(html_bytes))
            extractor.close()
            yield from extractor.blocks


def write_pdf(blocks: Iterable[TextBlock], pdf_path: Path, *, title: str) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = _pdf_styles()
    story = []

    for block in blocks:
        if block.kind == "heading":
            style = styles.get(f"Heading{min(max(block.level, 1), 3)}", styles["Heading3"])
            story.append(Spacer(1, 0.08 * inch))
            story.append(Paragraph(escape(block.text), style))
        else:
            story.append(Paragraph(escape(block.text).replace("\n", "<br/>"), styles["Body"]))
        story.append(Spacer(1, 0.08 * inch))

    document = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        title=title,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
    )
    document.build(story)


def _find_opf_path(book: zipfile.ZipFile) -> str:
    try:
        container_xml = book.read("META-INF/container.xml")
    except KeyError as exc:
        raise EpubError("META-INF/container.xml is missing") from exc

    try:
        container = ElementTree.fromstring(container_xml)
    except ElementTree.ParseError as exc:
        raise EpubError("META-INF/container.xml could not be parsed") from exc

    rootfile = container.find(".//{*}rootfile")
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise EpubError("EPUB container does not point to an OPF package")
    return _zip_path(rootfile.attrib["full-path"])


def _read_package(
    book: zipfile.ZipFile, opf_path: str
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    try:
        package_xml = book.read(opf_path)
    except KeyError as exc:
        raise EpubError(f"OPF package is missing: {opf_path}") from exc

    try:
        package = ElementTree.fromstring(package_xml)
    except ElementTree.ParseError as exc:
        raise EpubError("OPF package could not be parsed") from exc

    manifest_el = package.find(".//{*}manifest")
    spine_el = package.find(".//{*}spine")
    if manifest_el is None or spine_el is None:
        raise EpubError("OPF package is missing manifest or spine")

    manifest: dict[str, tuple[str, str]] = {}
    for item in manifest_el.findall("{*}item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = (href, item.attrib.get("media-type", ""))

    spine = [
        itemref.attrib["idref"]
        for itemref in spine_el.findall("{*}itemref")
        if itemref.attrib.get("idref") and itemref.attrib.get("linear", "yes").lower() != "no"
    ]
    return manifest, spine


def _spine_html_paths(
    manifest: dict[str, tuple[str, str]], spine: list[str], opf_path: str
) -> list[str]:
    opf_base = posixpath.dirname(opf_path)
    html_paths: list[str] = []
    for item_id in spine:
        href, media_type = manifest.get(item_id, ("", ""))
        if not href:
            continue
        if media_type not in {"application/xhtml+xml", "text/html", ""}:
            continue
        html_paths.append(_zip_path(posixpath.join(opf_base, href)))
    return html_paths


def _zip_path(path: str) -> str:
    normalized = posixpath.normpath(unquote(path)).replace("\\", "/").lstrip("/")
    if normalized == "." or normalized.startswith("../"):
        raise EpubError(f"unsafe EPUB path: {path}")
    return normalized


def _decode_html(data: bytes) -> str:
    head = data[:2048]
    match = re.search(br"charset=[\"']?([A-Za-z0-9._-]+)", head, flags=re.IGNORECASE)
    encodings = [match.group(1).decode("ascii", "ignore")] if match else []
    encodings.extend(["utf-8", "cp1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_filename(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return clean or "book"


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=11,
            leading=15,
            firstLineIndent=0.18 * inch,
            alignment=TA_LEFT,
            spaceAfter=3,
        ),
        "Heading1": ParagraphStyle(
            "Heading1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceBefore=12,
            spaceAfter=8,
        ),
        "Heading2": ParagraphStyle(
            "Heading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "Heading3": ParagraphStyle(
            "Heading3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            spaceBefore=8,
            spaceAfter=5,
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
