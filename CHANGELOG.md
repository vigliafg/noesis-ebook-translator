# Changelog

Le modifiche rilevanti dell'app. Il formato segue
[Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il versionamento è
`v<major>.<minor>.<patch>` (definito in `noesis_ebook_translator/__init__.py`).

Il changelog parte da qui: le versioni precedenti non avevano un file dedicato,
la storia completa è nei commit (`git log`).

## [Unreleased]

## [0.10.0] - 2026-10-26

**Prima release pubblica.** Installabili per Windows x64 (installer), macOS
Apple Silicon e Intel (DMG) e Linux x86_64 (deb, rpm, AppImage). Il pacchetto
include il lettore completo (QtWebEngine) e l'export PDF/DOCX.

- La versione dell'**app** (`0.10.0`) è ora separata da quella del motore
  verbatim (`v2.4.2`): il motore resta invariato e le migrazioni della
  configurazione continuano a usare la sua versione.
- Dati utente (libreria, capitoli, cache, log) spostati nella directory dati
  del sistema (macOS `Application Support`, Windows `%LOCALAPPDATA%`, Linux
  `$XDG_DATA_HOME`), con migrazione una-tantum e non distruttiva dal vecchio
  percorso di configurazione.
- Build PyInstaller `--onedir` con spec versionato; installer Windows NSIS,
  DMG macOS, deb/rpm via nfpm e AppImage.
- `--self-test` e `--self-test-reader`: verificano le risorse incluse e aprono
  davvero un EPUB col backend full, con report JSON (i bundle `--windowed` non
  hanno stdout garantito).
- Log diagnostico in `logs/app.log` e `THIRD_PARTY_NOTICES` inclusi nei
  pacchetti.
- Le release sono **non firmate**: macOS richiede click destro → Apri al primo
  avvio; Windows può mostrare SmartScreen.

### Changed

- **Traduzione in parallelo di default (8 richieste)**: nel test di velocità lo
  stesso capitolo passa da **856 s** in sequenziale a **63 s** a concorrenza 20
  (8 è il default prudente). "Sequenziale" resta un click per i motori con rate
  limit severi.
- **Batching online più veloce e più robusto**: i batch vengono inviati **in
  parallelo** (fino a `concurrency_limit`) invece che uno alla volta — nel test di
  velocità 541 s → **176-222 s** — e la dimensione è configurabile (default 20) dal
  wizard e dalle Impostazioni. La stima dei costi divide per la dimensione scelta.
- **La concorrenza nel wizard arriva a 20** (era 1-8): il motore ora la rispetta
  fino a 32 thread, quindi il valore scelto non è più finto.
- **La lista dei motori mostra solo ciò che è pronto all'uso**: nelle liste di
  scelta (gruppo *Motore* del ribbon, wizard di traduzione, giudice di qualità) i
  motori **non-LLM** restano sempre presenti, mentre un **LLM** compare **solo se
  configurato** — i motori del plugin (Gemini, ChatGPT, Claude, ChatGPT Azure,
  DeepSeek, OpenRouter) quando *Impostazioni → Traduzione* ha la loro chiave, i
  provider curati quando il loro slot è abilitato in *Impostazioni → Provider*.
  Prima i sei LLM del plugin erano sempre elencati e senza chiave davano errore
  solo al momento della traduzione; le pagine di configurazione mostrano comunque
  l'elenco completo, e la lista completa resta disponibile per l'edizione CLI
  (`engine_names()`). Corretto anche un difetto collegato: un provider tolto dalla
  lista degli slot lasciava la sua chiave dietro di sé, e restava quindi
  selezionabile.

### Added

- **Glossario in Impostazioni → Traduzione**: si sceglie un file con i termini
  (termine e traduzione su righe consecutive, voci separate da una riga vuota) e
  il motore li sostituisce con segnaposto prima della richiesta, ripristinandoli
  dopo. Funziona anche col **batching**, che prima lo ignorava del tutto.
- **Lettore a tutta pagina, con indice a richiesta e schermo intero**: nella
  scheda *Lettura* il viewport di foliate-js occupa tutto lo spazio e il TOC —
  prima un pannello fisso da 200 px — **parte nascosto** e compare a richiesta
  (pulsante nella toolbar del lettore o nel nastro, sempre sincronizzati; nascosto
  continua a funzionare per navigazione e selezione capitoli). La **toolbar del
  lettore** raccoglie i comandi d'uso mentre si legge — indice, precedente/
  successivo, pagina/scorrimento, singola/doppia, **zoom −/+**, **schermo
  intero** — mentre tema/fonte/interlinea/ricerca restano nel nastro, così ogni
  impostazione ha un solo controllo da tenere sincronizzato. **F11** e il pulsante
  *Schermo intero* passano a tutto schermo e, dalla scheda *Lettura*, nascondono
  anche la barra a nastro; si esce con **F11** o **Esc**, ripristinando la barra
  com'era (anche se nel frattempo si è cambiata scheda). Lo zoom ora muove
  **entrambi** i viewport: prima il pulsante agiva solo sulla vista principale e
  il confronto si disallineava.
- **Provider multipli (fino a 4)**: si possono tenere configurati
  contemporaneamente fino a 4 provider OpenAI-compatibili, ognuno con la
  **propria chiave API e il proprio modello**, e scegliere quale usare a ogni
  traduzione. Il provider si sceglie in **Impostazioni → Provider** e nei wizard
  di primo avvio e di traduzione.
- **Rosa curata di 17 provider** — OpenCode, OpenCode Go, OpenRouter, Groq,
  Mistral, xAI (Grok), Together, Fireworks, DeepInfra, Cerebras, SambaNova,
  NVIDIA NIM, Moonshot (Kimi), Z.AI (GLM), Alibaba (DashScope), Novita,
  HuggingFace — più un **endpoint personalizzato** (Ollama, LM Studio, vLLM,
  LiteLLM…).
- **Liste modelli live** dall'endpoint `/models` del provider, con snapshot
  incluso per l'uso offline (`noesis_ebook_translator/data/providers.json`),
  pulsante *Aggiorna modelli* per singolo provider, **rigenerazione di tutte le
  liste** dalle Impostazioni e dal wizard di primo avvio, e aggiornamento
  automatico dopo 24 ore.
- **Test automatico del modello**: una traduzione breve verifica il modello
  scelto e l'esito compare inline (`✓ Modello OK · 1,2s` oppure il motivo);
  l'ultimo esito resta visibile nel ribbon come **badge ✓/✗**.
- **Supporto alla Responses API** di OpenAI per i modelli dei gateway (OpenCode,
  OpenCode Go) che rifiutano `chat/completions` — p.es. `muse-spark-1.3-contributor`,
  `gpt-6-luna`, `grok-4.7`: lo snapshot registra il protocollo di ogni modello e
  il motore instrada di conseguenza.
- **Ripresa a prova di interruzione (blackout)**: ogni segmento tradotto è
  committato subito e registrato per contenuto (`noesis_resume`, per motore +
  modello + lingua), quindi un crash o una mancanza di corrente non fanno perdere
  nulla: rilanciando la traduzione si riparte dai soli segmenti mancanti, anche
  cambiando la selezione dei capitoli. L'EPUB finale è scritto in modo atomico
  (`*.part` + `os.replace`) e la GUI segnala «Ripresa: N/M segmenti». La cache
  vive sotto la directory dati dell'app (`translator-cache/cache`), non in `/tmp`,
  così sopravvive al riavvio.
- **L'app sa quando una traduzione è stata interrotta**: ogni run scrive un
  marker (`running` / `finished` / `cancelled` / `dismissed`) nella cache. Un
  crash o un blackout lascia `running`, quindi all'apertura del libro compare
  «Traduzione interrotta: N/M segmenti — Riprendere?» e il Sì riparte con lo
  **stesso** motore, modello, lingua e selezione di capitoli. «No» non cancella
  nulla (rilanciare a mano riprende lo stesso) e non richiede più per quel run.
- `tools/fetch_provider_catalog.py` per rigenerare lo snapshot incluso nel
  bundle (utile solo per lo sviluppo: l'app si aggiorna dalla UI). Ora lo
  snapshot include anche i **prezzi** (USD per 1M token) e `provider_catalog.price()`.
- **Stima di token, costo e durata prima di tradurre** (pagina *Costi e
  durata* del wizard): token contati con **tiktoken** sugli stessi segmenti che
  il motore invierà (prompt di sistema incluso), prezzo dal catalogo providers,
  durata come intervallo (calibrata sulle traduzioni precedenti dopo il primo
  run), dettaglio per capitolo e segmenti già in cache esclusi dal conto. Gli
  encoder BPE sono inclusi nel pacchetto (`data/tiktoken`) per funzionare
  offline, con fallback euristico se non disponibili.
- **Analisi del testo e prompt di stile** (pagina *Analisi del testo* del
  wizard): il modello legge un campione del libro (~6k caratteri) e propone
  genere, registro, tono, pubblico ed epoca; da lì nasce un'**aggiunta al system
  prompt** del motore — modificabile, applicabile o saltabile — che adatta lo
  stile senza mai perdere le regole di integrità (niente riassunti o omissioni,
  numeri/nomi/markup/segnaposto intatti). Lo stile entra nell'identità della
  cache: cambiarlo ritraduce, tornare indietro riprende il lavoro, e la ripresa
  dopo un blackout riusa lo stile del run senza rifare l'analisi.
- **Richieste in parallelo (1–8)** nel wizard: quando «sequenziale» è
  deselezionato, la concorrenza del motore è quella scelta e la stima della
  durata la riflette.

### Changed

- `appconfig.engine_names()` elenca i motori del plugin più **solo i provider
  abilitati**, così ribbon e wizard restano corti.
- La sonda del modello è **thread-safe**: costruisce una sottoclasse transitoria
  invece di mutare la configurazione condivisa del motore condiviso, e forza
  `stream=False` (una sola richiesta breve).
- Documentazione: nuova pagina *Providers* (5 lingue) e README aggiornato.

### Fixed

- **Un reply di batch incompleto non ferma più il libro**: se il modello salta
  degli ID, si ritentano **solo i segmenti mancanti** (non l'intero batch) e un
  JSON troncato viene riparato scartando la sola coppia tagliata — mai una
  traduzione a metà. Un segmento che resta mancante viene segnato come errore,
  non fa fallire l'intera traduzione.
- **Retry con jitter e `Retry-After`**: il backoff non è più fisso (5, 10, 15 s),
  rispetta l'attesa chiesta dal provider e non fa ritentare in lockstep N worker.
- **Il giudice di qualità legge le risposte in streaming**: con `stream=True`
  riceveva un generatore e lo serializzava, dando 0 a ogni campione. Ora unisce i
  chunk e, dove il motore lo supporta, spegne il reasoning.
- **La concorrenza scelta non veniva rispettata oltre ~8**: `Handler` esegue ogni
  chiamata con `run_in_executor(None, …)`, cioè sul *default executor* del loop,
  che CPython dimensiona `min(32, cpu+4)` (8 su una macchina a 4 CPU). I worker in
  più restavano in coda: nel test di velocità il parallelismo massimo osservato era
  **8** anche a concorrenza 20. Ora l'executor è dimensionato su
  `concurrency_limit` (tetto 32): 112 s → **77 s** sullo stesso capitolo.
- **`request_interval` annullava il parallelismo**: il default della famiglia
  OpenAI (20 s fra due richieste) non veniva toccato, quindi la modalità parallela
  impiegava 745 s contro i 112 s possibili. In parallelo l'app lo azzera; in
  sequenziale resta il valore del motore.
- **Il batching online non ha mai funzionato con lo streaming attivo**:
  `translate_batch` invia un corpo non-stream ma leggeva la risposta con
  `get_result`, che con `stream=True` (il default) prende il percorso streaming e
  fallisce con *«'str' object has no attribute 'readline'»*. Ora la risposta del
  batch viene letta come JSON normale.
- **La stima di durata era ottimistica dopo un run con batching**: `cache.info`
  registrava come `run_engine_calls` i **segmenti** (671) invece delle **richieste**
  (34). Ora conta le chiamate realmente fatte, quindi anche i tentativi ripetuti.
- I modelli che richiedono un protocollo diverso dall'endpoint OpenAI (p.es.
  Claude e Gemini su OpenCode/OpenCode Go) vengono **nascosti** invece di fallire
  a metà traduzione.
- Il wizard di primo avvio non supportava l'**endpoint personalizzato**: ora ha
  il campo URL base e la sonda lo usa.
- **Estrazione e traduzione non perdono più il CSS del libro**: ebooklib
  ricostruiva ogni documento dal proprio template e non ricopiava l'`<head>`
  letto, quindi l'EPUB risultante conservava i file `.css` ma **nessun**
  `<link rel="stylesheet">` (formattazione persa). L'intestazione originale
  (link, meta, titolo) viene ora scritta com'è.
- **Un capitolo con l'ancora dentro un contenitore non viene più cancellato**:
  in libri come Rosen l'indice punta all'`<h1>` dentro una `<section>` e
  l'isolamento per ancore eliminava il contenitore (e il capitolo). Ora restano
  gli antenati dell'ancora selezionata.
- **Le liste conservano la struttura**: un `<ul>`/`<ol>` con soli `<li>` era
  considerato inline-only e tradotto come un unico segmento, collassando ogni
  voce (con `class`/`id`) nel genitore; ora l'estrazione scende negli `<li>`.
- Aggiunto `tools/format_fidelity.py` (e `tests/test_format_fidelity.py`):
  confronta CSS, link ai fogli di stile, asset (font/immagini) e struttura
  stilata di due EPUB, per verificare la fedeltà di estrazione e traduzione.
- **L'analisi del testo funziona anche con i motori del plugin** (OpenRouter,
  ChatGPT, DeepSeek, Claude, Gemini…): `make_runner` scriveva `endpoint` vuoto
  nella configurazione della sonda, sovrascrivendo l'endpoint di default del
  motore; la chiamata falliva con `unknown url type` e la pagina ripiegava sul
  prompt generico. Ora l'endpoint di default resta, uno personalizzato vince.
- **OpenRouter non ha più il prompt «traduttore letterario»** hardcoded: su un
  trattato di medicina faceva uscire «colpo» per *stroke* nei segmenti brevi
  (titoli). Eredita il prompt neutro; la specializzazione arriva dall'analisi
  del testo.
- **Temperatura bassa dove serve, non ovunque**: `OpenRouterTranslate` usa
  `temperature = 0.2` (è un gateway generico senza valore tarato; a 1.0 i
  segmenti brevi erano un tiro di dado: lo stesso titolo usciva «Ictus» o
  «Colpo»). Gli altri motori tengono i propri valori (DeepSeek 1.3, Gemini
  0.9). `translate_temperature` resta un override globale **opt-in** (`None`
  di default) e un valore per-motore ha la precedenza.
- **Reasoning spento per la traduzione**: `translate_reasoning` (default `False`)
  chiede ai motori che accettano il campo (`reasoning_supported`, oggi OpenRouter)
  di saltare il ragionamento interno del modello (`{"reasoning": {"enabled":
  false}}`). Nel test di velocità costava **2,5× tempo** e **3,5× costo** per
  qualità uguale o peggiore; un valore per-motore (`reasoning`) ha la precedenza e
  i motori che rifiuterebbero il campo restano intatti. Anche la sonda
  dell'analisi del testo lo spegne.
