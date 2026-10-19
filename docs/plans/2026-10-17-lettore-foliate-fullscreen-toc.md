# Lettore "reader-first" nella scheda Lettura: viewport intero, TOC a richiesta, toolbar del lettore, schermo intero

- **Richiesta** (verbatim): «nella tab "Lettura" vorrei fare in modo di implementare un vero lettore basato su foliate invece che una piccola finestra per il lettore affiancata da una finestra per il toc. questo lettore dovrebbe andare a richiesta anche a full screen e incoprporare una vera toolbar + finestra del toc visuisibile a richiesta»
- **Obiettivo**: nella scheda Lettura il viewport foliate occupa tutta l'area, i controlli di lettura stanno in una barra dentro il lettore, il TOC compare a richiesta e si legge a schermo intero senza barra a nastro.
- **Criteri di successo**:
  1. aprendo la scheda Lettura il pane TOC è nascosto e il viewport foliate occupa tutta l'area;
  2. un comando (nastro **e** barra del lettore) mostra/nasconde il TOC; il TOC resta funzionante (click, espansioni, checkbox in modalità `select`, `selected_files()`);
  3. la barra del lettore espone: TOC, capitolo precedente/successivo, paginato/scorrimento, due pagine, zoom −/+, schermo intero; tema/font/interlinea/ricerca restano nel nastro;
  4. F11 o il pulsante della barra mettono la finestra a schermo intero e, **se la tab corrente è il lettore**, nascondono la barra a nastro; F11/Esc ripristinano la visibilità *precedente*;
  5. nessuna regressione col backend lite: `python -m unittest discover -s tests -v` verde.
- **Non-obiettivi**:
  - **non** riusare l'interfaccia demo di foliate (`reader_web/foliate-js/reader.js`: `#header-bar`, `#nav-bar`, `#side-bar`) come chrome — decisione motivata, non omissione (vedi *Alternative*);
  - **non** spostare tema/ricerca/font/interlinea nella barra del lettore (duplicherebbe lo stato del nastro: cfr. Rilievi 1-GLM, 5-Luna);
  - **non** persistere la visibilità del TOC in `appconfig` (stato effimero);
  - **non** toccare motore condiviso, bundle `reader_web/`, annotazioni, gesti/touch, auto-hide della barra al movimento del mouse;
  - **non** correggere bug preesistenti (vedi *Domande aperte*).

## Vincoli dal repository

- Il lettore è **desktop-only**: `noesis_ebook_translator/reader/**` e `reader_web/**` non sono nel sync del repo engine (`AGENTS.md`, sezione *Lettore (GUI) e harness*). Nessuna risincronizzazione richiesta.
- I test girano **headless** con `NOESIS_READER_BACKEND=lite` (`tests/__init__.py`); il backend full gira solo in **sottoprocesso** (`tests/test_reader_backends.py:39-68`) e in CI può mancare.
- i18n a **5 cataloghi** con test di parità delle chiavi (`noesis_ebook_translator/i18n.py:1-7`); `T()` fa fallback su `en`.
- F11 esiste già: `main.py:336-337` → `MainWindow.toggle_fullscreen` (`main.py:273-279`), con test di round-trip (`tests/test_workflow_bar.py:209-223`).
- Il TOC Qt è un widget con API proprie (`reader/widget.py:291-328`) e la sua modalità è pilotata dal nastro (`main.py:785-790`).
- Nessuna icona "fullscreen" in `assets/icons/` (48 nomi Fluent Emoji, `tools/build_icons.py:33-83`: verificato, Fluent non ha un glifo *maximize/fullscreen*); la barra del lettore è oggi **testuale** (`reader/widget.py:90-91`).
- `docs/site/` non documenta il layout del lettore: aggiornamento = `README.md:54-73` + `CHANGELOG.md`.

## Stato attuale

- `main.py:297-304`: `ReaderWidget(session=None, backend_mode=...)`; segnali collegati: `statusMessage`, `parallelChanged`, `flowChanged`, `spreadChanged`.
- `main.py:777-778`: sezione **Lettura** del nastro → `tabs.setCurrentWidget(self.reader)`; `main.py:316` la barra delle tab è nascosta.
- `main.py:872-873`: unico punto che mostra/nasconde il TOC, manipolando `self.reader.toc` dall'esterno.
- `reader/widget.py:82-124`: root = barra mini (`prev`, `next`, `cmb_flow`, `btn_spread`) + `QSplitter[TOC | views]`; il TOC ha `setMinimumWidth(200)` ed è **sempre visibile**.
- `reader/widget.py:110-124`: il `views` splitter contiene `backend` e `second` (vista parallela, `second.hide()` a `widget.py:60`); `set_parallel` a `widget.py:385-397`.
- `reader/widget.py:56-60`: **due** backend creati sempre, anche col lite.
- `reader/widget.py:197-220`: `_mark_current` evidenzia e fa `scrollToItem` sul TOC.
- `reader/widget.py:222-240`: `set_flow`/`set_spread` sono già protetti con `hasattr` (il lite non li implementa); `lite_backend.py:111` implementa `set_zoom`, `webengine_backend.py:265-267` pure.
- `ui/workflow_bar.py:522-564`: il nastro della sezione Lettura contiene pompa/tema/font/interlinea/giustifica/sillabazione/zoom/ricerca/confronto/note/stampa; `ui/workflow_bar.py:549-551` lo zoom agisce **solo** su `window.reader.backend`.
- `reader/webengine_backend.py:1-10`: il chrome Qt resta in Python per scelta dichiarata; `reader_web/reader.html:309` nasconde il chrome di foliate con una riga CSS.
- `reader_web/README.md`: `foliate-js/` è upstream **non modificato** (commit `78914ae`), `reader.html` è la *nostra* copia.

## Approccio proposto

Il motore di lettura è già quello vero (foliate-js in `QWebEngineView`): manca la **disposizione**. Oggi il TOC è un pannello fisso da 200 px e i controlli di lettura stanno nel nastro; a schermo intero il nastro sparisce e con lui i controlli.

1. **TOC a richiesta**, senza nuova infrastruttura: il pane resta nel `QSplitter` esistente ma **parte nascosto**, con un toggle esposto sia dal nastro (pulsante già esistente, reso *checkable*) sia dalla barra del lettore. Nessun legame con la modalità `select` del nastro: la sezione Traduzione mostra `_translate_tab`, non il lettore, quindi "riapri il TOC in modalità select" non avrebbe alcun effetto visibile.
2. **Barra del lettore** = la mini barra esistente, con l'aggiunta di TOC, zoom ± e schermo intero. Tema/ricerca/font restano nel nastro: sono impostazioni, non controlli di lettura, e duplicarle imporrebbe una sincronizzazione a due vie (la classe di bug segnalata da entrambi i critici).
3. **Zoom corretto**: lo zoom passa da un metodo unico su `ReaderWidget` che agisce su **entrambi** i backend; oggi il pulsante del nastro muove solo la vista principale e disallinea il confronto.
4. **Schermo intero**: un solo percorso in `MainWindow`, che ricorda la visibilità *precedente* del nastro e la ripristina all'uscita; Esc attivo solo durante il fullscreen.

Firme (l'unica parte che è il punto del piano):

```
# reader/widget.py
tocVisibilityChanged = pyqtSignal(bool)
fullscreenRequested  = pyqtSignal()
ReaderWidget.set_toc_visible(visible: bool) -> None
ReaderWidget.toc_visible() -> bool
ReaderWidget.toggle_toc() -> None
ReaderWidget.set_zoom(delta: int) -> None      # agisce su backend e second

# main.py
MainWindow.toggle_fullscreen() -> None         # firma invariata
```

## Passi

1. **TOC a richiesta** — file: `noesis_ebook_translator/reader/widget.py`, `main.py`, `noesis_ebook_translator/ui/workflow_bar.py`
   - TOC nascosto alla costruzione; `set_toc_visible`/`toc_visible`/`toggle_toc` + segnale `tocVisibilityChanged`; `btn_toc` reso *checkable* (`workflow_bar.py:524`) e sincronizzato dal segnale con `blockSignals`; `on_toggle_toc` delega al widget invece di toccare `self.reader.toc`.
   - Verifica: assert in `tests/test_features.py` (TOC nascosto dopo l'apertura, visibile dopo il toggle, larghezza riacquistata dopo `processEvents`); `tests/test_gui.py::test_reader_chapter_selection` e `tests/test_features.py::test_toc_modes_by_category` restano verdi.
   - Rischio: basso (nessuna logica di navigazione toccata). Stima **S**.
2. **Zoom unificato sui due viewport** — file: `noesis_ebook_translator/reader/widget.py`, `noesis_ebook_translator/ui/workflow_bar.py:549-551`
   - `ReaderWidget.set_zoom(delta)` che chiama `set_zoom` su `backend` e `second` (protetto, il lite lo implementa a `lite_backend.py:111`); i pulsanti del nastro usano il nuovo metodo.
   - Verifica: test che `reader.backend._zoom == reader.second._zoom == 1` dopo `set_zoom(1)` col backend lite.
   - Rischio: basso; corregge una divergenza già esistente tra vista principale e parallela. Stima **S**.
3. **Barra del lettore** — file: `noesis_ebook_translator/reader/widget.py:82-108`
   - Alla mini barra esistente si aggiungono: pulsante TOC (checkable, collegato a `toggle_toc`), zoom −/+, pulsante schermo intero che emette `fullscreenRequested`. Restano `prev`/`next`/`cmb_flow`/`btn_spread`. Nessun widget di *impostazione* viene duplicato.
   - Verifica: `tests/test_features.py` — i pulsanti esistono e agiscono (TOC commuta `toc_visible()`, zoom muove entrambi i backend).
   - Rischio: basso. Stima **S**.
4. **Schermo intero a richiesta** — file: `main.py:273-279, 336-337`, `noesis_ebook_translator/reader/widget.py`
   - `toggle_fullscreen()`: all'ingresso salva `self.workflow.isVisible()` e, se `tabs.currentWidget() is self.reader`, nasconde il nastro; `showFullScreen()`. All'uscita `showNormal()`/`showMaximized()` e **ripristino dello stato salvato** (mai dedotto dalla tab corrente: il cambio di tab durante il fullscreen non deve corrompere lo stato). `Esc` come `QShortcut` abilitata solo durante il fullscreen. `fullscreenRequested` della barra è collegato allo stesso metodo.
   - Verifica: estendere `tests/test_workflow_bar.py::test_fullscreen_toggle_round_trip` (nastro nascosto all'ingresso con la tab lettore attiva, ripristinato all'uscita, Esc esce, stato invariato se il fullscreen parte da un'altra tab).
   - Rischio: medio — Qt offscreen non ha un window manager: si asserisce lo stato Qt e la visibilità, non la resa; verifica manuale sul desktop. Stima **S/M**.
5. **i18n e documentazione** — file: `noesis_ebook_translator/locales/{it,en,fr,es,de}.json`, `README.md:54-73`, `CHANGELOG.md`
   - Chiavi nuove per i due pulsanti nuovi (TOC/schermo intero) nei **5** cataloghi; parità garantita da `tests/test_i18n.py`. README: la sezione *Lettore EPUB integrato* descrive la nuova disposizione. CHANGELOG: voce in `[Unreleased] → Added`.
   - Verifica: `python -m unittest tests.test_i18n -v`.
   - Rischio: basso. Stima **S**.

**Totale: M**

## Alternative considerate (e perché scartate)

- **Riusare il chrome di foliate** (`reader_web/reader.html:309`, togliere `#side-bar`/`#header-bar`/`#nav-bar` dalla regola di hide): è la leva più corta in assoluto — sidebar TOC già cablata (`foliate-js/reader.js:76-83`), slider di progresso, espansioni, voce corrente in grassetto — ma: (a) etichette **hardcoded in inglese** in un'app a 5 lingue; (b) funziona **solo** col backend full, quindi il TOC Qt resterebbe comunque per il lite e per la modalità `select` → **due TOC con ruoli diversi** nella stessa schermata; (c) la barra vivrebbe dentro la pagina, fuori dal tema Qt e dalle icone dell'app; (d) `reader.html` è già una copia nostra di un bundle upstream *unmodified*, e allargare la superficie di deriva rende più costoso l'aggiornamento a `78914ae`+. Resta la scelta più economica se un domani il progetto accetta un chrome in inglese e abbandona il lite.
- **TOC come overlay semitrasparente sopra il viewport** (stile side-bar di foliate): più bello a schermo intero, ma richiede un widget figlio frameless posizionato sulla view, gestione del resize e convivenza con lo splitter del confronto; rimandata.
- **Eliminare il TOC Qt** e usare solo quello di foliate: rompe `selected_files()` (`reader/widget.py:313`, usata da `tests/test_gui.py:61,72`) e il backend lite.
- **Barra del lettore completa** (tema, ricerca, font dentro il lettore): scartata — duplica controlli del nastro (`ui/workflow_bar.py:522-564`), impone sync a due vie (anche sul percorso `_apply_settings_values`, `main.py:739-763`) e una query di ricerca condivisa tra due campi.

## Riconciliazione del Concilio

| # | rilievo | chi | severità | decisione | motivo |
|---|---------|-----|----------|-----------|--------|
| 1 | Il passo "toolbar completa" reinventa controlli già nel nastro e introduce sync a due vie | GLM | BLOCKER | **accettato** → barra = mini barra + TOC + zoom ± + fullscreen; tema/ricerca/font restano nel nastro | `ui/workflow_bar.py:522-564` e `reader/widget.py:89-108` coprono già tutto; un secondo set di controlli è puro costo e una classe di bug (doppio stato) |
| 2 | La modalità `select` non è il flusso produttivo: la sezione Traduzione mostra `_translate_tab`, il TOC del lettore non è visibile lì | Luna | MAJOR | **accettato** → niente riapertura automatica legata alla sezione; `set_toc_mode` resta intatto | verifica mia: `main.py:772-790`; `selected_files()` è usata solo da test — il flusso reale è il wizard (`ui/translate_wizard.py`) |
| 3 | I campi UI proposti in `ReaderReport`: classe sbagliata (`FeatureReport`), `.ok` non li copre, e il lite non esercita foliate | Luna | MAJOR | **accettato** → nessuna estensione dell'harness; assert nei file unittest esistenti + verifica manuale del full | i test coprono già TOC (`tests/test_features.py:148-209`) e F11 (`tests/test_workflow_bar.py:209-223`); l'harness CLI resta com'è |
| 4 | Una ricerca dentro il lettore non può riusare `on_find_run` (legge `self.edt_find`) | Luna | MAJOR | **accettato** → nessun campo di ricerca nella barra; resta nel nastro | rende il rilievo non applicabile e conferma il taglio del Rilievo 1 |
| 5 | Lo zoom agisce solo su `reader.backend`: il confronto si disallinea | Luna | MAJOR | **accettato** → passo 2, `ReaderWidget.set_zoom(delta)` su entrambi i backend | corregge anche il comportamento attuale del pulsante nel nastro (`ui/workflow_bar.py:549-551`) |
| 6 | `blockSignals` non definisce la sincronizzazione dei controlli duplicati (percorso impostazioni) | Luna | MAJOR | **accettato** → eliminata la duplicazione: tema/font/interlinea restano a un solo controllo | `_apply_settings_values` (`main.py:739-763`) resta l'unico percorso; nessun nuovo ciclo |
| 7 | Manca Esc e il ripristino del nastro non deve dedursi dalla tab corrente | Luna | MAJOR | **accettato** → `Esc` attivo solo in fullscreen; visibilità del nastro salvata all'ingresso e ripristinata | stato esplicito invece che dedotto |
| 8 | Il chrome di foliate è già scritto e nascosto da 1 riga: va valutato, non bollato come non-obiettivo | GLM | MAJOR | **accettato come analisi, rifiutato come approccio** | accettata l'analisi (ora in *Alternative* con costo/beneficio); rifiutato per i18n hardcoded in inglese, due TOC con ruoli diversi (select + lite), chrome dentro la pagina fuori dal tema Qt e deriva dal bundle upstream `unmodified` |
| 9 | Persistenza `toc_visible` in `appconfig` = YAGNI | GLM | MAJOR | **accettato** → nessun nuovo campo di configurazione | stato effimero di lettura |
| 10 | Estendere due harness per 3 flag quando gli unittest bastano | GLM | MINOR | **accettato** → vedi Rilievo 3 | converge con Luna |
| 11 | Superficie API ridondante (segnale + getter) | GLM | MINOR | **parzialmente accettato** → 3 metodi + 1 segnale, nessun getter di comodo; `toc_visible()` resta perché serve ai test | il getter è l'unico modo pulito di asserire lo stato |
| 12 | Il criterio 3 con 9 controlli eccede la richiesta | GLM | MINOR | **accettato** → criterio ridotto a 6 gruppi | vedi Rilievo 1 |
| 13 | Ordine: TOC e fullscreen sono verificabili subito, l'harness non deve precedere il codice | GLM | MINOR | **accettato** → test per passo, nessun passo-harness; ordine TOC → zoom → barra → fullscreen → i18n | ogni passo è verificabile da solo |
| 14 | Manca un test hide → naviga → riapri; `scrollToItem` su tree nascosto non è verificato | Luna | MINOR | **accettato** → il passo 1 include il giro completo; il posizionamento visibile della voce corrente resta verifica **manuale** | `scrollToItem` su widget nascosto non è asseribile in offscreen |
| 15 | I criteri non distinguono full/lite e non coprono TOC vuoto o file non-EPUB | Luna | MINOR | **parzialmente accettato** → caso "libro senza voci TOC" nei test; full e non-EPUB restano fuori | `set_flow/set_spread` sono già protetti (`widget.py:222-240`); il percorso non-EPUB esiste solo nel full (`widget.py:128-138`) e non cambia |
| 16 | `QSplitter`: dimensioni dopo hide/show non verificate | Luna | NON VERIFICATO | **accettato** → assert sulla larghezza del pane dopo `processEvents` | unico modo di coprirlo headless |
| 17 | Fullscreen offscreen ≠ desktop; stime S/M non ricavabili dal codice | Luna | NON VERIFICATO | **accettato** → verifica manuale in *Test e verifica*; stime dichiarate come stime | nessuna pretesa di misura |

Nessun disaccordo strutturale fra i critici: le divergenze (auto-riapertura del TOC, portata della barra) sono state decise con i fatti del codice, senza secondo giro.

## Verdetto dei critici

- **Luna**: `APPROVE_WITH_CHANGES` — «l'impostazione è valida, ma selezione capitoli, harness e controlli duplicati vanno chiariti prima di considerare la bozza verificabile» (0 BLOCKER, 6 MAJOR, 2 MINOR).
- **GLM**: `APPROVE_WITH_CHANGES` — «l'obiettivo è giusto e il punto di innesto è corretto, ma il passo 3 rifà controlli che il nastro ha già … la versione minima è ~40-50 righe contro le ~300 della bozza» (1 BLOCKER, 2 MAJOR, 4 MINOR).

## Rischi e mitigazioni

1. **Doppio stato dei controlli** (il rischio che ha prodotto il BLOCKER): mitigato eliminando la duplicazione — un solo controllo per ogni impostazione, la barra del lettore porta solo comandi di lettura senza stato persistente.
2. **Fullscreen nei test**: Qt offscreen non ha window manager. Mitigazione: si asseriscono stato Qt (`isFullScreen`) e visibilità del nastro, più verifica manuale sul desktop.
3. **TOC nascosto e usabilità della selezione capitoli**: il TOC non perde API né modalità; il test `test_reader_chapter_selection` resta verde a pannello nascosto. Verifica manuale del giro nascondi → naviga → riapri.
4. **Deriva dal bundle foliate-js**: il piano non tocca `reader_web/foliate-js/**` né `reader.html`; la decisione di restare sul chrome Qt va annotata in `reader_web/README.md` (già coerente, nessuna modifica necessaria).

## Test e verifica

- `python -m unittest discover -s tests -v` (lite, headless) — deve restare verde a ogni passo.
- Test mirati: `python -m unittest tests.test_features tests.test_workflow_bar tests.test_gui tests.test_i18n -v`.
- Backend full (dove WebEngine è disponibile): `python tools/reader_harness.py --mode full --wait 15 <libro.epub>`.
- Caso "libro senza voci TOC": apertura + toggle TOC senza eccezioni (il caso `selected_files()` vuoto è già coperto da `tests/test_gui.py:61`).
- **Verifica manuale sul desktop** (non sostituibile): F11 e pulsante a schermo intero, uscita con F11 ed Esc, ripristino del nastro, TOC su richiesta durante la lettura, zoom ± con il confronto aperto, libro senza TOC, file non-EPUB (MOBI/PDF) col backend full.

## Criteri di accettazione

1. Aprendo un libro nella scheda Lettura: pane TOC nascosto, viewport foliate a tutta area.
2. Toggle TOC dal nastro e dalla barra del lettore: si mostrano/nascondono e restano sincronizzati; il TOC naviga e `selected_files()` funziona con il pane nascosto.
3. Zoom −/+ muove **entrambi** i viewport (principale e confronto), con lite e con full.
4. F11 (o il pulsante) da scheda Lettura: finestra a schermo intero, nastro nascosto; F11/Esc: nastro ripristinato allo stato precedente. Da un'altra tab il fullscreen non nasconde il nastro.
5. Suite unittest verde; full verificato a mano come sopra.

## Domande aperte / condizioni per l'assenso

1. **Tema e ricerca in schermo intero**: con la versione minima, a schermo intero il nastro è nascosto e quindi tema/ricerca non sono raggiungibili finché non si esce. Se vuoi cercare *senza* uscire dal fullscreen, va aggiunto alla barra un campo di ricerca con una query condivisa (`_find_query` in `MainWindow`, ≈15 righe + 1 test): è l'unico pezzo che avevo previsto e che ho tagliato su richiesta dei critici. Serve il tuo OK per lasciarlo fuori.
2. **Aspetto "vero lettore"**: il piano lascia il TOC come pannello laterale che compare/scompare. Se intendi un TOC **a scomparsa sopra la pagina** (overlay stile foliate), è l'*Alternativa 2*: +1 widget frameless, +gestione resize. Dimmi se la vuoi nella prima versione.
3. **Bug preesistenti fuori scope** (nessuna azione prevista): `help.py:19` elenca la sezione `reader`, ma `docs/site/docs/<lang>/reader.md` **non esiste** (link di aiuto potenzialmente rotto); il caso "TOC vuoto" nel backend lite (`lite_backend.py:56-58`) non è difeso.
