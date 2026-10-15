# Istruzioni per l'agente — Noesis Ebook Translator (app desktop)

## Cos'è questo repository

GUI desktop (**PyQt6**) per tradurre EPUB. L'entry point è
`main.py` (funzione `main()`); il pacchetto dell'app è `noesis_ebook_translator/`.

Questo repository è la **fonte di verità del motore**. Il repository gemello
`../noesis-ebook-translator-engine` (edizione CLI + TUI, monofile) **non ha un
motore proprio**: usa lo **stesso motore** copiato **verbatim** da qui.

## Motore verbatim dal fork del plugin Calibre

Il motore di traduzione è una copia **verbatim** del fork
`../Ebook-Translator-Calibre-Plugin` del plugin upstream
**bookfere/Ebook-Translator-Calibre-Plugin** (GPLv3):

- `noesis_ebook_translator/lib/` — `__init__.py`, `element.py`, `utils.py`,
  `exception.py`, `encodings.py`, `handler.py`, `translation.py`, `config.py`,
  `cache.py`.
- `noesis_ebook_translator/engines/*.py` — tutti i motori, **tranne**
  `engines/__init__.py`.
- `noesis_ebook_translator/vendor/` — l'intero albero (`cssselect/`, `socks.py`).

**Unica eccezione (override locale):** `noesis_ebook_translator/engines/__init__.py`.
Il fork aveva rimosso alcuni motori dalla tupla `builtin_engines`; questa app li
**ripristina tutti** (Gemini, ChatGPT, Claude, Azure ChatGPT, …). È quindi
l'unico file del motore intenzionalmente **non** verbatim: **non sovrascriverlo**
con quello del fork.

La provenienza del motore importato è registrata in `ENGINE_SOURCE.json`
(`fork_repo`, `fork_commit`, `fork_version`, `synced_at`, `verbatim`,
`overrides`).

## Shim `calibre/`

Il pacchetto top-level `calibre/` è uno **shim di compatibilità** necessario a
runtime: i moduli verbatim del plugin importano `calibre.*`
(`calibre.constants`, `calibre.utils.config`, `calibre.utils.localization`, …) e
il plugin inietta a runtime alcuni builtin (es. `load_translations`).
`noesis_ebook_translator/__init__.py` completa la compatibilità esponendo
`EbookTranslator` e `_z` e installando `load_translations` nei builtin.

Lo shim **non** è un pacchetto pip e **non** va pubblicato come "calibre" (vedi
`pyproject.toml`).

## Regole operative (sincronizzazione)

Per **aggiornare il motore dal fork**:

```bash
python tools/import_core_from_fork.py            # usa ../Ebook-Translator-Calibre-Plugin
python tools/import_core_from_fork.py --fork /percorso/del/fork
```

Lo script copia verbatim `lib/` (i 9 file), `engines/*.py` (senza `__init__.py`)
e `vendor/`, **salta le copie già identiche** (non tocca i file invariati) e
riscrive `ENGINE_SOURCE.json`. Dopo l'import, esegui sempre i test:

```bash
python -m unittest discover -s tests -v
```

Ogni volta che cambi il motore qui, i due repository **divergono** finché il repo
engine gemello non viene riallineato con il proprio `tools/sync_from_desktop.py`.

## Test

```bash
python -m unittest discover -s tests -v
```

I test girano **headless** (`QT_QPA_PLATFORM=offscreen`, impostato in
`tests/__init__.py`) e usano un motore fittizio offline
(`tests/fixtures.py`): **non serve la rete**. In CI:
`.github/workflows/tests.yml` (`ubuntu-latest`, Python 3.12).

### Corpus Project Gutenberg

`tests/data/corpus/` contiene **13 EPUB reali** di Project Gutenberg (pubblico
dominio, edizione **`.epub.images`**), usati dai test end-to-end
(`tests/test_corpus.py`) con il motore fittizio. **10** libri hanno **TOC
multilivello** (profondità ≥ 2) **e illustrazioni** (≥ 15): trattati e manuali
(anatomia, botanica, astronomia, bookbinding, meccanica…). Servono a verificare
che testo tradotto, `<img>`, link e **profondità del TOC** sopravvivano. Vedi
`tests/data/corpus/SOURCE.md` e `MANIFEST.json`.
Per (ri)scaricare: `python tools/fetch_corpus_fixtures.py`. I test online
opzionali (`NOESIS_ONLINE_TESTS=1`) traducono davvero con Google. Questo corpus è
**condiviso** col repo engine gemello (copiato dal suo `tools/sync_from_desktop.py`).

## Funzionalità desktop (solo GUI, fuori dal sync motore)

Questi moduli sono **desktop-only** (non inlineati nel repo gemello):

- `noesis_ebook_translator/paths.py` — directory dati dell'app.
- `noesis_ebook_translator/library.py` — libreria SQLite (libri, posizioni,
  annotazioni; migra `reader.json`). `reader/session.py` è un adapter su di essa.
- `noesis_ebook_translator/chapter_store.py` — libreria capitoli estratti/tradotti.
- `noesis_ebook_translator/segment.py` + `tools/segment_tool.py` — split/merge.
- `noesis_ebook_translator/quality/` + `tools/quality_harness.py` — valutazione
  qualità (metriche + giudice AI).
- `noesis_ebook_translator/help.py` — URL guida + fallback offline.
- `noesis_ebook_translator/ui/` — temi, wizard, impostazioni, help, export,
  animazioni, dialog qualità, **barra di workflow** (`workflow_bar.py`) e **icone**
  (`icons.py`).
- `assets/icons/` — icone colorate da **Microsoft Fluent Emoji** (MIT),
  generate da `tools/build_icons.py`; incluse nel bundle (`--add-data`).
- `noesis_ebook_translator/locales/*.json` — cataloghi interfaccia (5 lingue) e
  `main.py` (ribbon/tab). **Inclusi nel bundle** via `package-data` e
  `--collect-all noesis_ebook_translator` in `release.yml`.

**Guida**: `docs/site/` (MkDocs Material + i18n, 5 lingue) è pubblicata su
GitHub Pages da `.github/workflows/docs.yml`.

> Nota: `exporter.py` ed `extract.py` sono **condivisi** (inlineati nel repo
> gemello). Le funzioni aggiunte (export JSON/CSV/DOCX/PDF, write-back
> testi/tabelle/immagini) vanno rispecchiate con
> `tools/sync_from_desktop.py` nel repo engine.

## File da NON toccare senza motivo

- `main.py`, `noesis_ebook_translator/**`, `calibre/**` — codice dell'app e
  motore verbatim. Le modifiche al motore devono passare da
  `tools/import_core_from_fork.py` (che produce copie identiche al fork).
- `.venv/` — ambiente virtuale locale.

## Lettore (GUI) e harness

- `noesis_ebook_translator/reader/` — lettore: `document.py`, `lite_backend.py`
  (QTextBrowser), `webengine_backend.py` (foliate-js in QWebEngineView),
  `scheme.py` (scheme `app://`), `widget.py`, `session.py`, `panels.py`.
- `reader_web/` — bundle foliate-js **vendorizzato** (MIT) + wrapper QWebChannel.
  NON è un submodule: aggiornalo a mano e annota il commit in `reader_web/README.md`.
- Il backend è **`auto`** di default: usa **full** se QtWebEngine è importabile
  (va importato *prima* della `QApplication`: vedi `prepare_full()`), altrimenti
  ripiega su **lite**. Forzabile con `NOESIS_READER_BACKEND=full|lite|auto`.
- In test/CI `NOESIS_READER_BACKEND=lite` (impostato in `tests/__init__.py`) e la
  `QApplication` è creata prima dell'import di WebEngine, quindi i test restano
  sul backend lite (deterministico).
- Harness: `tests/harness.py` (scenario comune), `tests/test_reader_backends.py`
  (lite/full; il full gira in **sottoprocesso**), `tools/reader_harness.py` (CLI).
- NON importare `PyQt6.QtWebEngineWidgets` a livello di modulo nei test (blocca il
  processo): usa `importlib.util.find_spec` e i sottoprocessi.
