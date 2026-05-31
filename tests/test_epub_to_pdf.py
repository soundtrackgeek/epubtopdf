import zipfile
from pathlib import Path
from unittest import TestCase

from epub_to_pdf import convert_epub, convert_folder, parse_args, read_epub_text_blocks


class EpubToPdfTests(TestCase):
    def test_reads_spine_text_blocks(self) -> None:
        epub_path = self._make_epub()

        blocks = list(read_epub_text_blocks(epub_path))

        self.assertEqual("Chapter One", blocks[0].text)
        self.assertIn("Hello from the test EPUB.", [block.text for block in blocks])

    def test_converts_single_epub_to_pdf(self) -> None:
        epub_path = self._make_epub()
        pdf_path = self.tmp_path / "out.pdf"

        convert_epub(epub_path, pdf_path)

        self.assertTrue(pdf_path.exists())
        self.assertEqual(b"%PDF", pdf_path.read_bytes()[:4])

    def test_converts_folder_and_skips_existing_pdf(self) -> None:
        epub_dir = self.tmp_path / "epub"
        pdf_dir = self.tmp_path / "pdf"
        epub_dir.mkdir()
        self._make_epub(epub_dir / "sample.epub")

        first = convert_folder(epub_dir, pdf_dir)
        second = convert_folder(epub_dir, pdf_dir)

        self.assertEqual("converted", first[0][0])
        self.assertEqual("skipped", second[0][0])

    def test_accepts_input_and_output_dir_aliases(self) -> None:
        args = parse_args(["--input-dir", "books", "--output-dir", "out"])

        self.assertEqual(Path("books"), args.input_dir)
        self.assertEqual(Path("out"), args.output_dir)
        self.assertEqual(args.input_dir, args.epub_dir)
        self.assertEqual(args.output_dir, args.pdf_dir)

        old_args = parse_args(["--epub-dir", "books", "--pdf-dir", "out"])
        self.assertEqual(Path("books"), old_args.input_dir)
        self.assertEqual(Path("out"), old_args.output_dir)

    def setUp(self) -> None:
        self.tmp_path = Path(self._testMethodName)
        if self.tmp_path.exists():
            for child in sorted(self.tmp_path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                else:
                    child.rmdir()
            self.tmp_path.rmdir()
        self.tmp_path.mkdir()

    def tearDown(self) -> None:
        for child in sorted(self.tmp_path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            else:
                child.rmdir()
        self.tmp_path.rmdir()

    def _make_epub(self, path: Path | None = None) -> Path:
        epub_path = path or self.tmp_path / "sample.epub"
        with zipfile.ZipFile(epub_path, "w") as book:
            book.writestr("mimetype", "application/epub+zip")
            book.writestr(
                "META-INF/container.xml",
                """<?xml version="1.0"?>
                <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                  <rootfiles>
                    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
                  </rootfiles>
                </container>""",
            )
            book.writestr(
                "OEBPS/content.opf",
                """<?xml version="1.0" encoding="UTF-8"?>
                <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                  <manifest>
                    <item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
                  </manifest>
                  <spine>
                    <itemref idref="chap1"/>
                  </spine>
                </package>""",
            )
            book.writestr(
                "OEBPS/chapter1.xhtml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Chapter One</h1>
                    <p>Hello from the test EPUB.</p>
                  </body>
                </html>""",
            )
        return epub_path
