# noesis-ebook-translator

GUI desktop (**PyQt6**) per tradurre ebook **EPUB** in un'altra
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
- **Stima di token, costo e durata** nel wizard (tiktoken + prezzi dei provider) e
  **analisi del testo**: il modello rileva il genere e propone le istruzioni di
  stile per la traduzione (modificabili), che vengono accodate al system prompt
  del motore senza toccare l'integrità del testo.
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


## Lettore EPUB integrato

La GUI include un **lettore** con indice multilivello, navigazione, zoom, temi
(chiaro/sepia/scuro), ricerca e **vista parallela** (originale vs tradotto).
Esiste in due flavor:

- **full** (default quando disponibile): usa **foliate-js** (MIT) in
  `QWebEngineView` — ne incorporiamo il **motore di lettura** (`reader.html` +
  `reader.js` + bridge QWebChannel): EPUB, **MOBI/AZW3, FB2, CBZ, PDF**
  (pdf.js), due pagine (spread), **ricerca su tutto il libro**, note/evidenziazioni,
  note a piè di pagina, progress/CFI, stampa/export in PDF. Richiede
  `requirements-full.txt` (QtWebEngine);
- **lite** (fallback): `QTextBrowser`, solo EPUB, nessuna dipendenza extra.

Il backend è **automatico** (`auto`): usa il **full** se QtWebEngine è
importabile, altrimenti ripiega sul **lite**. Puoi forzare la scelta dalle
*Impostazioni* (o nel wizard) oppure con la variabile
`NOESIS_READER_BACKEND=full|lite|auto`.

I comandi di lettura sono nella sezione **Reader** della barra (fonte, interlinea,
zoom, ricerca, confronto, note, stampa) e nella mini-toolbar sopra il viewport
(precedente/successivo, pagina/scorrimento, singola/doppia). Il **TOC è quello Qt**
(evidenzia la posizione corrente; con le caselle in sezione *Translate* per
selezionare i capitoli). Nel **full**, tema/dimensione/interlinea sono applicati al
contenuto delle sezioni (via `foliate-js setStyles`).

## Capitoli, figure, tabelle, export

- Traduci/ed esporta **l'intero libro o capitoli selezionati** dall'indice
  (EPUB di soli capitoli scelti, oppure HTML/Markdown/TXT).
- **Figure** (con didascalie `Fig./Plate/Table` e numerazione) e **tabelle**
  (con `caption`) esportabili in immagini/HTML/MD e CSV/HTML/MD.
- Anteprima traduzione **in memoria** di un capitolo.

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

### Provider multipli (fino a 4)

Oltre ai motori del plugin, la scheda **Impostazioni → Provider** (e il wizard di
primo avvio) permette di configurare **fino a 4 provider OpenAI-compatibili**
contemporaneamente, ognuno con la **propria chiave API e il proprio modello**:
`OpenCode`, `OpenCode Go`, `OpenRouter`, `Groq`, `Mistral`, `xAI (Grok)`,
`Together`, `Fireworks`, `DeepInfra`, `Cerebras`, `SambaNova`, `NVIDIA NIM`,
`Moonshot (Kimi)`, `Z.AI (GLM)`, `Alibaba (DashScope)`, `Novita`, `HuggingFace`,
più un **endpoint personalizzato** (Ollama, LM Studio, vLLM, LiteLLM…).

- Le **liste modelli** sono aggiornate **live** dall'endpoint `/models` del
  provider (con cache e fallback incluso per l'uso offline); puoi rigenerarle con
  *Aggiorna modelli* (singolo provider), con *Rigenera tutte le liste* in
  **Impostazioni → Provider** o dal wizard di primo avvio.
- I modelli che richiedono un protocollo diverso dall'endpoint OpenAI (p.es.
  Claude e Gemini su OpenCode Go) vengono **nascosti**: restano solo quelli
  traducibili; se la lista in cache ha più di 24 ore l'app la riaggiorna da sola.
- Il **modello scelto viene testato automaticamente** (una traduzione breve) e
  l'esito compare inline: `✓ modello OK · 1,2s` oppure `✗ motivo` con *Riprova*.
- Lo stesso test parte dal **wizard «Traduci»** e l'esito resta visibile nel
  ribbon come **badge ✓/✗** accanto al modello.
- Solo i provider **abilitati** compaiono nella tendina del ribbon e del wizard;
  il provider si sceglie a ogni traduzione.

## Barra degli strumenti (workflow)

La barra è **custom** (nessuna libreria ribbon esterna): una **fascia superiore**
con **7 sezioni** e una **fascia inferiore** con i bottoni (**icona + nome
funzione**) della sezione attiva. Le icone sono Microsoft Fluent Emoji (MIT).

`Library · Reader · Assets · Translate · Quality · Export · Tools`

A sinistra della fascia alta c'è un pulsante **Start** (Apri/Aggiungi/Apri
cartella · Impostazioni · Wizard · Aiuto/Guida online · Informazioni ·
Diagnostica) e a destra la **rotella Impostazioni**. La navigazione tra le viste
avviene da qui (la barra a schede del pannello centrale è nascosta).

La **rotella** apre il **centro impostazioni** a tab (un unico posto): *Generale ·
Lettore · Traduzione · Qualità · Esportazione · Percorsi e dati · Assistenza e
info*. Il **tema del lettore è separato** dal tema dell'app; i controlli rapidi
nelle sezioni aggiornano anche i valori predefiniti.

- **Library**: libri originali, copie tradotte e capitoli (viste a toggle).
- **Reader**: indice, fonte/interlinea, zoom, ricerca, confronto, note, stampa/PDF.
- **Assets**: testi, figure e tavole estratti (con editor e salvataggio nell'EPUB).
- **Translate**: Traduci libro / Traduci capitoli, motore, lingue, opzioni, anteprima.
- **Quality**: valutazione (metriche + giudice AI) e report.
- **Export**: contenuto/edizione, formato e destinazione.
- **Tools**: split, merge e manutenzione.

Nel **TOC**: nella sezione *Reader* l'albero è cliccabile (solo bookmark); nella
sezione *Translate* è cliccabile **con le caselle di selezione** dei capitoli.

## Lingue

- **Origine**: rilevamento automatico (`Auto detect`) oppure una lingua esplicita.
- **Destinazione**: il set Google copre **~240 lingue** (`engines/languages.py`),
  ma la disponibilità effettiva dipende dal motore scelto.
- L'interfaccia e la **guida** sono disponibili in **5 lingue**: italiano,
  inglese, francese, spagnolo, tedesco (`noesis_ebook_translator/locales/*.json`
  + `docs/site/` pubblicato su GitHub Pages).

## Temi, onboarding, aiuto

- **Temi** (sistema, chiaro, scuro, seppia) applicati a tutta l'app (ribbon,
  pannelli, lettore). Selezionabili dal ribbon o dalle Impostazioni.
- **Wizard di benvenuto** al primo avvio (lingua, tema, motore + chiave API,
  backend di lettura). Si può **rilanciare** dalle Impostazioni
  (*Impostazioni… → Wizard di configurazione…*).
- **Aiuto** in-app (voce *Aiuto*, scorciatoia): apre la guida online nella lingua
  corrente, con fallback offline.
- **Animazioni** durante la traduzione (barra shimmer, progresso per capitolo),
  disattivabili con *Riduci animazioni*.

## Esportazione

Dal dialog *Esporta…* (o dagli strumenti) puoi esportare l'intero libro o i
**capitoli selezionati**, scegliendo fra **EPUB, HTML, Markdown, TXT, JSON, CSV**
e, se le dipendenze sono presenti, **DOCX** (`python-docx`) e **PDF**
(QtWebEngine). Puoi esportare l'edizione **originale** o **tradotta**.

## Libreria e capitoli

- **Libreria** persistente (SQLite) con copertina, ricerca, posizione di lettura e
  indicazione del file tradotto. Migra automaticamente il vecchio `reader.json`.
- **Libreria dei capitoli** estratti/tradotti con stato e ricerca.

## Qualità, split/merge, editor

- **Valutazione qualità** (`noesis_ebook_translator/quality/`): metriche
  automatiche (segmenti non tradotti/vuoti, lunghezze, numeri) + **giudice AI**
  opzionale. CLI: `python tools/quality_harness.py src.epub dst.epub [--judge OpenAI]`.
- **Split/merge** dei capitoli (originali o tradotti), preservando TOC e asset.
  CLI: `python tools/segment_tool.py split|merge ...`.
- **Editor** di testi, immagini e tavole con **scrittura nell'EPUB**
  (tab *Testi*, *Figure*, *Tabelle*).

## Requisiti

- **Python ≥ 3.10**
- PyQt6 ≥ 6.6, ebooklib, lxml, mechanize
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

### Corpus Project Gutenberg (fixture reali)

I test end-to-end girano su **13 libri veri** di Project Gutenberg (pubblico
dominio), in `tests/data/corpus/`, scaricati nell'edizione **`.epub.images`**:
**10** hanno insieme **TOC multilivello** (profondità ≥ 2) e **illustrazioni**
(≥ 15 immagini) — trattati, manuali e testi scientifici (botanica, anatomia,
astronomia, geologia, bookbinding, meccanica…). Elenco completo in
`tests/data/corpus/SOURCE.md`; catalogo leggibile in `MANIFEST.json`.

I test verificano che l'output sia un EPUB valido con **stesso numero di
documenti**, traduzioni applicate, **ancore/link**, **illustrazioni** (`<img>`) e
**profondità del TOC** preservati.

```bash
python tools/fetch_corpus_fixtures.py            # (ri)scarica corpus + MANIFEST.json
NOESIS_ONLINE_TESTS=1 python -m unittest tests.test_corpus -v   # + test Google reale
```


### Harness del lettore (lite + full)

`tests/harness.py` esegue lo stesso scenario su entrambi i backend e produce un
report; `tests/test_reader_backends.py` lo usa per i test automatici, mentre
`tools/reader_harness.py` è il runner da riga di comando (utile per validare il
backend **full** su un desktop reale):

```bash
python tools/reader_harness.py --mode both --wait 15 libri/*.epub
```

Il backend **full** richiede un WebEngine funzionante (GPU/display); su macchina
headless il report riporta `ready=False` (warning, non errore).

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
  main.py
```

## Edizione CLI/engine

Esiste un repository gemello **`noesis-ebook-translator-engine`** (CLI + TUI,
monofile): condivide **lo stesso motore verbatim** e usa questo repo come **fonte
di verità**. La provenienza del motore importato è registrata in
`ENGINE_SOURCE.json`; l'aggiornamento dal fork avviene con
`python tools/import_core_from_fork.py`.

## Changelog

Le modifiche rilevanti sono elencate in [CHANGELOG.md](CHANGELOG.md).

## Licenza

**GNU General Public License v3.0** (o successive) — vedi [LICENSE](LICENSE).

Quest'opera deriva dal plugin **Ebook Translator** di **bookfere**, distribuito
sotto la stessa licenza GPLv3; gli engine e la gestione degli elementi sono copie
verbatim dell'upstream. Se ridistribuisci o modifichi l'app, mantieni
l'attribuzione a bookfere e la licenza GPLv3.
