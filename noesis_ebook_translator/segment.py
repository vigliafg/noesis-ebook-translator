"""Split and merge EPUB files (headless, Qt-free).

Split a book into one EPUB per chapter; merge several EPUBs back into a single
book. Works on both the *original* and the *translated* edition (the operations
are path-based). Chapter structure, assets and the TOC are preserved.

The merge is deliberately conservative: every input keeps its own sub-directory
inside the merged EPUB (``part1/``, ``part2/``, …) so that identical file names
(``nav.xhtml``, ``style.css``, images…) never collide. The merged navigation gets
a top-level section per part.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from ebooklib import epub

from .chapters import Chapter, chapter_files, flatten, isolate_chapters, load_chapters
from .exporter import restrict_book, _ensure_toc_uids

__all__ = ["split_epub", "merge_epubs", "sanitize_name", "part_filename"]


def _is_nav_or_ncx(item) -> bool:
    if isinstance(item, (epub.EpubNav, epub.EpubNcx)):
        return True
    name = getattr(item, "file_name", "") or ""
    return name.lower().endswith(".ncx")


_SAFE_RE = re.compile(r"[^0-9A-Za-zÀ-ÿ._-]+")


def sanitize_name(name: str, fallback: str = "section") -> str:
    name = (name or "").strip()
    name = _SAFE_RE.sub("_", name).strip("._")
    return name[:60] or fallback


def part_filename(index: int, name: str) -> str:
    return f"{index:02d}_{sanitize_name(name)}.epub"


# ---------------------------------------------------------------------------
#  Split
# ---------------------------------------------------------------------------
def split_epub(input_path: str, out_dir: str,
               chapters: list[Chapter] | None = None,
               mode: str = "chapter") -> list[str]:
    """Split ``input_path`` into one EPUB per chapter under ``out_dir``.

    ``mode='chapter'`` uses the top-level chapters; ``mode='flat'`` uses every
    flattened chapter (leaves included). Returns the written file paths.
    """
    chapters = chapters if chapters is not None else load_chapters(input_path)
    if not chapters:
        raise ValueError("no chapters found to split")
    if mode == "flat":
        targets = [c for c in flatten(chapters) if c.file]
    else:
        targets = chapters

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for chapter in targets:
        files = chapter_files([chapter])
        if not files:
            continue
        book = epub.read_epub(input_path)
        restrict_book(book, files)
        isolate_chapters(book, [chapter])
        _ensure_toc_uids(book.toc)
        target = os.path.join(out_dir, part_filename(len(written) + 1, chapter.name))
        epub.write_epub(target, book)
        written.append(target)
    return written


# ---------------------------------------------------------------------------
#  Merge
# ---------------------------------------------------------------------------
def _remap_href(prefix: str, href):
    if not href:
        return href
    if href.startswith(("http://", "https://", "mailto:", "#")):
        return href
    return prefix + href


def _remap_toc(nodes, prefix: str):
    out = []
    for item in nodes or []:
        if isinstance(item, (list, tuple)) and item:
            head = _remap_toc([item[0]], prefix)[0]
            kids = _remap_toc(item[1] if len(item) > 1 else [], prefix)
            out.append((head, kids))
        elif isinstance(item, epub.Link):
            out.append(epub.Link(_remap_href(prefix, item.href), item.title,
                                 item.uid or f"uid-{sanitize_name(item.title)}"))
        elif isinstance(item, epub.Section):
            out.append(epub.Section(item.title,
                                    _remap_href(prefix, item.href or "") or None))
        else:
            out.append(item)
    return out


def _copy_document(item, prefix: str, part: int):
    new = epub.EpubHtml(
        title=getattr(item, "title", "") or item.file_name,
        file_name=prefix + item.file_name,
        lang=getattr(item, "lang", "") or "")
    new.id = f"p{part}-{item.id or item.file_name}"
    new.set_content(item.get_content())
    return new


def _copy_asset(item, prefix: str, part: int):
    new = epub.EpubItem(
        uid=f"p{part}-{item.id or item.file_name}",
        file_name=prefix + item.file_name,
        media_type=getattr(item, "media_type", "") or "application/octet-stream",
        content=item.get_content())
    return new


def merge_epubs(paths: list[str], output_path: str,
                title: str | None = None) -> str:
    """Merge ``paths`` (in order) into a single EPUB at ``output_path``."""
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        raise ValueError("no input EPUBs to merge")

    merged = epub.EpubBook()
    first = epub.read_epub(paths[0])

    def _meta(key, default=""):
        values = first.get_metadata("DC", key)
        return values[0][0] if values else default

    merged.set_identifier("noesis-merge-" + hashlib.md5(
        "\n".join(os.path.abspath(p) for p in paths).encode("utf-8")).hexdigest()[:12])
    merged.set_title(title or _meta("title", "Merged book"))
    merged.set_language(_meta("language", "en"))
    author = _meta("creator")
    if author:
        merged.add_author(author)

    spine: list = []
    toc: list = []
    for part, path in enumerate(paths, 1):
        book = epub.read_epub(path)
        prefix = f"part{part}/"
        for item in book.get_items():
            if _is_nav_or_ncx(item):
                continue
            item_type = item.get_type()
            if item_type == 9:
                new = _copy_document(item, prefix, part)
                merged.add_item(new)
                spine.append(new)
            else:
                merged.add_item(_copy_asset(item, prefix, part))

        part_title = _meta_title_of(book, path)
        nodes = _remap_toc(book.toc, prefix)
        if nodes:
            toc.append((epub.Section(part_title), nodes))
        else:
            toc.append(epub.Section(part_title))

    merged.add_item(epub.EpubNcx())
    merged.add_item(epub.EpubNav())
    merged.toc = tuple(toc)
    merged.spine = ["nav"] + spine
    _ensure_toc_uids(merged.toc)
    epub.write_epub(output_path, merged)
    return output_path


def _meta_title_of(book, path: str) -> str:
    values = book.get_metadata("DC", "title")
    if values and values[0][0]:
        return values[0][0]
    return Path(path).stem
