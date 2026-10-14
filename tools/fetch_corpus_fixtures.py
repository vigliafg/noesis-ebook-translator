#!/usr/bin/env python3
"""Fetch and catalogue the Project Gutenberg test corpus.

The corpus (``tests/data/corpus/``) is a set of **real, illustrated** public
domain books used by the end-to-end tests. This script:

* downloads any missing books (``.epub.images`` edition) from Project Gutenberg;
* rebuilds ``MANIFEST.json`` by inspecting each EPUB (title, author, images,
  TOC depth, size).

Usage::

    python tools/fetch_corpus_fixtures.py            # download missing + manifest
    python tools/fetch_corpus_fixtures.py --force    # re-download everything
    python tools/fetch_corpus_fixtures.py --manifest-only
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "data" / "corpus"

#: Project Gutenberg ebook id -> local filename. Treatises, manuals and science
#: books chosen for having **illustrations** and a **multi-level TOC**.
BOOKS: dict[int, str] = {
    1228: "origin_of_species.epub",
    944: "voyage_of_the_beagle.epub",
    2300: "descent_of_man.epub",
    24923: "variation_of_animals_and_plants.epub",
    25267: "astronomy_for_amateurs.epub",
    27378: "the_story_of_the_heavens.epub",
    30541: "treatise_on_anatomy_physiology_and_hygiene.epub",
    51213: "the_art_of_bookbinding.epub",
    21531: "woodwork_joints.epub",
    33757: "the_elements_of_botany.epub",
    695: "glaucus.epub",
    56133: "flowers_of_the_sky.epub",
    22298: "practical_mechanics_for_boys.epub",
}

URL = "https://www.gutenberg.org/ebooks/{id}.epub.images"
USER_AGENT = "noesis-ebook-translator/fixtures (+https://github.com/vigliafg)"


def fetch(ebook_id: int, target: Path) -> None:
    request = urllib.request.Request(
        URL.format(id=ebook_id), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    if not data.startswith(b"PK"):
        raise SystemExit(f"downloaded data for #{ebook_id} is not an EPUB zip")
    target.write_bytes(data)


def toc_depth(toc) -> int:
    depth = 0
    for item in toc or []:
        if isinstance(item, (tuple, list)):
            depth = max(depth, 1 + toc_depth(item[1] if len(item) > 1 else []))
        else:
            depth = max(depth, 1)
    return depth


def describe(path: Path, ebook_id: int) -> dict:
    from ebooklib import epub

    data = path.read_bytes()
    book = epub.read_epub(io.BytesIO(data))

    def meta(key):
        values = book.get_metadata("DC", key)
        return values[0][0] if values else ""

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        images = [n for n in names if n.lower().endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"))]
        img_tags = sum(
            archive.read(n).decode("utf-8", "replace").lower().count("<img")
            for n in names if n.lower().endswith((".xhtml", ".html", ".htm")))

    return {
        "id": ebook_id,
        "file": path.name,
        "title": meta("title"),
        "author": meta("creator"),
        "url": f"https://www.gutenberg.org/ebooks/{ebook_id}",
        "images": len(images),
        "img_tags": img_tags,
        "toc_depth": toc_depth(book.toc),
        "documents": len([i for i in book.get_items() if i.get_type() == 9]),
        "bytes": len(data),
    }


def build_manifest() -> list[dict]:
    entries = []
    for ebook_id, name in sorted(BOOKS.items()):
        path = CORPUS / name
        if not path.is_file():
            print(f"  WARNING: missing {name}", file=sys.stderr)
            continue
        entries.append(describe(path, ebook_id))
    (CORPUS / "MANIFEST.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the file already exists")
    ap.add_argument("--manifest-only", action="store_true",
                    help="only rebuild MANIFEST.json (no downloads)")
    args = ap.parse_args(argv)

    CORPUS.mkdir(parents=True, exist_ok=True)
    if not args.manifest_only:
        for ebook_id, name in BOOKS.items():
            target = CORPUS / name
            if target.exists() and not args.force:
                print(f"skip  {name}")
                continue
            print(f"fetch {name} <- gutenberg #{ebook_id} …", end=" ", flush=True)
            fetch(ebook_id, target)
            print(f"{target.stat().st_size} bytes")

    entries = build_manifest()
    total = sum(e["bytes"] for e in entries)
    print(f"\nmanifest: {len(entries)} books, {total / 1_048_576:.1f} MB total")
    for e in entries:
        print(f'  #{e["id"]:>6} depth={e["toc_depth"]} imgs={e["images"]:>3} '
              f'{e["bytes"] // 1024:>5}KB  {e["title"][:55]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
