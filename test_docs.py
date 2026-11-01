#!/usr/bin/env python3
"""
Tests that the manual's web page, docs/index.html (served by GitHub Pages at
https://tufts-ebbl.github.io/pebbl/), is up to date with its source,
docs/PEBBL_User_Manual.html:

  - regenerating it with docs/build_manual_pdf.py's pages_index() gives the
    committed file (line endings aside, since git may check it out as CRLF);
  - a changed source gives a different page (negative control);
  - the page links the PDF and the favicon, and those files and docs/.nojekyll
    exist;
  - the logo comes from its static files (branding/make_static_logo.py), whose
    lettering is outlines, and the manual's copy matches branding/pebbl_icon.svg.

If this fails after editing the manual, run
    annotate_env/Scripts/python.exe docs/build_manual_pdf.py --pages-only
(or the full build, which also remakes the PDF) and commit docs/index.html.

Run with: annotate_env\\Scripts\\python.exe test_docs.py
"""

import os
import shutil
import sys
import tempfile
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
sys.path.insert(0, DOCS)
import build_manual_pdf  # noqa: E402


def main():
    print("1. docs/index.html matches what docs/PEBBL_User_Manual.html generates...")
    with open(build_manual_pdf.INDEX, encoding="utf-8", newline="") as f:
        committed = f.read().replace("\r\n", "\n")
    assert build_manual_pdf.pages_index() == committed, \
        "docs/index.html is out of date: run docs/build_manual_pdf.py --pages-only and commit it"
    print("   OK")

    print("2. A changed source gives a different page (negative control)...")
    tmp = tempfile.mkdtemp()
    try:
        changed = os.path.join(tmp, "PEBBL_User_Manual.html")
        with open(build_manual_pdf.SOURCE, encoding="utf-8") as f:
            source = f.read()
        with open(changed, "w", encoding="utf-8") as f:
            f.write(source.replace('<div class="page">', '<div class="page"><p>An added line.</p>', 1))
        with patch.object(build_manual_pdf, "SOURCE", changed):
            assert build_manual_pdf.pages_index() != committed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("   OK")

    print("3. The page links the PDF and favicon, and Pages' files exist...")
    assert committed.startswith("<!doctype html>\n"), committed[:40]
    assert '<a href="PEBBL_User_Manual.pdf">Download it as a PDF</a>' in committed
    assert '<link rel="icon" type="image/png" href="img/pebbl_icon.png">' in committed
    for name in ("PEBBL_User_Manual.pdf", os.path.join("img", "pebbl_icon.png"), ".nojekyll"):
        assert os.path.exists(os.path.join(DOCS, name)), name
    print("   OK")

    print("4. The logo (HLU signed it off 2026-10-31) comes from its static files, lettering as outlines...")
    for name in ("pebbl_icon.svg", "pebbl_sticker.svg", "pebbl_sticker_print.svg", "pebbl_sticker_proof.svg"):
        with open(os.path.join(HERE, "branding", name), encoding="utf-8") as f:
            svg = f.read()
        assert "<text" not in svg and 'aria-label="pebbl"' in svg, name
    with open(build_manual_pdf.LOGO_SVG, "rb") as a, open(build_manual_pdf.MANUAL_LOGO, "rb") as b:
        assert a.read() == b.read(), "docs/img/pebbl_logo.svg isn't branding/pebbl_icon.svg: run docs/build_manual_pdf.py"
    assert '<img class="logo" src="img/pebbl_logo.svg"' in committed and "<script" not in committed, \
        "the manual's cover shows the static logo, not its own copy of the generator"
    print("   OK")

    print("\nALL DOCS TESTS PASSED.")


if __name__ == "__main__":
    main()
