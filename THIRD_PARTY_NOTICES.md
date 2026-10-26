# Third-party notices

Noesis Ebook Translator is distributed under the **GNU General Public License
version 3 or later** (see `LICENSE`). The corresponding source for this release
is the tagged repository:

<https://github.com/vigliafg/noesis-ebook-translator>

The translation engine (`noesis_ebook_translator/lib/`, `engines/`, `vendor/`)
is a verbatim copy of the fork of **bookfere/Ebook-Translator-Calibre-Plugin**
(GPLv3), with `engines/__init__.py` overridden locally to restore all engines.
See `ENGINE_SOURCE.json` for the exact fork commit.

## Components included in the installers

| Component | License | Notes |
| --- | --- | --- |
| **Noesis Ebook Translator** | GPL-3.0-or-later | this application |
| **bookfere Ebook Translator** engine | GPL-3.0-or-later | verbatim fork, source above |
| **Qt 6** / **PyQt6** | GPL-3.0-or-later (Qt also offers LGPL-3.0) | GUI, WebEngine; Qt license texts ship with the PyQt6 wheels and at <https://doc.qt.io/qt-6/licenses-used-in-qt.html> |
| **QtWebEngine / Chromium** | BSD-3-Clause and third-party licenses | Chromium notices ship with the QtWebEngine wheel; see <https://doc.qt.io/qt-6/licenses-used-in-qt.html> |
| **PyQt6-sip** | BSD-2-Clause | runtime bridge |
| **EbookLib** | **AGPL-3.0** | EPUB reading/writing; source at <https://github.com/aerkalov/ebooklib> |
| **lxml** | BSD-3-Clause | XHTML parsing |
| **mechanize** | BSD-3-Clause | HTTP stack used by the engine |
| **html5lib**, **six** | MIT | mechanize dependencies |
| **tiktoken** | MIT | token counting; BPE data is MIT |
| **regex** | Apache-2.0 | tiktoken dependency |
| **requests**, **urllib3**, **certifi**, **charset-normalizer**, **idna** | Apache-2.0 / BSD / MIT | tiktoken/HTTP dependencies |
| **python-docx** | MIT | DOCX export |
| **typing_extensions** | PSF-2.0 | python-docx dependency |
| **PyInstaller** | GPL-2.0-or-later with bootloader exception | packaging only; the exception permits proprietary bundles |
| **altgraph**, **macholib**, **pefile**, **pywin32-ctypes**, **packaging**, **pyinstaller-hooks-contrib** | MIT / BSD / Apache-2.0 | PyInstaller dependencies |
| **foliate-js** | MIT | vendored reader engine in `reader_web/foliate-js` (commit `78914ae`) |
| **Microsoft Fluent Emoji** | MIT | icons in `assets/icons` |
| **CPython** | PSF-2.0 | bundled interpreter |

## Notes

- The application is GPLv3; EbookLib is AGPLv3. GPLv3 §13 permits linking and
  combining the two. The combined distribution remains subject to the GPLv3
  for the application and to the AGPLv3 for EbookLib; the source of both is
  available at the links above.
- The release bundles are **not signed or notarized**. This is a distribution
  decision, not a license restriction.
- Full license texts are in `LICENSES/`; the GPLv3 text is also the root
  `LICENSE` file shown by the Windows installer.
