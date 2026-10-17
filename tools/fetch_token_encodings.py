#!/usr/bin/env python3
"""Download the BPE files that :mod:`tiktoken` needs, ready to be bundled.

``tiktoken.get_encoding("o200k_base")`` normally downloads the encoding file on
first use and caches it in the system temp directory. The app must count tokens
**offline** and must not depend on ``/tmp`` (an update or a reboot can wipe it),
so the files ship inside the package:

    noesis_ebook_translator/data/tiktoken/<sha1-of-url>

``tiktoken`` names its cache entries with the SHA-1 of the download URL, so the
file names here are fixed (they are not arbitrary). :mod:`token_count` points
``TIKTOKEN_CACHE_DIR`` at this directory.

Usage::

    python tools/fetch_token_encodings.py           # download what is missing
    python tools/fetch_token_encodings.py --check   # only verify the bundle

Not needed at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "noesis_ebook_translator" / "data" / "tiktoken"

URL = "https://openaipublic.blob.core.windows.net/encodings/{name}.tiktoken"

#: Encodings the estimator can ask for. ``o200k_base`` covers GPT-4o/4.1/5.x and
#: is the best approximation for modern non-OpenAI models; ``cl100k_base``
#: covers GPT-4 (classic), GPT-3.5 and the older embedding models.
ENCODINGS = ("o200k_base", "cl100k_base")


def cache_name(url: str) -> str:
    """The file name ``tiktoken`` expects in ``TIKTOKEN_CACHE_DIR``."""
    return hashlib.sha1(url.encode()).hexdigest()


def fetch(name: str) -> Path:
    url = URL.format(name=name)
    destination = OUTPUT / cache_name(url)
    print(f"fetching {url} -> {destination.relative_to(ROOT)}")
    request = urllib.request.Request(url, headers={"User-Agent": "NoesisEbookTranslator"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty download for {name}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def check() -> int:
    missing = []
    for name in ENCODINGS:
        path = OUTPUT / cache_name(URL.format(name=name))
        if path.is_file() and path.stat().st_size > 0:
            print(f"ok      {name}: {path.name} ({path.stat().st_size} bytes)")
        else:
            print(f"MISSING {name}: {path.name}", file=sys.stderr)
            missing.append(name)
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="only verify that the bundled files exist")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    for name in ENCODINGS:
        path = OUTPUT / cache_name(URL.format(name=name))
        if path.is_file() and path.stat().st_size > 0:
            print(f"kept    {name}: {path.name} ({path.stat().st_size} bytes)")
            continue
        fetch(name)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
