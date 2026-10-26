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
  destinazione in minuscolo: `libro-italian.epub` (cioè `*-<lingua>.epub`).

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

I comandi di lettura sono nella sezione **Reader** della barra (tema, fonte,
interlinea, ricerca, confronto, note, stampa) e nella **toolbar del lettore** sopra
il viewport (indice, precedente/successivo, pagina/scorrimento, singola/doppia,
zoom −/+, **schermo intero**). Il **TOC è quello Qt** (evidenzia la posizione
corrente; con le caselle in sezione *Translate* per selezionare i capitoli): per
leggere senza distrazioni **parte nascosto** e compare a richiesta, dal pulsante
della toolbar o dal nastro. Con **F11** (o il pulsante *Schermo intero*) la
finestra passa a tutto schermo e, dalla scheda *Lettura*, nasconde anche la barra
a nastro; si esce con **F11** o **Esc**, ripristinando la barra com'era. Nel
**full**, tema/dimensione/interlinea sono applicati al contenuto delle sezioni
(via `foliate-js setStyles`).

## Capitoli, figure, tabelle, export

- Traduci/ed esporta **l'intero libro o capitoli selezionati** dall'indice
  (EPUB di soli capitoli scelti, oppure HTML/Markdown/TXT).
- **Figure** (con didascalie `Fig./Plate/Table` e numerazione) e **tabelle**
  (con `caption`) esportabili in immagini/HTML/MD e CSV/HTML/MD.
- Anteprima traduzione **in memoria** di un capitolo.

## Motori supportati

L'app conosce tutti i motori ripristinati in `engines/__init__.py`:

| Categoria | Motori |
| --- | --- |
| Google (gratuiti) | `Google(Free)New`, `Google(Free)Html`, `Google(Free)` |
| Google (API) | `Google(Basic)`, `Google(Basic)ADC`, `Google(Advanced)` |
| LLM | `Gemini`, `ChatGPT`, `ChatGPT(Azure)`, `Claude`, `DeepSeek`, `OpenRouter` |
| DeepL | `DeepL`, `DeepL(Pro)`, `DeepL(Free)` |
| Altri | `MicrosoftEdge(Free)`, `Youdao`, `Baidu` |

Nelle liste di **scelta** (il gruppo *Motore* del ribbon, il wizard di traduzione e
il motore del giudice di qualità) i motori **non-LLM** compaiono sempre, mentre un
**LLM** compare **solo dopo che l'hai configurato**: i motori del plugin (Gemini,
ChatGPT, Claude, ChatGPT Azure, DeepSeek, OpenRouter) dalla pagina *Impostazioni →
Traduzione*, i provider curati abilitando uno slot in *Impostazioni → Provider*
(vedi sotto). Un motore configurato e poi lasciato senza credenziali esce dalla
lista finché non ne riceve di nuove: le pagine di configurazione continuano a
mostrare l'elenco completo.

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

## Download e installazione

Le release sono pubblicate su
[GitHub Releases](https://github.com/vigliafg/noesis-ebook-translator/releases).
La 0.10.0 è la prima release pubblica:

| Piattaforma | File | Note |
| --- | --- | --- |
| Windows 10/11 x64 | `NoesisEbookTranslator-windows-x64-setup.exe` | installa per tutti gli utenti (richiede admin) |
| Windows 10/11 x64 | `NoesisEbookTranslator-windows-x64.zip` | portatile (cartella onedir) |
| macOS Apple Silicon | `NoesisEbookTranslator-macos-arm64.dmg` | macOS 13+ |
| macOS Intel | `NoesisEbookTranslator-macos-x64.dmg` | macOS 13+ |
| Linux x86_64 | `NoesisEbookTranslator-amd64.deb` | Ubuntu 22.04+/Debian 12+ |
| Linux x86_64 | `NoesisEbookTranslator-x86_64.rpm` | Fedora 40+ |
| Linux x86_64 | `NoesisEbookTranslator-x86_64.AppImage` | glibc ≥ 2.35 |

I pacchetti includono **QtWebEngine** (lettore full, PDF/MOBI/AZW3/FB2/CBZ ed
export PDF) e **python-docx** (export DOCX): non serve installare Python.

**Le build non sono firmate.** Su macOS, al primo avvio: click destro sull'app
→ **Apri** (oppure `xattr -dr com.apple.quarantine
"/Applications/NoesisEbookTranslator.app"`). Su Windows SmartScreen può chiedere **Ulteriori informazioni
→ Esegui comunque**.

Su Linux l'AppImage può aver bisogno di FUSE; in alternativa
`./NoesisEbookTranslator-x86_64.AppImage --appimage-extract-and-run`.
Se Chromium non parte su un host senza user namespace, avviare con
`QTWEBENGINE_DISABLE_SANDBOX=1` (solo rimedio diagnostico: riduce l'isolamento
del browser).

La versione dell'**app** (0.10.0) è separata da quella del **motore** verbatim
(v2.4.2), visibile in *Info → Versione motore*: le migrazioni della
configurazione continuano a usare la versione del motore.

## Requisiti (esecuzione dal sorgente)

- **Python ≥ 3.10**
- PyQt6 ≥ 6.6, ebooklib, lxml, mechanize
  (vedi `requirements.txt`).
- Per il lettore full e l'export PDF/DOCX: `requirements-full.txt`
  (`PyQt6-WebEngine`, `python-docx`).
- Connessione a Internet per i motori online.

## Installazione (venv dedicato)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# lettore full, PDF e DOCX (opzionale ma consigliato)
.venv/bin/pip install -r requirements-full.txt
```

Su Windows:

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -r requirements-full.txt
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
Il_mio_libro.epub  ->  Il_mio_libro-italian.epub
```

Il suffisso è la lingua di destinazione in minuscolo, separata da un trattino
(`book.output_name()`): `*-<lingua>.epub`. L'estensione è sempre `.epub` e il
nome scelto nel wizard è solo la base (il suffisso viene aggiunto dall'app).

## Test

```bash
python -m unittest discover -s tests -v
```

I test girano **headless** (`QT_QPA_PLATFORM=offscreen`) e usano un motore di
traduzione fittizio offline: non serve la rete. In CI sono eseguiti su
`ubuntu-latest` (Python 3.12) da `.github/workflows/tests.yml`.

L'app espone anche un autotest per i bundle:

```bash
python main.py --self-test --require-full --report /tmp/self.json
python main.py --self-test-reader --report /tmp/reader.json
```

Il primo verifica risorse/import/EPUB e l'export PDF/DOCX; il secondo apre
davvero un EPUB col backend full (QtWebEngine). Il report è JSON perché un
bundle `--windowed` non ha stdout garantito su Windows/macOS.

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

Le release standalone sono compilate con **PyInstaller `--onedir`** su quattro
runner nativi (PyInstaller non fa cross-compile). La spec è
`packaging/app.spec`; i pacchetti nativi sono in `packaging/`.

| Target | Runner | Artefatto |
| --- | --- | --- |
| Windows x64 | `windows-latest` | installer NSIS `.exe` |
| Linux x86_64 | `ubuntu-22.04` | `.deb`, `.rpm`, `.AppImage` |
| macOS x86_64 | `macos-15-intel` | `.dmg` |
| macOS Apple Silicon (arm64) | `macos-15` | `.dmg` |

Il workflow `.github/workflows/release.yml` parte manualmente da
**Actions → release → Run workflow** (solo build, nessuna pubblicazione) oppure
al push del tag `v<APP_VERSION>` (per la 0.10.0: `v0.10.0`). La release viene
**pubblicata automaticamente** (stessa convenzione delle release di
`noesis-pdf-cloner`): nome = tag, note generate da GitHub, nessuna draft. Ogni
artefatto viene collaudato con `--self-test` e `--self-test-reader` prima di
essere caricato. Per la 0.10.0 non si usano release candidate: il dry-run
produce gli artefatti da provare, poi si tagga direttamente `v0.10.0`.

### Build locale (opzionale)

```bash
.venv/bin/pip install -r requirements-release.txt
.venv/bin/pyinstaller packaging/app.spec --noconfirm --clean
# output: dist/NoesisEbookTranslator/ (Linux/Windows) o
#         dist/NoesisEbookTranslator.app (macOS)
```

Su Linux:

```bash
packaging/linux/build-appimage.sh 0.10.0 NoesisEbookTranslator-x86_64.AppImage
VERSION=0.10.0 nfpm package -f packaging/linux/nfpm-deb.yaml -p deb -t dist/
```

La build locale usa le Qt del sistema se non sono installate da pip; per
riprodurre la release usare le versioni pinnate in `requirements-release.txt`.

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

Le licenze dei componenti inclusi (Qt/PyQt6, Chromium, EbookLib AGPL, foliate-js,
Fluent Emoji, tiktoken, python-docx, …) sono elencate in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) e i testi completi in
[`LICENSES/`](LICENSES/).
