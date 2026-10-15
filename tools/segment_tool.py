#!/usr/bin/env python3
"""Split or merge EPUB files (original or translated editions).

Examples::

    python tools/segment_tool.py split book.epub --out parts/
    python tools/segment_tool.py split book.epub --out parts/ --mode flat
    python tools/segment_tool.py merge parts/*.epub --out merged.epub
    python tools/segment_tool.py merge a.epub b.epub --out merged.epub --title "My book"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("split", help="split one EPUB into per-chapter EPUBs")
    sp.add_argument("book", help="input EPUB")
    sp.add_argument("--out", required=True, help="output directory")
    sp.add_argument("--mode", choices=["chapter", "flat"], default="chapter")

    mg = sub.add_parser("merge", help="merge EPUBs into one")
    mg.add_argument("books", nargs="+", help="input EPUBs (in order)")
    mg.add_argument("--out", required=True, help="output EPUB")
    mg.add_argument("--title", default=None, help="title of the merged book")

    args = ap.parse_args(argv)
    from noesis_ebook_translator import segment

    if args.command == "split":
        written = segment.split_epub(args.book, args.out, mode=args.mode)
        for path in written:
            print(path)
        print(f"\n{len(written)} EPUB(s) written to {args.out}", file=sys.stderr)
    else:
        out = segment.merge_epubs(args.books, args.out, title=args.title)
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
