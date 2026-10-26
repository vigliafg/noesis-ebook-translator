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
**ripristina tutti** (Gemini, ChatGPT, Claude, Azure ChatGPT, …) e vi appende i
provider curati generati da `engines/openai_compatible.py`. È quindi l'unico file
del motore intenzionalmente **non** verbatim: **non sovrascriverlo** con quello
del fork.

**Estensioni locali del motore** (file che nel fork non esistono): 
`engines/openai_compatible.py` (trasporto generico OpenAI-compatible + una classe
per provider) — dichiarato in `ENGINE_SOURCE.json` sotto `extensions` e in
`tools/import_core_from_fork.py` (`EXTENSIONS`). Va aggiunto a `CORE_MODULES`
dello script di sync del repo engine: **ogni modifica al motore va risincronizzata**
(`noesis-ebook-translator-engine/tools/sync_from_desktop.py` + test).

Il **catalogo dei provider** (`noesis_ebook_translator/provider_catalog.py` e lo
snapshot `data/providers.json`) è **condiviso**: viene inlineato nel motore CLI
(è in `CORE_MODULES`), mentre le parti solo-GUI (schede Impostazioni, widget di
test) restano fuori dal sync. Rigenera lo snapshot con
`python tools/fetch_provider_catalog.py`.

La provenienza del motore importato è registrata in `ENGINE_SOURCE.json`
(`fork_repo`, `fork_commit`, `fork_version`, `synced_at`, `verbatim`,
`overrides`, `extensions`).

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

### Harness di scenario (invarianti di stato)

`tests/harness.py` espone due harness molto diversi:

- `run_feature_harness` — **smoke**: la finestra si costruisce, un libro si apre,
  gli asset caricano. Verifica «non è esploso».
- `run_scenario_matrix` — **invarianti**: esegue **davvero** traduzioni su una
  matrice di condizioni (cache assente / piena / parziale / grande >50 kB,
  capitolo nuovo **prima** o dopo la cache, selezione che si restringe, TOC
  multilivello, anchor) e controlla che `segmenti processati == pianificati`,
  che nessun capitolo resti `pending`, che l'output contenga la traduzione in
  **ogni** documento e in **tutti** i livelli del TOC. Ogni condizione gira in un
  thread con **watchdog**: uno stallo è un test rosso, non una suite appesa.

```bash
python tools/scenario_harness.py          # tabella + exit code
python tools/scenario_harness.py --json   # report grezzi
```

`tests/test_scenarios.py` è il wrapper unittest (una condizione = un test, più
il caso GUI «cache mista → 100%» e l'annullamento).

### Canale stderr asserito

`tests/test_console_clean.py` esegue `python -m tests.console_probe {gui,engine,reader}`
in **sottoprocessi** e fallisce su `Traceback`, `AttributeError`,
`Release of profile requested`, `SIGSEGV`, … con allow-list per il rumore di
piattaforma headless (`QRhiGles2`, `Vulkan`, `libpng`). È l'unico modo per
accorgersi delle eccezioni negli slot Qt (PyQt le stampa e prosegue) e dei
warning di Chromium.

> Le due classi di bug che questo harness ha trovato al primo colpo sono in
> `book.py`: la cache era riconciliata per **indice posizionale** (`id`), non per
> contenuto, e un annullamento veniva riportato come traduzione riuscita con un
> file parziale scritto su disco.

### TOC di libri con manifest rotto

`chapters.py` (**condiviso**) legge l'indice con `ebooklib`. Alcuni libri reali sono
re-pack "slim" con il **package document che mente**: dichiara font/script che non
sono più nell'archivio (nel corpus reale: Davidson's, 48 font MathJax assenti), e
`ebooklib` si rifiuta di leggere il libro. In quel caso l'indice viene letto
**direttamente dallo zip** (NCX, o il documento di navigazione EPUB 3). Se anche
questo fallisce, `load_chapters` solleva `ChapterError` con un messaggio leggibile:
la banda 2 lo **mostra** al posto del generico «nessuna voce», e `book.py` solleva
`TranslationFailed` spiegando che il file è incompleto/malformato.

### Corpus Project Gutenberg

`tests/data/corpus/` contiene **13 EPUB reali** di Project Gutenberg (pubblico
dominio, edizione **`.epub.images`**), usati dai test end-to-end
(`tests/test_corpus.py`) con il motore fittizio. **10** libri hanno **TOC
multilivello** (profondità ≥ 2) **e illustrazioni** (≥ 15): trattati e manuali
(anatomia, botanica, astronomia, bookbinding, meccanica…). Servono a verificare
che testo tradotto, `<img>`, link e **profondità del TOC** sopravvivano. Vedi
`tests/data/corpus/SOURCE.md` e `MANIFEST.json`.
Per (ri)scaricare: `python tools/fetch_corpus_fixtures.py`. I test online
opzionali (`NOESIS_ONLINE_TESTS=1`) traducono davvero con Google e **verificano che
i segmenti tornino tradotti** (non solo che il file esista: controllare la dimensione
passerebbe anche se fallisse tutto). Limite noto del motore gratuito: i segmenti
molto lunghi (~17 kB) fanno rispondere **HTTP 400** all'endpoint GET e restano in
**errore** in banda 2; con `request_attempt` di default ogni fallimento costa 5-10 s
di backoff. Questo corpus è **condiviso** col repo engine gemello (copiato dal suo
`tools/sync_from_desktop.py`).

### Test dei comportamenti "da motore reale" (offline)

`tests/test_real_engines.py` copre ciò che il motore fittizio non può: latenza,
**concorrenza** (`concurrency_limit>1`, misurata con un contatore di richieste in
volo), **errori per segmento** (una riga in errore, le altre completano),
**generatori/stream** (i motori GenAI restituiscono un generatore), **batching**
(`translate_batch`) e **rate limit** (`request_interval`). Usa il motore `Realistic`
di `tests/fixtures.py` (knob nel dict `REALISTIC`): tutto **offline, nessuna chiave**.

## Funzionalità desktop (solo GUI, fuori dal sync motore)

Questi moduli sono **desktop-only** (non inlineati nel repo gemello):

- `noesis_ebook_translator/paths.py` — directory dati dell'app: **config** nel
  percorso di configurazione (JSON del motore), **dati** in
  `Application Support`/`%LOCALAPPDATA%`/`$XDG_DATA_HOME`; migrazione
  una-tantum copia-e-verifica dal vecchio percorso, con originali intatti.
- `noesis_ebook_translator/selfcheck.py` — `--self-test` e
  `--self-test-reader`: verificano le risorse del bundle congelato e aprono un
  EPUB col backend full, scrivendo un report JSON (i bundle `--windowed` non
  hanno stdout).
- `noesis_ebook_translator/logging_setup.py` — log rotante in
  `data_dir()/logs/app.log` ed `excepthook` (handler Qt solo nei bundle).
- `noesis_ebook_translator/library.py` — libreria SQLite (libri, posizioni,
  annotazioni; migra `reader.json`). `reader/session.py` è un adapter su di essa.
- `noesis_ebook_translator/chapter_store.py` — libreria capitoli estratti/tradotti.
- `noesis_ebook_translator/segment.py` + `tools/segment_tool.py` — split/merge.
- `noesis_ebook_translator/quality/` + `tools/quality_harness.py` — valutazione
  qualità (metriche + giudice AI).
- `noesis_ebook_translator/token_count.py` — conteggio token con **tiktoken**
  (encoder BPE inclusi in `data/tiktoken`, fallback euristico per script).
  Rigenera i file con `tools/fetch_token_encodings.py`.
- `noesis_ebook_translator/estimate.py` — stima token/costo/durata (prezzi da
  `provider_catalog.price()`, latenza calibrata sulle statistiche dei run).
- `noesis_ebook_translator/text_analysis.py` — analisi del genere e costruzione
  del prompt di stile (runner LLM iniettabile).
- `noesis_ebook_translator/help.py` — URL guida + fallback offline.
- `noesis_ebook_translator/ui/` — temi, wizard, impostazioni, help, export,
  animazioni, dialog qualità, **barra di workflow** (`workflow_bar.py`) e **icone**
  (`icons.py`).
- `assets/icons/` — icone colorate da **Microsoft Fluent Emoji** (MIT),
  generate da `tools/build_icons.py`; incluse nel bundle dai `datas` di
  `packaging/app.spec`.
- `noesis_ebook_translator/locales/*.json` — cataloghi interfaccia (5 lingue) e
  `main.py` (ribbon/tab). **Inclusi nel bundle** via `package-data` e
  `collect_all("noesis_ebook_translator")` in `packaging/app.spec`.

### Banda 2 «Capitoli» (contratto)

`progress_model.py` + `ui/chapter_track.py` mostrano **una riga per voce del
TOC**, in ordine di lettura, indentata per profondità — **mai** una riga per file
(due capitoli possono stare nello stesso XHTML con ancore diverse: CHAPTER IV e
V del corpus). Le intestazioni senza documento restano come righe
(`STATE_HEADER`, nessuna barra/conteggio).

- **Stato A** (libro aperto, nessun run attivo): l'intera gerarchia è già lì,
  tutte le voci in font normale. Se esiste una cache per il libro, le righe sono
  seminate con il piano e la copertura dell'ultimo run
  (`book.chapter_cache_status`): «Tradotti» / «Da tradurre» sono significativi
  **prima** di avviare qualcosa, e le righe parziali restano visibili senza
  animazioni. Se non c'è cache, restano senza numeri. In entrambi i casi la
  testata è `Capitoli · —`: nessun capitolo è «corrente» finché non parte un run.
- **Stato B** (dopo il wizard / durante): selezionati normali, gli altri
  **grigi** (`STATE_EXCLUDED`); i capitoli in lavorazione con **barra +
  `done/total`**. Filtri «Tutti» / «Da tradurre» / «Tradotti»: con «Da tradurre»
  restano solo le sezioni che hanno ancora un figlio visibile.
- **Stato C** (fine corsa, vista «Tutti»): i tradotti restano nella gerarchia in
  **neretto + check + barra piena**.
- **`done` = tradotto con successo**, non «processato». Un segmento fallito va
  in `errors`: la riga è rossa, la barra si ferma sotto il totale e
  `overall_percent()` **non** arriva a 100. La percentuale globale e quella del
  capitolo descrivono traduzioni, non tentativi.
- **Cancel/fail chiudono il run**: `ProgressModel.finish(ok=False)` alza
  `finished`, `running_units()` torna vuoto e timer/header smettono di pulsare.
  Le righe parziali restano visibili (non fingono il completamento).
- **`finish(ok=True)` non promuove** un capitolo a `total`: contano solo i
  callback. I documenti con `done < total` finiscono in `incomplete` e vengono
  loggati a fine run.
- **Filtri e heading**: una heading resta solo se un suo discendente è visibile;
  un documento alla stessa profondità è un sibling e interrompe il sottoalbero
  (bug del vecchio scan, che guardava solo le heading).
- **Selezione vuota**: nel wizard capitoli `[]` non è «tutto il libro»; l'utente
  deve confermarlo (`whole_book`). La selezione viaggia come **href con ancora**
  (`main._normalize_chapter_spec`, `TranslateWizard._chapter_choices`): passare
  nomi di file fondeva le voci che condividono un documento (selezionare
  CHAPTER V ne traduceva 87 segmenti invece di 8).
- I totali (`overall/summary/done_chapters`) si contano sui **documenti unici**,
  così due voci sullo stesso file non contano due volte. I documenti che il
  motore traduce ma il TOC non menziona (cover, nav) vengono aggiunti in coda
  con `extra=True` ed etichettati «fuori indice».
- La barra è disegnata **dentro** la riga (`BAR_TOP`, non sugli ultimi 2 px):
  una riga tagliata dal viewport non perde più la barra.
- **Scala**: il delegate costruisce il payload **su richiesta** (`row_data`), solo
  per le righe che dipinge; la vista filtrata è **cache per
  `(filtro, model.revision, ricerca)`** e le mappe file→riga rendono header e
  scroll O(1). Il corpus locale dell'utente arriva a **7541 voci** (Ferri's).
- **Orientamento**: la testata mostra `done/total capitoli · errori · in corso`,
  i filtri portano il conteggio (`Tutti (n)`, `Da tradurre (n)`, `Tradotti (n)`),
  c'è una ricerca libera e due salti («Primo da tradurre», «Prossimo errore»).
  La legenda spiega punto/check/cancel/`—`; il pulsante **Segui** accende o
  spegne l'auto-scroll.
- **Righe**: tooltip dinamico con nome completo, file/ancora, stato, `done/total`,
  cache ed errore (testo compreso); `AccessibleTextRole` e testo dell'item per i
  lettori di schermo; focus da tastiera e **Invio/double-click** aprono il
  capitolo nel lettore. Le heading hanno chevron e peso maggiore; le righe
  parziali dopo un cancel o all'apertura della cache restano ferme e smorzate
  («interrotto»).
- **Parallelo**: con più capitoli in lavorazione la testata non finge un
  «capitolo corrente»: mostra `N capitoli in corso` e la percentuale complessiva.

### Ripresa dopo un'interruzione (cache a prova di blackout)

`book.py` committa **ogni** segmento appena tradotto (una riga per segmento) e lo
registra anche in una tabella **per contenuto** (`noesis_resume`, stessa SQLite),
collegata a *motore + modello + lingua sorgente/destinazione*:

- un blackout a metà traduzione **non perde nulla**: rilanciando la stessa
  traduzione il motore viene interrogato **solo** per i segmenti mancanti
  (`tests/test_resume.py` uccide davvero il processo a metà e verifica la ripresa);
- cambiare **selezione** non distrugge il lavoro: la cache posizionale viene
  ricostruita, le traduzioni tornano dalla tabella per contenuto (prima si
  perdevano i capitoli fuori selezione);
- cambiare **modello** non mescola: le traduzioni della cache vengono azzerate e la
  tabella per contenuto conserva il lavoro *per modello* (tornando indietro si riprende);
- testo identico condivide la traduzione (stessa semantica di
  `add_translations`, che indicizza per contenuto);
- l'EPUB finale è scritto su `*.part` e rinominato con `os.replace`: un blackout
  durante il salvataggio non lascia un file corrotto al posto di uno valido.

Il motivo per cui la tabella è necessaria: la cache verbatim indicizza per
**posizione**, quindi una selezione diversa ri-indicizza le righe e il suo rebuild
scarta tutto ciò che è fuori selezione. `cache.info` conserva modello, lingua e
selezione; `on_resume(done, total)` dice alla GUI quanti segmenti arrivano dalla cache.

**Marker di stato (l'app «sa» che il run è interrotto).** Ogni run scrive in
`cache.info` anche `run_status`:

- `running` all'avvio. Un processo che muore (blackout, SIGKILL, crash) **non**
  scrive nient'altro: il marker restato `running` è la firma dell'interruzione
  (vale anche per un errore di rete che ferma un run lungo);
- `finished` dopo `os.replace` dell'EPUB, `cancelled` sull'annullamento esplicito
  (nessuno dei due viene più proposto);
- `dismissed` quando l'utente risponde «No» al prompt: il lavoro resta, ma non
  viene richiesto di nuovo per quel run.

`book.interrupted_runs(input_path)` scansiona in sola lettura i `*.db` della cache
e restituisce i run `running` del libro, con titolo, motore, modello, lingue,
selezione, `input_path`/`output_path`, opzioni e `done/total`. All'apertura di un
libro `main._offer_resume()` chiede «Traduzione interrotta: N/M — Riprendere?» e,
se si accetta, `_resume_run()` riparte con **lo stesso** motore/modello/lingua/
selezione (la chiave API arriva da `engine_preferences`). Non è indispensabile per
la correttezza (la ripresa è automatica), ma evita che ore di lavoro restino in
cache senza che l'utente lo sappia. Test: `tests/test_interrupted_run.py`.

La cache (e la tabella di ripresa) vive in `<dati app>/translator-cache/cache`:
`main.py` imposta `cache_path` **prima** di importare `book`, perché la cache
verbatim userebbe la directory temporanea di sistema (`/tmp`), che un riavvio può
svuotare. Al primo avvio le cache di una versione precedente vengono migrate.

### Wizard: analisi del testo, stile e stima di costo

Il wizard di traduzione ha due pagine nuove, **nell'ordine** *Contenuto → Motore
→ Analisi del testo → Costi e durata → Opzioni → Output*: la stima dipende dallo
stile, quindi l'analisi viene prima.

**Analisi del testo** (`text_analysis.py` + `ui/analysis_page.py`). Il modello
scelto legge un campione (~6.000 caratteri distribuiti, estratti dai segmenti
reali) e risponde in JSON con categoria/genere/registro/tono/pubblico/epoca e
3-6 istruzioni. Da lì `build_style_prompt()` costruisce un **addendum** che
`book.translate_epub(style_prompt=…)` **accoda** al prompt del motore (le regole
base di integrità e i segnaposto restano). Il prompt è modificabile, applicabile o
saltabile; un errore non blocca mai la traduzione (fallback `generic_style_prompt`).
Gli esempi sono trattati come dati, non istruzioni; le regole di integrità sono
sempre in coda. La pagina viene **saltata** per i motori senza `prompt`
(`appconfig.engine_supports_prompt`), cioè per i traduttori non-LLM.

**Stile nella cache.** Lo stile è parte dell'identità del run: `noesis_resume` ha
la colonna `style_hash` (migrata automaticamente dalle tabelle v1, che restano
valide per lo scope senza stile) e `run_style_hash` in `cache.info` fa scattare
l'azzeramento delle traduzioni posizionali quando lo stile cambia — stesso
pattern del cambio modello. Cambiare stile ritraduce; tornare allo stile
precedente riprende il suo lavoro; la ripresa dopo un blackout riusa lo stile
salvato in `run_options` senza rifare l'analisi.

**Costi e durata** (`estimate.py` + `ui/estimate_page.py`). Conta i token con
`token_count` (tiktoken: `o200k_base`/`cl100k_base`, encoder BPE inclusi nel
pacchetto così funziona offline), include il **prompt di sistema per richiesta**
(è spesso il costo dominante) e le richieste (una per segmento, o `ceil(n/20)` con
il batching), esclude i segmenti già in cache *per lo stesso scope di stile*, e
moltiplica per i prezzi dello snapshot (`provider_catalog.price()`, USD/1M token;
modelli builtin mappati con `estimate.ENGINE_TO_MODELS_DEV`). La durata è un
intervallo: latenza misurata dai run precedenti (`run_started_at`,
`run_finished_at`, `run_engine_calls`, `run_concurrency`, `run_batching` in
`cache.info`), altrimenti un default per motore; concorrenza 1 se sequenziale,
altrimenti la scelta dell'utente (spinbox 1-8, salvata in `translate_parallel`).

Lo stile viaggia anche nel worker: `TranslationWorker(style_prompt=…, genre=…)` e
`main._resume_run()` lo recuperano da `run_options`.

### Nome del file tradotto (e sovrascritture)

Il nome scelto nel wizard è solo la **base**: l'app aggiunge **sempre** il suffisso
`-<lingua>` (slug minuscolo: `Italian` → `-italian`, `Chinese (Simplified)` →
`-chinese-simplified`) e forza l'estensione `.epub`. Vive in `book.output_name()` /
`book.language_slug()` (**condivisi**) e `default_output_path()` lo usa, quindi CLI,
banda 1 e wizard mostrano lo **stesso** nome.

Se il file risultante esiste già l'app **chiede conferma**: `TranslateWizard.accept()`
(dentro il wizard, così «No» lascia aperti i campi) e
`MainWindow._confirm_output_path()` come rete di sicurezza per gli altri chiamanti.
Se il percorso coincide con il **libro originale** compare un avviso specifico con
default **No**. Prima di questa regola il nome di default del wizard era il percorso
dell'originale: premere Fine lo **sovrascriveva**.

**Guida**: `docs/site/` (MkDocs Material + i18n, 5 lingue) è pubblicata su
GitHub Pages da `.github/workflows/docs.yml`.

> Nota: `exporter.py` ed `extract.py` sono **condivisi** (inlineati nel repo
> gemello). Le funzioni aggiunte (export JSON/CSV/DOCX/PDF, write-back
> testi/tabelle/immagini) vanno rispecchiate con
> `tools/sync_from_desktop.py` nel repo engine.

## Release e packaging (0.10.0)

- **Versione app ≠ versione motore**: `APP_VERSION` in
  `noesis_ebook_translator/__init__.py` è la versione della release (tag
  `v0.10.0`); la tupla `version = (2, 4, 2)` resta quella del motore verbatim e
  guida migrazioni/cache/User-Agent. Non allineare l'una all'altra.
- **PyInstaller `--onedir`** con `packaging/app.spec` (committato; `.gitignore`
  ha la negazione `!packaging/*.spec`). Non tornare a `--onefile`: QtWebEngine
  ha bisogno di `_internal/` accanto all'eseguibile e la firma macOS futura non
  sopravvive al onefile.
- `packaging/` contiene installer NSIS adattato a onedir, DMG macOS
  (`.app` + symlink Applications + firma ad-hoc), `nfpm` deb/rpm, desktop entry,
  metainfo AppStream e AppRun/build AppImage.
- `.github/workflows/release.yml` costruisce i 4 runner, esegue
  `--self-test`/`--self-test-reader` sugli artefatti, genera `SHA256SUMS` e crea
  una **draft release**. Per la 0.10.0 l'unico tag ammesso è `v$APP_VERSION`
  (nessuna release candidate); `workflow_dispatch` non pubblica mai.
- `docs/RELEASE.md` è la checklist di go/no-go (matrice manuale Windows/macOS/
  Linux, limiti della build non firmata). `THIRD_PARTY_NOTICES.md` e `LICENSES/`
  sono inclusi nei pacchetti.
- `requirements-release.txt` pinna le versioni usate dalla release; gli asset
  icona sono generati una tantum e committati (`assets/noesis-ebook-translator.*`).

## File da NON toccare senza motivo

- `main.py`, `noesis_ebook_translator/**`, `calibre/**` — codice dell'app e
  motore verbatim. Le modifiche al motore devono passare da
  `tools/import_core_from_fork.py` (che produce copie identiche al fork).
- `.venv/` — ambiente virtuale locale.

## Lettore (GUI) e harness

- `noesis_ebook_translator/reader/` — lettore: `document.py`, `lite_backend.py`
  (QTextBrowser), `webengine_backend.py` (foliate-js in QWebEngineView),
  `scheme.py` (scheme `app://`), `widget.py`, `session.py`, `panels.py`.
- `reader_web/` — bundle foliate-js **vendorizzato** (MIT). `reader.html` è la
  nostra pagina (UI demo di foliate con chrome nascosto + bridge); `noesis_bridge.js`
  espone `window.api` e inoltra gli eventi; il libro si apre via `?url=` su
  `app://`. NON è un submodule: aggiornalo a mano e annota il commit in
  `reader_web/README.md`.
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
