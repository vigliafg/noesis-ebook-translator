# assets

Risorse grafiche dell'app **Noesis Ebook Translator**.

## File attesi

| File | Formato | Piattaforma | Note |
| --- | --- | --- | --- |
| `noesis-ebook-translator.png` | PNG 256×256 | Linux / AppImage, icona finestra | **presente** (placeholder) |
| `noesis-ebook-translator.ico` | ICO multi-risoluzione | Windows (PyInstaller + NSIS) | da aggiungere prima della release |
| `noesis-ebook-translator.icns` | ICNS | macOS (PyInstaller) | da aggiungere prima della release |
| `noesis-ebook-translator.svg` | SVG | sorgente vettoriale (opzionale) | facoltativo |

Le **icone reali** (`.ico` e `.icns`) verranno inserite **prima della release**:
i workflow di build le referenziano, ma se assenti il build ripiega senza icona
(vedi `.github/workflows/release.yml`).

Il `noesis-ebook-translator.png` attualmente presente è un **placeholder**
generato automaticamente (256×256, sfondo blu scuro con un glifo "libro"):
serve a far girare build e AppImage finché non arriva l'icona definitiva.
Per rigenerarlo basta un PNG valido 256×256 con lo stesso nome.

## Uso nell'app

`main.py` carica `assets/noesis-ebook-translator.png` come icona della finestra:

```python
icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "noesis-ebook-translator.png")
```

## Uso nelle build

- **Windows** — `--icon assets/noesis-ebook-translator.ico` (PyInstaller) e
  `!define MUI_ICON "assets\noesis-ebook-translator.ico"` (`installer.nsi`).
- **macOS** — `--icon assets/noesis-ebook-translator.icns` (PyInstaller).
- **Linux / AppImage** — `assets/noesis-ebook-translator.png` copiato
  nell'AppDir come `NoesisEbookTranslator.png`.
