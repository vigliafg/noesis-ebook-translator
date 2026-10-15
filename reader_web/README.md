# reader_web — foliate-js reader (full flavour)

Vendored [foliate-js](https://github.com/johnfactotum/foliate-js) (**MIT**, commit
`78914ae`) plus a small bridge that connects it to Qt/Python.

- `foliate-js/` — the upstream library **unmodified** (views, epub/pdf/mobi
  parsers, `reader.html` + `reader.js` demo UI, `ui/`, `vendor/`).
- `reader.html` — our page: a copy of `foliate-js/reader.html` with an adapted
  CSP and foliate's built-in chrome (header/nav/sidebar) **hidden** (we use the
  Qt toolbar and TOC). It loads `foliate-js/reader.js` and `noesis_bridge.js`.
- `noesis_bridge.js` — opens the channel, forwards `relocate`/`load` events to
  Python and exposes `window.api` (`goTo`, `next`, `prev`, `goToFraction`,
  `setTheme`, `setFont`, `setLineHeight`, `setZoom`, `setFlow`, `setSpread`,
  `search`). The book is opened by foliate from the `?url=` query parameter.
- `qwebchannel.js` — extracted from the Qt resource (`:/qtwebchannel/qwebchannel.js`).

Served through the private `app://` scheme (`noesis_ebook_translator/reader/scheme.py`):
the bundle under `app://reader/…`, the book under `app://reader/__book__/…`
(same origin, so no CORS/CSP friction).

The **lite** reader (`QTextBrowser`) does not use this folder.
