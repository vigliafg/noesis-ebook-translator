# License texts

`LICENSES/` is included in every installer (NSIS payload, `Contents/Resources`,
`/usr/share/doc/...`, AppDir). The mapping of components to licenses is in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

| File | Used by |
| --- | --- |
| `GPL-3.0-or-later.txt` | Noesis Ebook Translator, Qt, PyQt6 |
| `AGPL-3.0-or-later.txt` | EbookLib |
| `Apache-2.0.txt` | regex, requests, packaging, pyinstaller-hooks-contrib |
| `MIT.txt` + `MIT-notices.txt` | foliate-js, Fluent Emoji, tiktoken, python-docx, html5lib, six, altgraph, macholib, pefile |
| `BSD-3-Clause.txt` | lxml, mechanize, pywin32-ctypes |
| `BSD-2-Clause.txt` | PyQt6-sip |
| `PSF-2.0.txt` | the bundled CPython interpreter (see the Python license) |

QtWebEngine embeds Chromium: its BSD license and the third-party notices are
shipped by the Qt wheel and can also be found at
<https://doc.qt.io/qt-6/licenses-used-in-qt.html>.
