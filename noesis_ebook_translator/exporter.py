"""Headless export of EPUB content (chapters, figures, tables, text).

Shared logic (no Qt) used by the desktop GUI and the CLI edition. A *selection*
of chapters can be exported as a standalone EPUB or converted to HTML/Markdown/
plain text; figures and tables can be exported as images/HTML/Markdown and
CSV/HTML/Markdown respectively.
"""
from __future__ import annotations

import base64
import csv
import os
import re
from pathlib import Path

from ebooklib import epub
from lxml import etree

from .chapters import Chapter, chapter_files
from .extract import Figure, Table, extract_figures, extract_tables

__all__ = [
    "restrict_book", "export_epub", "export_html", "export_markdown",
    "export_text", "export_figures", "export_tables", "export_chapters",
]

XHTML = "{http://www.w3.org/1999/xhtml}"
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = {"p", "blockquote", "li", "pre"}


def _localname(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else tag


def _file_of(href):
    return href.split("#", 1)[0] if href else None


# --------------------------------------------------------------------------
#  Restricting an ebooklib book to a subset of documents
# --------------------------------------------------------------------------
def restrict_book(book, files: set[str]) -> None:
    """Edit ``book`` in place, keeping only documents in ``files``."""
    book.items = [item for item in book.items
                  if item.get_type() != 9 or item.file_name in files]

    kept_ids = {item.id for item in book.items}
    spine = []
    for entry in book.spine or []:
        key = entry[0] if isinstance(entry, (tuple, list)) else entry
        if not isinstance(key, str):
            key = getattr(key, "id", None)
        item = book.get_item_with_id(key) if key else None
        if item is None:
            continue  # removed document
        if item.get_type() == 9 or item.id in kept_ids:
            spine.append(entry)
    book.spine = spine

    def keep(href):
        return _file_of(getattr(href, "href", None)) in files

    def filter_toc(nodes):
        out = []
        for item in nodes or []:
            if isinstance(item, (tuple, list)) and item:
                head = item[0]
                kids = filter_toc(item[1] if len(item) > 1 else [])
                if kids:
                    out.append((head, kids))
                elif keep(head):
                    out.append(head)
            elif keep(item):
                out.append(item)
        return out

    book.toc = filter_toc(list(book.toc or []))


def _read(path: str):
    return epub.read_epub(path)


def _ensure_toc_uids(toc) -> None:
    for entry in toc or []:
        if isinstance(entry, (tuple, list)):
            if entry:
                _ensure_toc_uids([entry[0]])
            if len(entry) > 1:
                _ensure_toc_uids(entry[1])
            continue
        if hasattr(entry, "uid") and not entry.uid:
            href = getattr(entry, "href", "") or ""
            entry.uid = "toc-" + re.sub(r"[^0-9a-zA-Z]+", "", href)[:40]


def export_epub(input_path: str, output_path: str,
                selected: list[Chapter] | None = None) -> list[str]:
    book = _read(input_path)
    if selected:
        restrict_book(book, chapter_files(selected))
    _ensure_toc_uids(book.toc)
    epub.write_epub(output_path, book)
    return [output_path]


# --------------------------------------------------------------------------
#  HTML / Markdown / text
# --------------------------------------------------------------------------
def _documents(book, files: set[str] | None):
    docs = []
    for entry in book.spine or []:
        item = entry[0] if isinstance(entry, (tuple, list)) else entry
        if isinstance(item, str):
            item = book.get_item_with_id(item)
        if item is None or item.get_type() != 9:
            continue
        if files and item.file_name not in files:
            continue
        docs.append(item)
    if not docs:
        docs = [i for i in book.get_items() if i.get_type() == 9
                and (not files or i.file_name in files)]
    return docs


def _data_uri(book, doc_name, src):
    import posixpath
    target = posixpath.normpath(posixpath.join(posixpath.dirname(doc_name), src))
    for item in book.get_items():
        if item.file_name in (target, src) and getattr(item, "media_type", "").startswith("image/"):
            b64 = base64.b64encode(item.get_content()).decode("ascii")
            return f"data:{item.media_type};base64,{b64}"
    return src


def export_html(input_path: str, output_path: str,
                selected: list[Chapter] | None = None,
                title: str | None = None) -> list[str]:
    book = _read(input_path)
    files = chapter_files(selected) if selected else None
    parts = ["<!DOCTYPE html>", '<html><head><meta charset="utf-8">',
             f"<title>{title or os.path.basename(input_path)}</title>",
             "<style>body{font-family:serif;line-height:1.5;margin:2rem;} "
             "img{max-width:100%;}</style></head><body>"]
    for doc in _documents(book, files):
        root = etree.fromstring(doc.get_content(),
                                parser=etree.XMLParser(recover=True))
        for img in root.iter():
            if _localname(img.tag) == "img" and img.get("src"):
                img.set("src", _data_uri(book, doc.file_name, img.get("src")))
        body = root.find(f".//{XHTML}body")
        if body is None:
            body = root.find(".//body")
        parts.append(f'<section data-src="{doc.file_name}">')
        if body is not None:
            parts.extend(etree.tostring(c, encoding="unicode") for c in body)
        parts.append("</section>")
    parts.append("</body></html>")
    Path(output_path).write_text("\n".join(parts), encoding="utf-8")
    return [output_path]


def export_markdown(input_path: str, output_path: str,
                    selected: list[Chapter] | None = None) -> list[str]:
    book = _read(input_path)
    files = chapter_files(selected) if selected else None
    assets = Path(output_path).with_suffix("")
    assets = assets.parent / (assets.name + "_files")
    written: list[str] = []
    lines: list[str] = []
    for doc in _documents(book, files):
        root = etree.fromstring(doc.get_content(),
                                parser=etree.XMLParser(recover=True))
        body = root.find(f".//{XHTML}body")
        if body is None:
            body = root.find(".//body")
        for el in (body if body is not None else root):
            name = _localname(el.tag)
            if name in HEADINGS:
                lines.append("#" * int(name[1]) + " " +
                             " ".join("".join(el.itertext()).split()))
                lines.append("")
            elif name in BLOCKS:
                text = " ".join("".join(el.itertext()).split())
                if text:
                    lines.append(text)
                    lines.append("")
            elif name == "img" and el.get("src"):
                src = _data_uri_bytes(book, doc.file_name, el.get("src"))
                if src:
                    data, fname = src
                    assets.mkdir(parents=True, exist_ok=True)
                    target = assets / fname
                    target.write_bytes(data)
                    written.append(str(target))
                    lines.append(f"![{el.get('alt', fname)}]({assets.name}/{fname})")
                    lines.append("")
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [output_path] + written


def _data_uri_bytes(book, doc_name, src):
    import posixpath
    target = posixpath.normpath(posixpath.join(posixpath.dirname(doc_name), src))
    for item in book.get_items():
        if item.file_name in (target, src) and getattr(item, "media_type", "").startswith("image/"):
            return item.get_content(), os.path.basename(item.file_name)
    return None


def export_text(input_path: str, output_path: str,
                selected: list[Chapter] | None = None) -> list[str]:
    from .extract import extract_text
    blocks = extract_text(input_path, selected=selected)
    Path(output_path).write_text(
        "\n\n".join(text for _, _, text in blocks) + "\n", encoding="utf-8")
    return [output_path]


# --------------------------------------------------------------------------
#  Figures and tables
# --------------------------------------------------------------------------
def _ext(mime: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
            "image/svg+xml": ".svg", "image/webp": ".webp"}.get(mime, ".img")


def export_figures(figures: list[Figure], out_dir: str, fmt: str = "img") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if fmt in ("img", "files"):
        for fig in figures:
            name = f"figure-{fig.number:03d}{_ext(fig.mime)}"
            target = out / name
            target.write_bytes(fig.data)
            written.append(str(target))
        return written
    if fmt == "html":
        lines = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
                 "<title>Figures</title></head><body>"]
        for fig in figures:
            b64 = base64.b64encode(fig.data).decode("ascii")
            cap = fig.caption or ""
            lines.append(
                f"<figure id='fig{fig.number}'><img src='data:{fig.mime};base64,{b64}'>"
                f"<figcaption>Fig. {fig.number}. {cap}</figcaption></figure>")
        lines.append("</body></html>")
        target = out / "figures.html"
        target.write_text("\n".join(lines), encoding="utf-8")
        return [str(target)]
    if fmt == "md":
        lines = []
        for fig in figures:
            name = f"figure-{fig.number:03d}{_ext(fig.mime)}"
            (out / name).write_bytes(fig.data)
            lines.append(f"![Fig. {fig.number}. {fig.caption or ''}]({name})")
            lines.append("")
        target = out / "figures.md"
        target.write_text("\n".join(lines), encoding="utf-8")
        return [str(target)]
    raise ValueError(f"unknown figures format: {fmt}")


def export_tables(tables: list[Table], out_dir: str, fmt: str = "csv") -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    if fmt == "csv":
        for table in tables:
            target = out / f"table-{table.number:03d}.csv"
            with open(target, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerows(table.rows)
            written.append(str(target))
        return written
    if fmt == "html":
        lines = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
                 "<title>Tables</title></head><body>"]
        for table in tables:
            lines.append(f"<h3>Table {table.number}"
                         + (f": {table.caption}" if table.caption else "") + "</h3><table border='1'>")
            for row in table.rows:
                lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
            lines.append("</table>")
        lines.append("</body></html>")
        target = out / "tables.html"
        target.write_text("\n".join(lines), encoding="utf-8")
        return [str(target)]
    if fmt == "md":
        lines = []
        for table in tables:
            lines.append(f"### Table {table.number}"
                         + (f": {table.caption}" if table.caption else ""))
            if table.rows:
                lines.append("| " + " | ".join(table.rows[0]) + " |")
                lines.append("| " + " | ".join("---" for _ in table.rows[0]) + " |")
                for row in table.rows[1:]:
                    lines.append("| " + " | ".join(row) + " |")
            lines.append("")
        target = out / "tables.md"
        target.write_text("\n".join(lines), encoding="utf-8")
        return [str(target)]
    raise ValueError(f"unknown tables format: {fmt}")


def export_chapters(input_path: str, out, selected: list[Chapter] | None = None,
                    fmt: str = "epub") -> list[str]:
    """Export selected chapters as a standalone artifact of the given format."""
    fmt = (fmt or "epub").lower()
    out = str(out)
    if fmt == "epub":
        return export_epub(input_path, out, selected)
    if fmt == "html":
        return export_html(input_path, out, selected)
    if fmt in ("md", "markdown"):
        return export_markdown(input_path, out, selected)
    if fmt in ("txt", "text"):
        return export_text(input_path, out, selected)
    raise ValueError(f"unknown chapter format: {fmt}")
