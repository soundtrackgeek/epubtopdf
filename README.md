# EPUB to PDF

A small Python CLI that converts every `.epub` file in the `epub/` folder into
a `.pdf` file in the `pdf/` folder.

## Setup

Install the only runtime dependency:

```powershell
python -m pip install -r requirements.txt
```

## Usage

Place EPUB files in `epub/`, then run:

```powershell
python epub_to_pdf.py
```

The tool creates `pdf/` if needed and writes one PDF per EPUB using the EPUB
file name. Existing PDFs are skipped by default.

To replace PDFs that already exist:

```powershell
python epub_to_pdf.py --overwrite
```

You can also choose different folders:

```powershell
python epub_to_pdf.py --epub-dir path\to\epubs --pdf-dir path\to\pdfs
```

This converter focuses on readable text extraction from the EPUB spine. It does
not try to preserve exact ebook styling, page layout, or images.
