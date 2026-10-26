# assets

Risorse grafiche dell'app **Noesis Ebook Translator**.

## File

| File | Formato | Piattaforma | Note |
| --- | --- | --- | --- |
| `noesis-ebook-translator-source.jpg` | JPEG 189×176 | sorgente | artwork fornito dall'autore |
| `noesis-ebook-translator.png` | PNG 1024×1024 | Linux / icona finestra | master generato dal sorgente |
| `noesis-ebook-translator.ico` | ICO multi-risoluzione (16–256) | Windows (PyInstaller + NSIS) | generato dal master |
| `noesis-ebook-translator.icns` | ICNS (16–1024) | macOS (PyInstaller) | generato dal master |
| `linux/hicolor/256x256/apps/noesis-ebook-translator.png` | PNG 256×256 | deb/rpm/AppImage | icona hicolor |

Le icone sono generate una tantum dal sorgente con Pillow (upscale Lanczos +
leggero unsharp mask) e **committate**: la build non dipende da Pillow. Per
rigenerarle basta un PNG quadrato ≥ 512 px con lo stesso nome del master; poi
`packaging/` e `installer.nsi` le usano senza altre modifiche.

`icons/` contiene le icone semantiche dell'interfaccia (Fluent Emoji, MIT; vedi
`icons/LICENSE`).
