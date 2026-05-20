#!python3
"""OCR the image pages of a bundle PDF and save per-page text sidecars.

Renders each pdfplumber-empty page to PNG via pdftoppm, runs Tesseract on
each PNG, and writes the recognized text to <out_dir>/page_NNNN.txt.

Text-extractable pages are passed through (their pdfplumber text is
written to the same sidecar layout) so split_bundle.py can read a single
source-of-truth directory regardless of whether each page came from the
PDF text layer or from OCR.

Usage:
    python3 -m extractors.prr.transit.ocr_bundle \\
        --bundle 'data/transit/.../Installment 11.pdf' \\
        --out-dir data/transit/ocr/Installment_11/
"""

import argparse
import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


IMAGE_THRESHOLD = 20


def render_page_to_png(bundle, page_num, out_png, dpi=300):
    """Render a single page of `bundle` to `out_png` via pdftoppm.

    pdftoppm with -singlefile writes <stem>.png exactly (no -NN suffix).
    """
    stem = str(out_png)
    if stem.endswith(".png"):
        stem = stem[:-4]
    cmd = [
        "pdftoppm", "-png", "-r", str(dpi),
        "-f", str(page_num), "-l", str(page_num),
        "-singlefile",
        str(bundle), stem,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def ocr_png(png_path, psm=6, lang="eng"):
    """Run tesseract on a PNG and return the recognized text.

    psm=6 ("Assume a single uniform block of text.") works well for
    printed-Outlook page layouts where the header is a tight block at the
    top followed by body paragraphs.
    """
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
        stem = f.name
    try:
        cmd = ["tesseract", str(png_path), stem,
               "--psm", str(psm), "-l", lang]
        subprocess.run(cmd, check=True, capture_output=True)
        txt_path = Path(stem + ".txt")
        text = txt_path.read_text(encoding="utf-8", errors="replace")
        return text
    finally:
        for ext in (".txt",):
            p = Path(stem + ext)
            if p.exists():
                p.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--psm", type=int, default=6,
                        help="tesseract page segmentation mode (default 6)")
    parser.add_argument("--lang", default="eng")
    parser.add_argument("--all-pages", action="store_true",
                        help="OCR every page (default: skip pages where "
                        "pdfplumber already gets >= threshold chars)")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing sidecar .txt files")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    bundle = Path(args.bundle)
    if not bundle.is_file():
        sys.exit(f"--bundle {bundle} does not exist")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: classify pages and write pdfplumber text for the non-image ones.
    with pdfplumber.open(str(bundle)) as pdf:
        n_pages = len(pdf.pages)
        pages_to_ocr = []
        for i, page in enumerate(pdf.pages, 1):
            sidecar = out_dir / f"page_{i:04d}.txt"
            if sidecar.exists() and not args.force:
                continue
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.warning("page %d pdfplumber error: %s", i, e)
                text = ""
            if args.all_pages or len(text) < IMAGE_THRESHOLD:
                pages_to_ocr.append(i)
            else:
                sidecar.write_text(text, encoding="utf-8")
    logger.info("bundle %s: %d pages, OCRing %d (sidecars in %s)",
                bundle.name, n_pages, len(pages_to_ocr), out_dir)

    # Pass 2: render + OCR.
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        for idx, page_num in enumerate(pages_to_ocr, 1):
            png = Path(tmp) / f"page_{page_num:04d}.png"
            try:
                render_page_to_png(bundle, page_num, png, dpi=args.dpi)
            except subprocess.CalledProcessError as e:
                logger.error("pdftoppm failed on page %d: %s",
                             page_num, e.stderr.decode("utf-8", "replace"))
                continue
            try:
                text = ocr_png(png, psm=args.psm, lang=args.lang)
            except subprocess.CalledProcessError as e:
                logger.error("tesseract failed on page %d: %s",
                             page_num, e.stderr.decode("utf-8", "replace"))
                text = ""
            (out_dir / f"page_{page_num:04d}.txt").write_text(
                text, encoding="utf-8")
            png.unlink(missing_ok=True)
            if idx % 10 == 0 or idx == len(pages_to_ocr):
                logger.info("OCR'd %d/%d (%.1fs elapsed)",
                            idx, len(pages_to_ocr), time.time() - t0)

    logger.info("done in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
