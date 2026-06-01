# EPUB to PDF

A small Python CLI that converts every `.epub` file in an input folder into a
`.pdf` file in an output folder.

## Setup

Install the tool from this checkout:

```powershell
python -m pip install .
```

For local development, use `python -m pip install -e .` instead.

## Usage

Place EPUB files in `epub/`, then run:

```powershell
epubtopdf
```

The tool creates `pdf/` if needed and writes one PDF per EPUB using the EPUB
file name. Existing PDFs are skipped by default, and a progress bar tracks
batch conversion.

To replace PDFs that already exist:

```powershell
epubtopdf --overwrite
```

You can also choose different folders:

```powershell
epubtopdf --input-dir path\to\epubs --output-dir path\to\pdfs
```

The older `--epub-dir` and `--pdf-dir` options are still accepted as aliases.
Use `--no-progress` to hide the progress bar in scripts or logs.

This converter focuses on readable text extraction from the EPUB spine. It does
not try to preserve exact ebook styling, page layout, or images.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for
details.
