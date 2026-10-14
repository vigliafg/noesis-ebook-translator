# noesis-ebook-translator

GUI desktop (**PyQt6** + **pyqtribbon**) per tradurre ebook **EPUB** in un'altra
lingua conservando la formattazione, i markup inline e l'indice. Il motore di
traduzione è preso **verbatim** dal plugin Calibre
[bookfere/Ebook-Translator-Calibre-Plugin](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin)
(GPLv3); questa app ne è un front-end snello: apri un EPUB, scegli motore e
lingue, traduci.

## Cosa fa

- Apre un file **EPUB** e lo traduce nella lingua di destinazione scelta.
- Preserva i **link/ancore** e i **blocchi di codice**, e traduce l'**indice**
  (TOC) insieme al testo. Il testo in corsivo/grassetto viene tradotto (il tag
  `em`/`i`/`b`… viene sostituito dal testo tradotto): puoi riservare altri
  elementi con l'impostazione `reserve_rules`.
- Mostra una **barra a nastro (ribbon)** con gruppi *Home · Motore · Lingua ·
  Opzioni · Info*: apri file, avvia/annulla la traduzione, apri la cartella di
  output.
- **Progresso** in tempo reale, log dell'avvenuta traduzione e stato del lavoro.
- **Cache** su disco: le parti già tradotte non vengono ritradotte (utile in caso
  di errore di rete o interruzione).
- **Testo bilingue** opzionale (traduzione sotto l'originale) oltre alla modalità
  *solo traduzione*.
- L'output è scritto accanto al file di origine con il suffisso della lingua di
  destinazione in maiuscolo: `libro_ITALIAN.epub` (cioè `*_<LINGUA>.epub`).

## Motore verbatim dal plugin Ebook Translator

Tutti i moduli che fanno il lavoro pesante sono **copie verbatim** del fork del
plugin Calibre di **bookfere**:

- `noesis_ebook_translator/lib/` — gestione elementi, traduzione, cache, config,
  handler (`element.py`, `translation.py`, `cache.py`, …).
- `noesis_ebook_translator/engines/` — i motori di traduzione.
- `noesis_ebook_translator/vendor/` — dipendenze incluse dal plugin
  (`cssselect`, `socks.py`).

L'unico file **non** verbatim è `engines/__init__.py`: è un *override locale* che
ripristina **tutti** i motori del plugin (il fork ne aveva rimossi alcuni). Vedi
`AGENTS.md` e `ENGINE_SOURCE.json`.

Crediti e ringraziamenti:

- Autore del plugin originale: **bookfere** — <https://translator.bookfere.com>
- Repository upstream: <https://github.com/bookfere/Ebook-Translator-Calibre-Plugin>
- Licenza upstream: **GNU GPL v3.0**.

## Motori supportati

L'app espone tutti i motori ripristinati in `engines/__init__.py`:

| Categoria | Motori |
| --- | --- |
| Google (gratuiti) | `Google(Free)New`, `Google(Free)Html`, `Google(Free)` |
| Google (API) | `Google(Basic)`, `Google(Basic)ADC`, `Google(Advanced)` |
| LLM | `Gemini`, `ChatGPT`, `ChatGPT(Azure)`, `Claude`, `DeepSeek`, `OpenRouter` |
| DeepL | `DeepL`, `DeepL(Pro)`, `DeepL(Free)` |
| Altri | `MicrosoftEdge(Free)`, `Youdao`, `Baidu` |

I motori LLM e le API a pagamento richiedono una **chiave API** (e a volte un
**modello**, es. `gpt-4o-mini`): i campi credenziali compaiono nel gruppo
*Motore* del ribbon e vengono salvati tra le sessioni. I motori Google gratuiti,
DeepL Free e Microsoft Edge funzionano senza chiave.

## Lingue

- **Origine**: rilevamento automatico (`Auto detect`) oppure una lingua esplicita.
- **Destinazione**: il set Google copre **~240 lingue** (`engines/languages.py`),
  ma la disponibilità effettiva dipende dal motore scelto.
- L'interfaccia è disponibile in **italiano** e **inglese** (`i18n.py`).

## Requisiti

- **Python ≥ 3.10**
- PyQt6 ≥ 6.6, pyqtribbon ≥ 0.7.8, qtpy, ebooklib, lxml, mechanize
  (vedi `requirements.txt`).
- Connessione a Internet per i motori online.

## Installazione (venv dedicato)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Su Windows:

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Uso

```bash
.venv/bin/python main.py
```

1. **Home → Apri EPUB…** per selezionare il file.
2. Nel gruppo **Motore** scegli il traduttore; se serve, inserisci **chiave API** e
   **modello**.
3. Nel gruppo **Lingua** imposta **origine** (o *Auto detect*) e **destinazione**.
4. In **Opzioni** seleziona *Testo bilingue*, *Usa cache* e *Batching online*.
5. Premi **Traduci**. A fine corsa premi **Apri cartella** per raggiungere il file.

## Output

Il file tradotto viene salvato accanto all'originale:

```text
Il_mio_libro.epub  ->  Il_mio_libro_ITALIAN.epub
```

Il suffisso è la lingua di destinazione (`default_output_path`) convertita in
maiuscolo: `*_<LINGUA>.epub`.

## Test

```bash
python -m unittest discover -s tests -v
```

I test girano **headless** (`QT_QPA_PLATFORM=offscreen`) e usano un motore di
traduzione fittizio offline: non serve la rete. In CI sono eseguiti su
`ubuntu-latest` (Python 3.12) da `.github/workflows/tests.yml`.

### Corpus Darwin (fixture reali)

I test end-to-end girano su tre libri veri di **Charles Darwin** da Project
Gutenberg (pubblico dominio), in `tests/data/darwin/`:

| File | Project Gutenberg |
| --- | --- |
| `origin_of_species.epub` | [#1228 — On the Origin of Species](https://www.gutenberg.org/ebooks/1228) |
| `voyage_of_the_beagle.epub` | [#944 — The Voyage of the Beagle](https://www.gutenberg.org/ebooks/944) |
| `descent_of_man.epub` | [#2300 — The Descent of Man](https://www.gutenberg.org/ebooks/2300) |

```bash
python tools/fetch_darwin_fixtures.py          # (ri)scarica le fixture
NOESIS_ONLINE_TESTS=1 python -m unittest tests.test_darwin_corpus -v   # + test Google reale
```

## Build delle release (GitHub Actions)

Le release standalone sono compilate con **PyInstaller** su quattro runner nativi
(PyInstaller non fa cross-compile):

| Target | Runner |
| --- | --- |
| Windows x64 | `windows-latest` |
| Linux x64 | `ubuntu-latest` |
| macOS x86_64 | `macos-15-intel` |
| macOS Apple Silicon (arm64) | `macos-15` |

Il workflow `.github/workflows/release.yml` parte manualmente da
**Actions → build-releases → Run workflow** oppure al push di un tag `v*`
(es. `git tag v1.0.0 && git push --tags`), creando una **GitHub Release** con gli
artefatti: `.exe` (installer NSIS) su Windows, **AppImage** su Linux, `.dmg` su
macOS. Gli eseguibili macOS non sono firmati: al primo avvio usare click destro →
**Apri** per aggirare Gatekeeper.

### Build locale (opzionale)

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller --onefile --windowed --name NoesisEbookTranslator \
  --collect-all pyqtribbon main.py
```

## Edizione CLI/engine

Esiste un repository gemello **`noesis-ebook-translator-engine`** (CLI + TUI,
monofile): condivide **lo stesso motore verbatim** e usa questo repo come **fonte
di verità**. La provenienza del motore importato è registrata in
`ENGINE_SOURCE.json`; l'aggiornamento dal fork avviene con
`python tools/import_core_from_fork.py`.

## Licenza

**GNU General Public License v3.0** (o successive) — vedi [LICENSE](LICENSE).

Quest'opera deriva dal plugin **Ebook Translator** di **bookfere**, distribuito
sotto la stessa licenza GPLv3; gli engine e la gestione degli elementi sono copie
verbatim dell'upstream. Se ridistribuisci o modifichi l'app, mantieni
l'attribuzione a bookfere e la licenza GPLv3.
