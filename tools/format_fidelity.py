#!/usr/bin/env python3
"""Compare the *formatting* of an EPUB against its source (CSS fidelity).

The translation engine rewrites text nodes and may drop inline emphasis tags, so
"the output looks the same" needs a definition. This tool reports it in layers:

* **CSS assets** -- every ``.css`` of the source must exist byte-for-byte in the
  result (the file name may be re-rooted, the bytes may not change);
* **stylesheet links** -- every ``<link rel="stylesheet">`` of every shared
  document must still be in the result (a book can keep the CSS files and lose
  the link, which silently removes *all* styling);
* **styling attributes** -- ``class`` / ``id`` / ``style`` / ``role`` /
  ``epub:type`` on elements that carry them must survive (this is what the
  stylesheet selects). Lost block elements are fatal by default;
* **inline tags** -- ``em``/``i``/``b``/``cite``/... are intentionally not
  reserved by the engine (their text is translated, the tag goes). Reported, not
  fatal unless ``--strict``.

Examples::

    python tools/format_fidelity.py src.epub out.epub
    python tools/format_fidelity.py src.epub out.epub --strict --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter

from lxml import etree

XHTML = "{http://www.w3.org/1999/xhtml}"
#: Tag attributes that decide how the stylesheet paints the element.
STYLE_ATTRS = ("class", "id", "style", "role", "type")
#: Tags the engine deliberately rewrites away (text is translated, tag dropped).
INLINE = {"a", "em", "strong", "small", "s", "cite", "q", "time", "samp",
          "i", "b", "u", "mark", "span", "data", "del", "ins", "sub", "sup",
          "abbr", "code", "kbd", "var", "wbr"}
BLOCK = {"p", "div", "section", "table", "figure", "figcaption", "h1", "h2",
         "h3", "h4", "h5", "h6", "ul", "ol", "li", "td", "th", "tr", "caption",
         "thead", "tbody", "blockquote", "address", "footer", "hgroup"}
#: Structural elements with no styling of their own: losing one changes layout
#: (line/structure) but not a CSS selector. ``img`` is *not* here: a lost image
#: element is a real problem, and the asset check cannot see it.
NEUTRAL = {"br", "hr", "wbr", "col", "source", "track", "area", "base"}


def _entries(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _documents(entries: dict[str, bytes]) -> dict[str, bytes]:
    """Map navigation-free HTML documents by *base name*.

    The package root can be renamed by a round-trip (``OEBPS/`` -> ``EPUB/``), so
    matching full paths would compare nothing. Navigation documents are skipped:
    their content is regenerated from the (filtered) TOC on purpose.
    """
    docs: dict[str, bytes] = {}
    skip = ("nav.xhtml", "toc.xhtml", "cover.xhtml")
    for name, data in entries.items():
        base = name.rsplit("/", 1)[-1]
        if not base.lower().endswith((".xhtml", ".html", ".htm")):
            continue
        if base.lower() in skip:
            continue
        docs[base] = data
    return docs


def _root(data: bytes):
    return etree.fromstring(data, etree.XMLParser(recover=True,
                                                  resolve_entities=False))


def _localname(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and "}" in tag else tag


def _style_signature(root) -> Counter:
    """Multiset of ``(tag, styling attributes)`` over the document."""
    counter: Counter = Counter()
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = _localname(element.tag)
        attrs = tuple(sorted(
            (key.split("}")[-1], value) for key, value in element.attrib.items()
            if key.split("}")[-1] in STYLE_ATTRS))
        counter[(name, attrs)] += 1
    return counter


def _stylesheet_links(root) -> Counter:
    links: Counter = Counter()
    for element in root.iter():
        if _localname(element.tag) == "link" and \
                "stylesheet" in (element.get("rel") or ""):
            links[(element.get("href") or "",
                   element.get("media") or "")] += 1
    return links


def _css_hashes(entries: dict[str, bytes]) -> Counter:
    return Counter(hashlib.sha256(data).hexdigest()
                   for name, data in entries.items()
                   if name.lower().endswith(".css"))


#: Assets whose bytes are part of the look of the book (fonts, images, media).
_ASSET_SUFFIXES = (".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                   ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4",
                   ".m4a", ".js")


def _asset_hashes(entries: dict[str, bytes]) -> Counter:
    return Counter(hashlib.sha256(data).hexdigest()
                   for name, data in entries.items()
                   if name.lower().endswith(_ASSET_SUFFIXES))


def compare(source: str, result: str, strict: bool = False) -> dict:
    src, dst = _entries(source), _entries(result)
    report: dict = {"source": source, "result": result, "problems": [],
                    "notes": []}

    css_src, css_dst = _css_hashes(src), _css_hashes(dst)
    report["css_files"] = {"source": sum(css_src.values()),
                           "result": sum(css_dst.values())}
    if css_src != css_dst:
        report["problems"].append(
            "CSS assets differ or are missing (source "
            f"{sum(css_src.values())}, result {sum(css_dst.values())})")

    assets_src, assets_dst = _asset_hashes(src), _asset_hashes(dst)
    missing_assets = assets_src - assets_dst
    report["assets"] = {"source": sum(assets_src.values()),
                        "missing": sum(missing_assets.values())}
    if missing_assets:
        report["problems"].append(
            f"{sum(missing_assets.values())} asset(s) (fonts/images/media) "
            "differ or are missing")

    docs_src, docs_dst = _documents(src), _documents(dst)
    shared = sorted(set(docs_src) & set(docs_dst))
    report["documents"] = {"source": len(docs_src), "result": len(docs_dst),
                           "compared": len(shared)}
    if not shared:
        report["problems"].append("no shared HTML documents to compare")

    lost_links: list[str] = []
    missing_blocks = Counter()
    missing_inline = Counter()
    missing_neutral = Counter()
    for name in shared:
        a, b = _root(docs_src[name]), _root(docs_dst[name])
        links = _stylesheet_links(a) - _stylesheet_links(b)
        if links:
            lost_links.append(f"{name}: {dict(links)}")
        missing = _style_signature(a) - _style_signature(b)
        for (tag, attrs), count in missing.items():
            carry = any(attr for attr, _ in attrs)
            if tag in NEUTRAL and not carry:
                missing_neutral[(tag, attrs)] += count
            elif tag in INLINE:
                missing_inline[(tag, attrs)] += count
            elif carry or tag in BLOCK or tag == "img":
                missing_blocks[(tag, attrs)] += count
            else:
                missing_neutral[(tag, attrs)] += count
        extra = _style_signature(b) - _style_signature(a)
        if extra:
            report["notes"].append(
                f"{name}: {sum(extra.values())} element(s) gained styling "
                "attributes (engine adds dir/lang)")
    if lost_links:
        report["problems"].append("stylesheet links lost: " + "; ".join(lost_links))
    lost_block_elements = sum(missing_blocks.values())
    lost_inline_elements = sum(missing_inline.values())
    lost_neutral_elements = sum(missing_neutral.values())
    report["elements"] = {"lost_block": lost_block_elements,
                          "lost_inline": lost_inline_elements,
                          "lost_neutral": lost_neutral_elements,
                          "detail_block": {f"{t} {dict(a)}": n
                                           for (t, a), n in missing_blocks.items()},
                          "detail_inline": {f"{t} {dict(a)}": n
                                            for (t, a), n in missing_inline.items()},
                          "detail_neutral": {f"{t} {dict(a)}": n
                                             for (t, a), n in
                                             missing_neutral.items()}}
    if lost_block_elements:
        report["problems"].append(
            f"{lost_block_elements} styled block element(s) lost")
    if lost_inline_elements:
        message = (f"{lost_inline_elements} inline element(s) collapsed to text "
                   "(the engine translates their text and drops the tag)")
        (report["problems"] if strict else report["notes"]).append(message)
    if lost_neutral_elements:
        report["notes"].append(
            f"{lost_neutral_elements} structural element(s) lost (line breaks / "
            "rules); layout may reflow slightly")

    report["ok"] = not report["problems"]
    return report


def _print(report: dict) -> None:
    print(f"source: {report['source']}")
    print(f"result: {report['result']}")
    css = report["css_files"]
    print(f"CSS files            : {css['result']}/{css['source']} present")
    assets = report["assets"]
    print(f"assets (fonts/images): {assets['missing']} missing of "
          f"{assets['source']}")
    docs = report["documents"]
    print(f"HTML documents       : {docs['compared']} compared "
          f"(source {docs['source']}, result {docs['result']})")
    elements = report["elements"]
    print(f"styled block elements: {elements['lost_block']} lost")
    print(f"inline elements      : {elements['lost_inline']} collapsed")
    print(f"structural elements  : {elements.get('lost_neutral', 0)} lost "
          "(br/hr: line breaks)")
    for note in report["notes"]:
        print(f"  note : {note}")
    for problem in report["problems"]:
        print(f"  FAIL : {problem}")
    print("OK" if report["ok"] else "FAILED")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="source EPUB")
    ap.add_argument("result", help="extracted/translated EPUB")
    ap.add_argument("--strict", action="store_true",
                    help="fail on collapsed inline tags too")
    ap.add_argument("--json", action="store_true", help="print the raw report")
    ap.add_argument("--detail", action="store_true",
                    help="list every lost element signature")
    args = ap.parse_args(argv)

    report = compare(args.source, args.result, strict=args.strict)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print(report)
        if args.detail:
            print("lost blocks:", json.dumps(report["elements"]["detail_block"],
                                             ensure_ascii=False))
            print("lost inline:", json.dumps(report["elements"]["detail_inline"],
                                             ensure_ascii=False))
            print("lost neutral:", json.dumps(
                report["elements"].get("detail_neutral", {}),
                ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
