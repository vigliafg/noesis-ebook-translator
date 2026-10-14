#!/usr/bin/env python3
"""Download the Darwin test corpus from Project Gutenberg.

The fixtures are used by ``tests/test_darwin_corpus.py``. They are committed to
the repository, so running this script is only needed to (re)download or refresh
them.

Usage::

    python tools/fetch_darwin_fixtures.py
    python tools/fetch_darwin_fixtures.py --force
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "tests" / "data" / "darwin"

#: local filename -> Project Gutenberg ebook id
BOOKS = {
    "origin_of_species.epub": 1228,
    "voyage_of_the_beagle.epub": 944,
    "descent_of_man.epub": 2300,
}

URL = "https://www.gutenberg.org/ebooks/{id}.epub.noimages"
USER_AGENT = "noesis-ebook-translator/fixtures (+https://github.com/vigliafg)"


def fetch(ebook_id: int, target: Path) -> None:
    request = urllib.request.Request(
        URL.format(id=ebook_id), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if not data.startswith(b"PK"):
        raise SystemExit(f"downloaded data for #{ebook_id} is not an EPUB zip")
    target.write_bytes(data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the file already exists")
    args = ap.parse_args(argv)

    DEST.mkdir(parents=True, exist_ok=True)
    for name, ebook_id in BOOKS.items():
        target = DEST / name
        if target.exists() and not args.force:
            print(f"skip  {name} (already present, {target.stat().st_size} bytes)")
            continue
        print(f"fetch {name} <- gutenberg #{ebook_id} …", end=" ", flush=True)
        fetch(ebook_id, target)
        print(f"{target.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
