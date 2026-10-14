# reader_web — foliate-js bundle (full reader flavour)

Vendored [foliate-js](https://github.com/johnfactotum/foliate-js) (**MIT**, commit
`78914ae`) plus a thin wrapper (`index.html`, `main.js`) that exposes a small API
to Python over **QWebChannel**. Served inside `QWebEngineView` through the private
`app://` scheme (`noesis_ebook_translator/reader/scheme.py`).

`qwebchannel.js` is extracted from the Qt resource (`:/qtwebchannel/qwebchannel.js`).

The **lite** reader flavour (`QTextBrowser`) does not use this folder.
