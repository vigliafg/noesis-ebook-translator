"""Chapter / TOC model for EPUB books.

Shared headless logic (no Qt): maps the EPUB navigation document to a tree of
chapters, exposes the files each chapter covers, and resolves chapter
selections such as ``"1,3,5-7"`` or a list of hrefs. Used by the desktop GUI
(reader + chapter-scoped translation/export) and by the CLI edition.
"""
from __future__ import annotations

import os
import posixpath
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

from ebooklib import epub
from lxml import etree

XHTML = "{http://www.w3.org/1999/xhtml}"

__all__ = [
    "Chapter", "load_chapters", "flatten", "resolve_selection",
    "chapter_files", "book_meta", "isolate_chapters", "toc_anchors",
    "ChapterError",
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
    """Return the top-level chapters of an EPUB (multi-level tree).

    A few real books are re-packed "slim" and keep a **lying manifest**: the
    package document still lists files (fonts, scripts) that are no longer in the
    archive, and :mod:`ebooklib` refuses to read them. When that happens the
    table of contents is read straight from the archive instead -- the NCX, or the
    EPUB 3 navigation document.

    :class:`ChapterError` (with a readable message) is raised when neither route
    works, so the caller can *report* it instead of silently showing nothing.
    """
    try:
        return chapters_from_book(epub.read_epub(epub_path))
    except ChapterError:
        raise
    except Exception as exc:  # noqa: BLE001 - the archive may still be readable
        first = exc
    try:
        chapters = _chapters_from_zip(epub_path)
    except Exception as exc:  # noqa: BLE001 - report the *first* failure
        raise ChapterError(
            "impossibile leggere l'indice di "
            f"{os.path.basename(epub_path)}: {type(first).__name__}: {first}"
        ) from exc
    if not chapters:
        raise ChapterError(
            "l'indice di " + os.path.basename(epub_path) + " è vuoto"
            f" ({type(first).__name__}: {first})")
    return chapters


def chapters_from_book(book) -> list[Chapter]:
    chapters = _from_toc(book.toc)
    if not chapters:
        chapters = _fallback_chapters(book)
    for chapter in chapters:
        _annotate(chapter)
    return chapters


def _annotate(chapter: Chapter) -> None:
    # Fill ``files`` with the chapter's own file plus all descendants' files.
    files: list[str] = []
    seen = set()
    for node in chapter.walk():
        if node.file and node.file not in seen:
            seen.add(node.file)
            files.append(node.file)
    chapter.files = files
    for child in chapter.children:
        _annotate(child)


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


def toc_anchors(book) -> dict[str, set[str]]:
    """Public alias of the TOC anchor map (``{file: {anchor, ...}}``)."""
    return _toc_anchor_map(book)


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


# ---------------------------------------------------------------------------
#  Fallback reader: the table of contents straight from the archive
# ---------------------------------------------------------------------------
class ChapterError(RuntimeError):
    """The EPUB's table of contents cannot be read at all."""


def _local(tag) -> str:
    """Tag name without its namespace (``{ns}navPoint`` -> ``navPoint``)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _relativize(src: str, base_dir: str, opf_dir: str) -> str | None:
    """Resolve ``src`` against ``base_dir``, expressed relative to the OPF.

    ``Chapter.file`` must look like the names ebooklib exposes (relative to the
    package document) because the rest of the app compares them with the engine.
    """
    if not src:
        return None
    path, _, fragment = src.partition("#")
    if "://" in path:
        return src
    resolved = posixpath.normpath(posixpath.join(base_dir, path)) \
        if base_dir else path
    prefix = f"{opf_dir}/" if opf_dir else ""
    if prefix and resolved.startswith(prefix):
        resolved = resolved[len(prefix):]
    return resolved + (f"#{fragment}" if fragment else "")


def _opf_path(archive) -> str:
    try:
        container = ElementTree.fromstring(
            archive.read("META-INF/container.xml"))
        for element in container.iter():
            if _local(element.tag) == "rootfile" and element.get("full-path"):
                return element.get("full-path")
    except Exception:  # noqa: BLE001 - fall through to the scan
        pass
    for name in archive.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ChapterError("l'archivio non contiene il package document (OPF)")


def _toc_document(archive, opf_path: str) -> tuple[str | None, str]:
    """Return ``(zip_path, kind)`` of the NCX or of the navigation document."""
    names = set(archive.namelist())
    opf_dir = posixpath.dirname(opf_path)
    ncx = nav = None
    try:
        root = ElementTree.fromstring(archive.read(opf_path))
    except Exception:  # noqa: BLE001 - a broken OPF: fall back to the scan
        root = None
    if root is not None:
        for element in root.iter():
            if _local(element.tag) != "item":
                continue
            href = (element.get("href") or "").partition("#")[0]
            if not href:
                continue
            path = posixpath.normpath(posixpath.join(opf_dir, href))
            if path not in names:
                continue
            if element.get("media-type") == "application/x-dtbncx+xml":
                ncx = ncx or path
            if "nav" in (element.get("properties") or "").split():
                nav = nav or path
    if ncx is None:
        ncx = next((name for name in sorted(names)
                    if name.lower().endswith(".ncx")), None)
    if ncx:
        return ncx, "ncx"
    if nav:
        return nav, "nav"
    return None, ""


def _chapters_from_zip(epub_path: str) -> list[Chapter]:
    """Read the TOC from the archive, without ebooklib's manifest validation."""
    with zipfile.ZipFile(epub_path) as archive:
        opf_path = _opf_path(archive)
        opf_dir = posixpath.dirname(opf_path)
        path, kind = _toc_document(archive, opf_path)
        if path is None:
            raise ChapterError(
                "l'archivio non ha né un NCX né un documento di navigazione")
        data = archive.read(path)
        base_dir = posixpath.dirname(path)
        if kind == "ncx":
            chapters = _chapters_from_ncx(data, base_dir, opf_dir)
        else:
            chapters = _chapters_from_nav(data, base_dir, opf_dir)
    for chapter in chapters:
        _annotate(chapter)
    return chapters


def _chapters_from_ncx(data: bytes, base_dir: str,
                       opf_dir: str) -> list[Chapter]:
    root = ElementTree.fromstring(data)
    # The entries live inside <navMap>, not directly under <ncx>.
    nav_map = next((element for element in root.iter()
                    if _local(element.tag) == "navMap"), None)
    if nav_map is None:
        return []
    return _navpoints(nav_map, base_dir, opf_dir, 0)


def _navpoints(parent, base_dir: str, opf_dir: str, depth: int) -> list[Chapter]:
    chapters: list[Chapter] = []
    for element in parent:
        if _local(element.tag) != "navPoint":
            continue
        name = src = ""
        for child in element:
            tag = _local(child.tag)
            if tag == "navLabel":
                for text in child.iter():
                    if _local(text.tag) == "text":
                        name = (text.text or "").strip()
                        break
            elif tag == "content":
                src = child.get("src") or ""
        children = _navpoints(element, base_dir, opf_dir, depth + 1)
        href = _relativize(src, base_dir, opf_dir)
        # A heading carries the first child's target (that is how the NCX is
        # written for a section): it must stay a heading, otherwise the list would
        # show its first chapter twice.
        if (children and href and children[0].href
                and _file_of(href) == _file_of(children[0].href)):
            href = None
        chapter = Chapter(name=name, href=href, file=_file_of(href),
                          children=children, depth=depth)
        if not chapter.name and not chapter.file and not children:
            continue
        chapters.append(chapter)
    return chapters


def _chapters_from_nav(data: bytes, base_dir: str,
                       opf_dir: str) -> list[Chapter]:
    """EPUB 3 navigation document: the ``<nav epub:type="toc">`` list."""
    root = ElementTree.fromstring(data)
    toc = None
    for element in root.iter():
        if _local(element.tag) == "nav" and any(
                value == "toc" for value in element.attrib.values()):
            toc = element
            break
    if toc is None:
        toc = next((element for element in root.iter()
                    if _local(element.tag) == "nav"), None)
    if toc is None:
        return []
    ordered = next((element for element in toc.iter()
                    if _local(element.tag) == "ol"), None)
    return _nav_list(ordered, base_dir, opf_dir, 0) if ordered is not None else []


def _nav_list(ordered, base_dir: str, opf_dir: str,
              depth: int) -> list[Chapter]:
    chapters: list[Chapter] = []
    for item in ordered:
        if _local(item.tag) != "li":
            continue
        name = ""
        href = None
        children: list[Chapter] = []
        for child in item:
            tag = _local(child.tag)
            if tag in ("a", "span"):
                if not name:
                    name = "".join(child.itertext()).strip()
                if tag == "a" and href is None:
                    href = _relativize(child.get("href") or "", base_dir, opf_dir)
            elif tag == "ol":
                children = _nav_list(child, base_dir, opf_dir, depth + 1)
        chapter = Chapter(name=name, href=href, file=_file_of(href),
                          children=children, depth=depth)
        if not chapter.name and not chapter.file and not children:
            continue
        chapters.append(chapter)
    return chapters


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
