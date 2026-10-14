# Istruzioni per l'agente — Noesis Ebook Translator (app desktop)

## Cos'è questo repository

GUI desktop (**PyQt6** + **pyqtribbon**) per tradurre EPUB. L'entry point è
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

### Corpus Darwin

`tests/data/darwin/` contiene tre EPUB reali di **Charles Darwin** (Project
Gutenberg, pubblico dominio, edizione **`.epub.images`**), usati dai test
end-to-end (`tests/test_darwin_corpus.py`) con il motore fittizio. Il *Voyage of
the Beagle* è **illustrato** (15 immagini, 40 `<img>`): serve a verificare che le
illustrazioni sopravvivano alla traduzione. Vedi `tests/data/darwin/SOURCE.md`.
Per (ri)scaricarli: `python tools/fetch_darwin_fixtures.py`. I test online
opzionali (`NOESIS_ONLINE_TESTS=1`) traducono davvero con Google. Questo corpus è
**condiviso** col repo engine gemello (copiato dal suo `tools/sync_from_desktop.py`).

## File da NON toccare senza motivo

- `main.py`, `noesis_ebook_translator/**`, `calibre/**` — codice dell'app e
  motore verbatim. Le modifiche al motore devono passare da
  `tools/import_core_from_fork.py` (che produce copie identiche al fork).
- `.venv/` — ambiente virtuale locale.
