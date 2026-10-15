"""Chapter / TOC model for EPUB books.

Shared headless logic (no Qt): maps the EPUB navigation document to a tree of
chapters, exposes the files each chapter covers, and resolves chapter
selections such as ``"1,3,5-7"`` or a list of hrefs. Used by the desktop GUI
(reader + chapter-scoped translation/export) and by the CLI edition.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ebooklib import epub
from lxml import etree

XHTML = "{http://www.w3.org/1999/xhtml}"

__all__ = [
    "Chapter", "load_chapters", "flatten", "resolve_selection",
    "chapter_files", "book_meta", "isolate_chapters",
]


def _fragment_of(href: str | None) -> str | None:
    if href and "#" in href:
        return href.split("#", 1)[1] or None
    return None


@dataclass
class Chapter:
    name: str
    href: str | None = None
    file: str | None = None
    files: list[str] = field(default_factory=list)
    children: list["Chapter"] = field(default_factory=list)
    depth: int = 0
    index: int = 0  # 1-based, filled by flatten()

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def _file_of(href: str | None) -> str | None:
    if not href:
        return None
    return href.split("#", 1)[0]


def _from_toc(items, depth: int = 0) -> list[Chapter]:
    chapters: list[Chapter] = []
    for item in items or []:
        children: list[Chapter] = []
        node = item
        if isinstance(item, (tuple, list)) and item:
            node = item[0]
            if len(item) > 1:
                children = _from_toc(item[1], depth + 1)
        href = getattr(node, "href", None) or None
        name = getattr(node, "title", None) or getattr(node, "name", None) or ""
        chapter = Chapter(
            name=name.strip(), href=href, file=_file_of(href),
            children=children, depth=depth)
        if not chapter.name and not chapter.file and not children:
            continue
        chapters.append(chapter)
    return chapters


def _spine_documents(book) -> list:
    docs = []
    for entry in book.spine or []:
        item = entry
        if isinstance(entry, (tuple, list)):
            item = entry[0]
        if isinstance(item, str):
            item = book.get_item_with_id(item)
        if item is not None and getattr(item, "get_type", lambda: None)() == 9:
            docs.append(item)
    if not docs:  # fallback: any document, in manifest order
        docs = [i for i in book.get_items() if i.get_type() == 9]
    return docs


def _title_of(item) -> str:
    try:
        root = etree.fromstring(
            item.get_content(),
            parser=etree.XMLParser(recover=True, resolve_entities=False))
    except Exception:  # noqa: BLE001
        return item.file_name
    for tag in ("h1", "h2", "h3", "title"):
        found = root.find(f".//{{http://www.w3.org/1999/xhtml}}{tag}")
        if found is None:
            found = root.find(f".//{tag}")
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return item.file_name


def _fallback_chapters(book) -> list[Chapter]:
    return [Chapter(name=_title_of(item), href=item.file_name,
                    file=item.file_name, depth=0)
            for item in _spine_documents(book)]


def load_chapters(epub_path: str) -> list[Chapter]:
    """Return the top-level chapters of an EPUB (multi-level tree)."""
    return chapters_from_book(epub.read_epub(epub_path))


def chapters_from_book(book) -> list[Chapter]:
    chapters = _from_toc(book.toc)
    if not chapters:
        chapters = _fallback_chapters(book)
    for chapter in chapters:
        _annotate(chapter, book)
    return chapters


def _annotate(chapter: Chapter, book) -> None:
    # Fill ``files`` with the chapter's own file plus all descendants' files.
    files: list[str] = []
    seen = set()
    for node in chapter.walk():
        if node.file and node.file not in seen:
            seen.add(node.file)
            files.append(node.file)
    chapter.files = files
    for child in chapter.children:
        _annotate(child, book)


def flatten(chapters: list[Chapter]) -> list[Chapter]:
    """Depth-first list; assigns a stable 1-based ``index``."""
    result: list[Chapter] = []
    for chapter in chapters:
        for node in chapter.walk():
            node.index = len(result) + 1
            result.append(node)
    return result


def chapter_files(chapters: list[Chapter]) -> set[str]:
    files: set[str] = set()
    for chapter in chapters:
        files.update(chapter.files)
    return files


def resolve_selection(chapters: list[Chapter], spec) -> list[Chapter]:
    """Resolve a selection into chapters.

    ``spec`` may be ``None``/empty (→ all top-level chapters), a string like
    ``"1,3,5-7"`` (1-based indices over :func:`flatten`), or a list of hrefs /
    file names / indices.
    """
    flat = flatten(chapters)
    if not spec:
        return chapters
    if isinstance(spec, str):
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        selected: list[Chapter] = []
        for part in parts:
            if "-" in part and part.replace("-", "").isdigit():
                start, end = part.split("-", 1)
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= len(flat):
                        selected.append(flat[i - 1])
            elif part.isdigit() and 1 <= int(part) <= len(flat):
                selected.append(flat[int(part) - 1])
            else:
                selected.extend(
                    c for c in flat if c.href == part or c.file == part)
        return selected
    # list of hrefs/files/indices
    wanted = {str(x) for x in spec}
    return [c for c in flat
            if c.href in wanted or c.file in wanted or str(c.index) in wanted]


# ---------------------------------------------------------------------------
#  Anchor-aware isolation (chapters that share one XHTML file)
# ---------------------------------------------------------------------------
def _iter_chapters(chapters):
    for chapter in chapters or []:
        yield from chapter.walk()


def _toc_anchor_map(book) -> dict[str, set[str]]:
    """Return ``{file_name: {anchor, ...}}`` from the (current) TOC."""
    anchors: dict[str, set[str]] = {}

    def walk(items):
        for item in items or []:
            if isinstance(item, (tuple, list)) and item:
                walk([item[0]])
                if len(item) > 1:
                    walk(item[1])
                continue
            href = getattr(item, "href", None)
            file_name = _file_of(href)
            fragment = _fragment_of(href)
            if file_name and fragment:
                anchors.setdefault(file_name, set()).add(fragment)

    walk(book.toc)
    return anchors


def isolate_chapters(book, selected) -> None:
    """Trim kept documents to the selected chapters' anchor ranges.

    When several TOC entries are anchors inside the *same* XHTML file (e.g.
    ``part.xhtml#ch2``), restricting by file keeps the whole file (previous and
    next chapters included). This keeps only the ``[anchor, next_anchor)`` ranges
    of the selected chapters. Chapters without an anchor keep the whole file.
    """
    anchors = _toc_anchor_map(book)
    wanted: dict[str, set[str] | None] = {}
    for chapter in _iter_chapters(selected):
        if not chapter.file:
            continue
        fragment = _fragment_of(chapter.href)
        if fragment is None:
            wanted[chapter.file] = None  # whole file requested
        elif wanted.get(chapter.file, set()) is not None:
            wanted.setdefault(chapter.file, set()).add(fragment)

    for item in book.get_items():
        if item.get_type() != 9 or item.file_name not in wanted:
            continue
        anchor_set = wanted[item.file_name]
        if anchor_set is None:
            continue
        _trim_item_to_anchors(item, anchor_set, anchors.get(item.file_name, set()))


def _trim_item_to_anchors(item, wanted: set[str], all_anchors: set[str]) -> None:
    if not wanted or not all_anchors:
        return
    try:
        root = etree.fromstring(
            item.get_content(),
            parser=etree.XMLParser(recover=True, resolve_entities=False))
    except Exception:  # noqa: BLE001 - malformed item, leave as-is
        return
    body = root.find(f".//{XHTML}body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        return

    order = {el: index for index, el in enumerate(root.iter())}
    anchor_pos: dict[str, int] = {}
    for el in root.iter():
        element_id = el.get("id")
        if element_id and element_id in all_anchors and element_id not in anchor_pos:
            anchor_pos[element_id] = order.get(el, 0)
    if not anchor_pos:
        return
    ordered = sorted(anchor_pos.items(), key=lambda pair: pair[1])

    def segment_of(element) -> str | None:
        position = order.get(element, 0)
        current = None
        for anchor, anchor_position in ordered:
            if anchor_position <= position:
                current = anchor
            else:
                break
        return current

    removed = False
    for child in list(body):
        segment = segment_of(child)
        if segment is None or segment not in wanted:
            body.remove(child)
            removed = True
    if removed:
        item.set_content(etree.tostring(
            root, encoding="utf-8", method="xml", xml_declaration=True))


def book_meta(epub_path: str) -> dict:
    """Return basic metadata (title, author, language, identifier, cover)."""
    book = epub.read_epub(epub_path)

    def first(key):
        values = book.get_metadata("DC", key)
        return values[0][0] if values else ""

    cover = None
    for item in book.get_items():
        name = item.file_name.lower()
        if item.get_type() == 1 and any(
                n in name for n in ("cover", "cover-image")) or \
                getattr(item, "id", "") in ("cover", "cover-image"):
            cover = item.get_content()
            break
    return {
        "title": first("title"),
        "author": first("creator"),
        "language": first("language"),
        "identifier": first("identifier"),
        "cover": cover,
    }
