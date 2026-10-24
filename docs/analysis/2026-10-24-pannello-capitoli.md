# Analisi: pannello «Capitoli» (banda 2) della vista Traduci

- **Richiesta** (verbatim): «nell'ambiente traduzione ho difficoltà a creare una versione del pannello indice dei capitoli tradotti/da tradurre. analizzate i punti deboli di ciò che fa questo pannello.»
- **Perimetro**: banda 2 «Capitoli» della vista Traduci — elenco del TOC, stati, filtri *Tutti / Da tradurre / Tradotti*, selezione, conteggi, integrazione con run e cache.
- **Non analizzato**: il TOC del lettore, il layout del wizard, il motore di traduzione interno, temi e animazioni; il pannello del lettore è un altro widget.
- **Data e revisione del codice**: 2026-10-24, commit `95672f0` (working tree pulito).

## Sintesi esecutiva

Il pannello è un buon **renderer del TOC in ordine di lettura**, ma non è un indice dello stato del libro: è un **oggetto di progresso del run**. All'apertura non sa nulla della cache; `done` conta anche i segmenti falliti; un cancel lascia le righe `running` e le animazioni accese; `finish(ok=True)` può promuovere a completo un capitolo incompleto; una selezione vuota nel wizard diventa «tutto il libro». La difficoltà di costruire una vista «tradotti / da tradurre» nasce da qui: **manca una sorgente di verità per lo stato per capitolo**, e le due unità (voce TOC vs documento XHTML) non coincidono.

**Bug confermati**: 5 (vedi sotto). **Rischi**: saturazione dei filtri a 20k voci, selezione mista file/ancora, href duplicati. **Nessun codice modificato.**

## Come funziona

### Ciclo di vita

```
apertura libro ──► _show_toc ──► ProgressModel(units)      [niente piano, niente done, niente cache]
avvio run      ──► build_units ──► set_selection ──► worker
worker         ──► on_plan(counts per page) ──► set_plan
worker         ──► DeltaBatch ──► TransferThrottle ──► _on_delta ──► apply ──► refresh
fine/cancel/fail ─► set_finished(ok) ──► finish(ok)
```

- All'apertura: `main.py:434-453` costruisce `ProgressModel(build_units(path))` senza piano, senza `done`, senza cache; su `ChapterError` mostra il motivo.
- All'avvio: `main.py:1479-1489` ricostruisce le unità, crea il modello, applica `set_selection(chapters)` e passa il modello alla vista.
- Piano: `main.py:1521-1527` riceve `on_plan`; `book.py:746-754` conta i segmenti per `page_id` (XHTML), escludendo `toc.ncx`.
- Delta: `main.py:1536-1549` applica il payload, aggiorna la vista e la percentuale globale; il worker coalesce con `DeltaBatch`/`TransferThrottle` (`main.py:86-183`).
- Fine: `main.py:1569-1605` chiama `set_finished(ok=True)`, legge `summary()` e mostra il messaggio. Cancel/fail: `main.py:1657-1681` chiamano `set_finished(ok=False)`.

### Modello (`progress_model.py`)

- **Unità di riga**: `ChapterUnit`, una voce del TOC, con `href`/`file`/`depth`/`kind` (`52-80`). La chiave è `href` o `file` o `#indice` (`73-80`).
- **Unità di progresso**: il **documento XHTML**. `DeltaBatch.add_paragraph` conta per `page` (`159-181`); il piano è per `page_id` (`book.py:746-754`). Due voci sullo stesso file mostrano gli stessi numeri.
- `build_units` (`83-112`) restituisce tutte le voci in ordine di lettura; il parametro `selected` (`106-107`) **filtra** le voci, mentre `set_selection` (`230-244`) le lascia visibili come `excluded`. Due comportamenti diversi per lo stesso concetto.
- `set_plan` (`246-261`) aggiunge in **coda** i documenti fuori TOC con contenuto; `set_units` (`263-272`) azzera `done/errors/cached/last/finished/exported` ma **non** `plan`, `cached_pages` e `selection`.
- `file_state` (`278-291`): errori per primi; `total == 0` → `skipped` se il piano esiste, altrimenti `pending`; `done >= total` → `done`; `done > 0` → `running`.
- `tracked` (`313-330`) collassa i file, tiene solo i selezionati con `total > 0`; `overall` (`332-336`) somma `min(done, total)`; `done_chapters` (`346-349`) richiede `file_state == done`; `running_units` (`342-344`) include `running` ed `error`.
- `apply` (`372-396`) somma i conteggi; `finish` (`398-416`): con `ok=False` non tocca gli stati; con `ok=True` porta a `total` ogni documento selezionato con `done > 0` e nessun errore.

### Vista (`ui/chapter_track.py`)

- Una riga per voce TOC, delegate che costruisce il payload solo per le righe dipinte (`50-55`), barra dentro la riga (`64-65`, `155-171`), conteggio `done/total` (`111-112`).
- Filtri (`208-232`, `287-297`): `all` = tutte le unità; `todo` = `pending/running/error`; `done` = `done`. Gli heading restano solo se un discendente è visibile (`_section_has_visible_child`, `325-336`).
- `refresh` (`363-382`) rifiltra tutte le unità, confronta le chiavi, aggiorna `running`, header e timer. `_rebuild` (`429-440`) ricrea N item quando il set visibile cambia.

### Test

`tests/test_translate_view.py:111-260` copre stati, selezione, `finish`, cache, errori; `340-490` pulse e barra. `tests/test_chapter_audit.py:120-180` copre documenti condivisi, heading nidificati e filtro. `tests/test_scenarios.py` copre gli invarianti end-to-end. Mancano i casi elencati in fondo.

## Invarianti e assunzioni (la radice delle debolezze)

1. **Le righe sono voci TOC; il progresso è per documento.** È il contratto, ma rende ambigua la frase «capitolo tradotto» quando due voci condividono un file.
2. **Il pannello conosce solo il run corrente.** `done`/`plan` nascono dai callback del worker; la cache persistente non viene letta all'apertura.
3. **`done` significa «processato», non «tradotto con successo».** Gli errori sono contati a parte ma non sottratti.
4. **`running` è derivato da `0 < done < total`.** Non significa «in volo»: un capitolo fermo a metà resta `running` per sempre.
5. **La selezione è per href/file; il piano è per file.** Il motore isola le ancore (`chapters.py:271-296`), ma la riga non sa rappresentare un intervallo.
6. **Il completamento è ottimistico.** `finish(ok=True)` presume che un run riuscito abbia processato tutto.
7. **La cache ha due facce.** La tabella `cache` è posizionale e ha `page`/`original` (`lib/cache.py:133-135`, `254-259`); `noesis_resume` è per contenuto e **non ha `page`** (`book.py:264-330`). L'estimate calcola i cached per capitolo in modo **proporzionale**, non esatto (`estimate.py:472-495`).

## Domande poste ai critici

Le stesse, nell'ordine, a `council-luna` e `council-glm`:

1. All'apertura di un libro, senza avviare una traduzione, il pannello può mostrare quali capitoli risultano già tradotti in cache? Quale informazione manca e dove andrebbe presa?
2. Qual è l'unità di stato di un «capitolo»: la voce del TOC o il documento XHTML? Con due voci sullo stesso documento e una sola selezionata, cosa dovrebbero mostrare le due righe e cosa mostrano oggi?
3. Gli stati disponibili bastano per rappresentare un libro riaperto, un run annullato, un capitolo interamente in cache, un capitolo parziale? Quali stati mancano o sono ambigui?
4. Selezione e progresso usano la stessa chiave? Elenca gli scenari in cui le due chiavi (href/file) divergono e l'effetto su riga e totali.
5. `finish(ok=True)` porta a `total` i documenti con almeno un segmento processato: in quali scenari può dichiarare completo un capitolo incompleto? Serve un segnale diverso?
6. Un segmento in errore viene contato in `done` e il documento diventa `ERROR`: la percentuale globale può raggiungere 100% con un capitolo rosso? Qual è la semantica corretta di `done` e di `overall`?
7. Dopo cancel o fail, quali stati restano e quali animazioni continuano? Cosa dovrebbe vedere l'utente e cosa vede oggi?
8. I filtri «Tutti / Da tradurre / Tradotti» trattano correttamente heading, capitoli senza contenuto, esclusi e sottotree? Ci sono casi in cui una heading resta o sparisce senza che il suo sottoalbero lo giustifichi?
9. Prestazioni e scala: cosa costa `refresh()` e `_rebuild()` rispetto al numero di voci e alla frequenza dei delta? Dove si satura la GUI su 7.500/20.000 voci?
10. L'architettura (lista piatta in ordine TOC + filtro) è adatta a una vista raggruppata o ordinata per stato («tradotti» / «da tradurre»)? Cosa manca nel modello?
11. Documenti fuori TOC, href duplicati, voci senza file, TOC che puntano fuori dallo spine: come influenzano ordine, gerarchia, conteggi e filtri?
12. Quali invarianti del pannello non sono coperti dai test (riapertura con cache, cancel/fail, errore+100%, documento condiviso con una sola voce, heading sibling, 20k voci)? Quali test aggiungeresti?

## Risposte (sintesi per domanda)

| # | DeepSeek | Luna | GLM |
|---|----------|------|-----|
| 1 | No: il modello nasce vuoto; servono piano e copertura cache per documento. La tabella `cache` ha `page`/`original`, `noesis_resume` no: si può fare un join per `uid(original)` nello scope. | No. La cache posizionale ha documento e traduzione; la resume è per contenuto. Serve correlare segmenti a documenti/ancore e consultare lo scope. | No. Il piano è calcolato solo nel run; persistere `plan` in `cache.info` è l'enabler minimo, ma da solo non dà lo stato cached per pagina. |
| 2 | Riga = voce TOC, progresso = documento. Con una sola ancora selezionata il file viene isolato e la sorella è `excluded`; con entrambe, le due righe mostrano gli stessi numeri. | Stessa risposta; il contratto «documento unico» è corretto per i totali, ambiguo per la riga. | Stessa risposta; con entrambe selezionate due righe «6/6» non dicono che i segmenti si sovrappongono. |
| 3 | Mancano `cached`, `interrupted`, `partial`; `running` confonde «in volo» e «fermo a metà»; `skipped` è ambiguo. | Sì: riapertura = `pending`, cancel = `running`, cache = `done` solo durante il run. | Sì: mancano «già tradotto», «interrotto», «parziale da cache». |
| 4 | Chiavi diverse: selezione href/file, progresso `page`. Divergono su file condivisi, selezioni miste, href duplicati. | Sì; una selezione per file seleziona tutte le voci, una per ancora distingue ma il conteggio resta per file. | Sì; segnala anche la selezione mista che disattiva il trim per ancora (`chapters.py:285-288`). |
| 5 | Promozione ottimistica: `done>0` → `total`. Confermato; serve un confronto col piano. | MAJOR: può dichiarare completo un capitolo incompleto; il test la codifica. | MINOR: difficile da triggerare oggi, ma il modello non controlla l'invariante. |
| 6 | Sì: `done` conta anche gli errori; `overall` non li sottrae. | Sì; 100% con riga rossa e messaggio «2/3». | Sì; percorso completo verificato nel codice. |
| 7 | Cancel/fail lasciano `running`; timer e `bar_current` restano busy. | Sì; pulse 2 Hz e shimmer infiniti. | Sì; `finished` esiste ma non è usato da timer/header. |
| 8 | Filtri corretti in generale; heading sibling trattenuto; `skipped` fuori da entrambi i filtri. | Heading sibling; heading mai grigie. | Heading sibling; heading a sottoalbero escluso restano a colore pieno. |
| 9 | `refresh()` è O(entries) per delta; filtro con molti heading O(n·sottoalbero); `_rebuild` O(n). | MAJOR sui filtri con molti heading; manca benchmark. | MINOR: 20k ~10-30 ms, ma il caso `todo` attivo durante il run è il peggiore. |
| 10 | La lista piatta è il contratto; per raggruppare serve una proiezione. | Una vista raggruppata richiede un indice stato→unità; il modello non ce l'ha. | Raggruppare per stato è la direzione sbagliata: distrugge l'ordine di lettura; i filtri bastano. |
| 11 | Extra in coda con nome file grezzo; href duplicati rompono `key()`; fuori spine → `skipped`. | Stessa risposta; il corpus non copre questi casi. | Stessa risposta; label grezza e tre parsing del TOC. |
| 12 | Mancano riapertura con cache, cancel/fail animato, errore+100, condiviso con entrambe selezionate, 20k con filtro, heading sibling, href duplicati. | Mancano gli stessi, più la selezione vuota. | Mancano gli stessi, più href duplicati e piano con extra. |

**Accordo**: 9 domande su 12 hanno risposta concorde. I disaccordi sono su **severità** (finish, performance) e **direzione** (vista raggruppata), non sui fatti.

## Rilievi

| # | rilievo | chi | severità | stato | decisione | evidenza | correzione | test |
|---|---------|-----|----------|--------|-----------|----------|------------|------|
| 1 | Il pannello non mostra lo stato cache all'apertura: è run-scoped | tutti | MAJOR | CONFERMATO (gap) | accettato | `main.py:434-453`; `progress_model.py:212-227`; `lib/cache.py:133-135,254-259`; `book.py:264-330` | Sorgente `chapter_cache_status`: join `uid(cache.original)` ↔ `noesis_resume` nello scope; persistere `plan` in `cache.info` come ottimizzazione; seed del modello all'apertura | riaprire dopo run pieno/parziale; contare cached per documento; cambio modello/stile |
| 2 | I segmenti in errore contano in `done`: 100% con capitolo rosso | tutti | MAJOR | CONFERMATO (simulazione) | accettato | `progress_model.py:159-181,278-291,332-336`; `main.py:1572` | Separare *processati* da *tradotti*; non contare gli errori in `done` (o rendere `overall` error-aware); non forzare 100% in `_on_finished` | un errore → `overall_percent()<100`, `done_chapters` coerente |
| 3 | Cancel/fail lasciano `running`: pulse e shimmer infiniti | tutti | MAJOR | CONFERMATO (simulazione) | accettato | `progress_model.py:342-344,398-407`; `chapter_track.py:404-427,452-459`; `main.py:1657-1681` | `running_units()` rispetta `finished`; stato `interrupted`/`cancelled` o stop esplicito di timer/header | cancel e fail → `is_animating()` falso, barra non busy |
| 4 | `finish(ok=True)` promuove `done>0` a `total` | Luna MAJOR, GLM MINOR | MAJOR | CONFERMATO (simulazione) | accettato con nota | `progress_model.py:398-416`; simulazione 1/10 → 10/10 | Non inferire il completamento: confrontare con il piano; se `done<total`, resta parziale/errore e si logga il mismatch | piano 10 + 1 delta + finish(ok) → non done |
| 5 | Selezione vuota nel wizard = tutto il libro | Luna | MAJOR | CONFERMATO (codice) | accettato | `translate_wizard.py:67-72,363-371`; `main.py:1279-1280,1424-1426`; `book.py:725-729` | Distinguere `[]` da `None`; in modalità capitoli richiedere almeno una voce o confermare «tutto il libro» | wizard capitoli senza check → nessuna traduzione o conferma esplicita |
| 6 | `refresh()` è O(entries) per delta; filtro con heading O(n·sottoalbero); rebuild O(n) | Luna MAJOR, GLM MINOR | MEDIA | CONFERMATO (complessità), SOSPETTO (soglia) | accettato | `chapter_track.py:308-336,363-382,429-440`; `progress_model.py:342-344` | Cache del filtro per `(filter, revision)`; set `running` mantenuto; scansione unica dei sottoalberi; rebuild differito; benchmark 7.5k/20k | 20k unit, filtro `todo`, 20 delta/s: lag event loop |
| 7 | Heading trattenuto da un documento sibling allo stesso livello | tutti | MEDIA | CONFERMATO (simulazione) | accettato | `chapter_track.py:325-336` | Interrompere la scansione quando `unit.depth <= depth`, anche per i documenti | fixture H d0 + doc d0 visibile + doc d1 escluso |
| 8 | Stati insufficienti: mancano cached/interrupted/partial; `running` ambiguo | tutti | MAJOR | CONFERMATO | accettato | `progress_model.py:34-44,278-300,398-416` | Aggiungere `origin` (cache/fresh), stato `interrupted`, e separare processati/tradotti | riapertura, cancel, cache piena |
| 9 | Selezione (href/file) e progresso (page) divergono; condivisione documento ambigua | tutti | MEDIA | CONFERMATO (semantica), SOSPETTO (misto) | accettato con nota | `progress_model.py:230-244,313-336`; `chapters.py:271-296`; `main.py:1270-1292` | Tenere i totali per documento; aggiungere indicatore «documento condiviso»/range; documentare il caso misto | due voci selezionate → stessi numeri; una sola → sorella excluded; misto file+ancora |
| 10 | Documenti fuori TOC in coda con nome file grezzo | GLM | MINOR | CONFERMATO | accettato | `progress_model.py:246-260` | Etichetta leggibile e collocazione (testa/coda) esplicita; valutarne l'esclusione dai totali di lettura | piano con `cover.xhtml`/`nav.xhtml` |
| 11 | `set_units` non azzera `plan`, `cached_pages`, `selection` | DeepSeek | MINOR | CONFERMATO (codice, oggi non usato) | accettato | `progress_model.py:263-272` | Azzerare tutto o rimuovere il metodo | riuso del modello con unità nuove |
| 12 | `build_units(selected=...)` filtra le righe invece di marcarle `excluded` | DeepSeek | MINOR | CONFERMATO (codice, oggi non usato) | accettato | `progress_model.py:83-112`; `230-244` | Rimuovere il parametro o allinearlo a `set_selection` | build_units con selezione parziale |
| 13 | `state()` e `unit_state()` hanno semantiche diverse sulla selezione | DeepSeek | MINOR | CONFERMATO | accettato | `progress_model.py:293-308` | Deprecare `state()` o allinearlo | documento condiviso con una voce esclusa |
| 14 | `cached` include i segmenti TOC, `cached_pages` no | DeepSeek | MINOR | CONFERMATO | accettato | `progress_model.py:173-178`; `ui/translate_view.py:196-197` | Escludere `TOC_PAGE` dal conteggio globale o documentarlo | run con titoli TOC in cache |
| 15 | L'header mostra `running[0]`, non il capitolo realmente in volo; include gli errori | DeepSeek | MEDIA | SOSPETTO | da verificare | `progress_model.py:342-344`; `chapter_track.py:404-427` | Set esplicito `in_flight` dal worker, o header aggregato («3 capitoli in corso») | run con 2+ capitoli in parallelo |
| 16 | L'auto-scroll su `running[0]` combatte lo scroll utente | DeepSeek | MINOR | SOSPETTO | da verificare | `chapter_track.py:376-394` | Toggle «segui» o scroll solo se l'utente non ha scrollato | run lungo con scroll manuale |
| 17 | I cached per capitolo dell'estimate sono proporzionali, non esatti | DeepSeek | MEDIA | CONFERMATO (commento) | accettato | `estimate.py:472-495` | Non usarli come stato; join `page`/`original` per l'esattezza | confronto con cache reale |
| 18 | TOC parsato 3 volte fra apertura e avvio | GLM | MINOR | CONFERMATO | accettato | `main.py:425-432,434-453,1479-1489` | Riutilizzare le unità della `_show_toc` | tempo di apertura su libro grande |

## Bug

### Confermati

1. **Errore + 100%** — scenario: un documento con 2 segmenti, uno in errore; `done=2/2`, `overall_percent()=100`, `file_state=error`, `done_chapters` lo esclude. Evidenza: `progress_model.py:159-181,332-336`; `main.py:1572`. Simulazione eseguita: `overall=(4,4)`, `100.0`, `done_chapters=1`, `state_b=error`.
2. **Cancel/fail ancora animati** — scenario: un documento a metà, `finish(ok=False)`; `running_units()` continua a restituirlo, il timer resta attivo, `bar_current` resta busy. Evidenza: `progress_model.py:342-344,398-407`; `chapter_track.py:404-427,452-459`; simulazione: `running=['a.xhtml']` dopo cancel, `finished=True`.
3. **`finish(ok=True)` promuove 1/10 a 10/10** — scenario: piano 10, un solo delta, fine con successo; `done[a]=10`. Evidenza: `progress_model.py:415-416`; simulazione.
4. **Heading sibling** — scenario: H d0, A d1 escluso, B d0 pending; il filtro `todo` tiene H. Evidenza: `chapter_track.py:325-336`; simulazione: `True`.
5. **Selezione vuota = tutto il libro** — scenario: wizard in modalità capitoli, nessuna checkbox; `selected_chapters()=[]` → `_normalize_chapter_spec([])=None` → `translate_epub(chapters=None)`. Evidenza: `translate_wizard.py:67-72,363-371`; `main.py:1279-1280,1424-1426`; `book.py:725-729`.

### Sospetti (con esperimento)

- **Saturazione a 20k voci**: la complessità è O(n) per delta e O(n·sottoalbero) con filtro attivo, ma non c'è una misura. Esperimento: 20k unit, filtro `todo`, 20 delta/s, misurare il lag dell'event loop.
- **Selezione mista file+ancora**: `chapters.py:285-288` disattiva il trim se una voce dello stesso file non ha fragment; le righe per ancora mostrano numeri che includono segmenti fuori dal loro range. Esperimento: fixture con due voci ancorate + una voce file-level sullo stesso documento.
- **Run «riuscito» con callback mancanti**: `finish(ok=True)` non confronta i conteggi col piano. Esperimento: motore fake che omette un callback e restituisce successo; oggi il capitolo verrebbe promosso.
- **Header «capitolo corrente» in parallelo**: con 2+ documenti parziali, `running[0]` è il primo in ordine TOC, non necessariamente quello in volo. Esperimento: due documenti con delta alternati.

### Non riproducibili

Nessun rilievo è stato scartato come non riproducibile. Due sono stati **ridimensionati**: la promozione di `finish` (Luna MAJOR, GLM MINOR) resta un rischio di correttezza ma è raro nel flusso attuale; il costo dei filtri (Luna MAJOR, GLM MINOR) è reale ma la soglia di saturazione non è misurata.

## Punti critici e debito

- **Due unità di misura**: la riga è una voce TOC, lo stato è un documento. Qualsiasi vista «tradotti/da tradurre» deve dire esplicitamente quale delle due sta contando.
- **Stato run-scoped**: il modello non ha una sorgente persistente. La cache ha i dati (tabella `cache` con `page`/`original`; `noesis_resume` con lo scope), ma il pannello non li legge.
- **Semantica di `done`**: processati vs tradotti. Finché coincidono solo per caso, la percentuale non è affidabile.
- **Lifecycle**: `running` non è «in volo»; `finished` non spegne le animazioni; `finish` indovina il completamento.
- **Filtri**: il caso heading sibling è un bug; il costo è O(n) per delta e O(n·sottoalbero) con molti heading; `_rebuild` ricrea N item.
- **Selezione**: vuoto = tutto il libro; file vs ancora; href duplicati; voci fuori spine.
- **Debito**: `set_units` incompleto, `build_units(selected)` incoerente, `state()` legacy, `cached` che include il TOC, commento «O(visible)» falso.
- **Estimate**: i cached per capitolo sono proporzionali; non vanno usati come stato.

## Piano di correzione

1. **Sorgente di verità per capitolo** — file: `book.py` (nuova funzione `chapter_cache_status`), `progress_model.py`, `main.py`. Calcolare piano e copertura cache per documento nello scope corrente (join `cache.page`/`original` ↔ `noesis_resume`; persistere `plan` in `cache.info` come ottimizzazione). Seed del modello in `_show_toc`. Test: riapertura dopo run pieno/parziale, cambio modello/stile, conteggi esatti per documento. Rischio: medio (join e scope). Criterio: il filtro «Tradotti» mostra i capitoli giusti senza avviare un run.
2. **Separare processati e tradotti** — file: `progress_model.py` (`DeltaBatch`, `overall`, `file_state`), `main.py` (`_on_finished`, `_on_delta`). Non contare gli errori in `done`; `overall` non deve raggiungere 100% con errori; non forzare 100% in `_on_finished`. Test: errore+100, tutto ok → 100. Rischio: basso. Criterio: percentuale e messaggio finale coerenti.
3. **Lifecycle del run** — file: `progress_model.py` (`running_units`, `finish`), `chapter_track.py` (`_update_timer`, `_update_header`). `finished` spegne timer/header; aggiungere `interrupted`/`cancelled` o un flag equivalente. Test: cancel/fail → nessuna animazione, barra non busy. Rischio: basso.
4. **Completamento onesto** — file: `progress_model.py` (`finish`). Rimuovere la promozione `done>0 → total` o applicarla solo se `done == total`; se il run finisce con un mismatch, segnare il documento come parziale/errore e loggare. Test: piano 10 + 1 delta + finish(ok) → non done. Rischio: medio (cambia il messaggio finale in casi rari).
5. **Selezione vuota** — file: `ui/translate_wizard.py`, `main.py`. Distinguere `[]` da `None`; in modalità capitoli richiedere almeno una voce o mostrare una conferma «verrà tradotto tutto il libro». Test: wizard senza check. Rischio: basso.
6. **Filtri e heading** — file: `ui/chapter_track.py`. Interrompere lo scan quando `unit.depth <= depth` anche per i documenti; calcolare la visibilità dei sottoalberi in una passata. Test: fixture flat H d0 + doc d0; nested headings. Rischio: basso.
7. **Prestazioni** — file: `ui/chapter_track.py`, `progress_model.py`. Cache del filtro per `(filter, revision)`; set `running` mantenuto; evitare la copia per `all`; rebuild differito. Benchmark 7.5k/20k con filtro `todo`. Rischio: medio. Criterio: refresh sotto ~16 ms a 20k con filtro attivo.
8. **Debito e documentazione** — file: `progress_model.py`, `estimate.py`, `AGENTS.md`. `set_units` completo, `build_units(selected)` allineato o rimosso, `state()` deprecato, `cached` senza TOC, extra TOC etichettati, commento «O(visible)» corretto, nota che i cached per capitolo dell'estimate sono proporzionali. Test: unità nuove, run con extra, cache TOC.

**Totale: 8 passi** (P0: 1-3; P1: 4-6; P2: 7-8).

## Aree non verificate / esperimenti

- **Benchmark 7.5k/20k** con filtro `todo` attivo e delta a 20 Hz: misurare il lag dell'event loop, non solo il repaint.
- **Cache reale**: aprire un DB di un libro tradotto e verificare che il join `uid(original)` ↔ `noesis_resume` ricostruisca i conteggi per pagina; provare cambio modello/stile.
- **Fixture flat** con heading e documento sibling; **href duplicati**; **voci fuori spine**.
- **Motore fake** che termina con successo omettendo un callback: verificare il comportamento di `finish`.
- **Parallelo**: due documenti in volo, controllo dell'header e dell'auto-scroll.
- **Selezione mista** file+ancora sullo stesso documento.

## Implementazione (2026-10-24)

Gli 8 passi sono stati implementati nel desktop e sincronizzati nel repository
gemello.

| passo | esito | file principali |
| --- | --- | --- |
| 1. sorgente di verità per capitolo | fatto: `book.chapter_cache_status` + piano in `cache.info` + seed in `_show_toc` | `book.py`, `main.py`, `progress_model.py` |
| 2. processati vs tradotti | fatto: gli errori non entrano in `done`; `overall` < 100 con un rosso; niente 100% forzato | `progress_model.py`, `main.py` |
| 3. lifecycle | fatto: `running_units()` vuoto a run chiuso; timer/header si fermano; righe parziali restano | `progress_model.py`, `chapter_track.py` |
| 4. completamento onesto | fatto: niente promozione `done>0 → total`; mismatch in `incomplete` e nel log | `progress_model.py`, `main.py` |
| 5. selezione vuota | fatto: conferma «tutto il libro»; `chapter_mode`/`whole_book` fino a `_start_translation` | `translate_wizard.py`, `main.py`, locales |
| 6. filtri e heading | fatto: stop a qualsiasi sibling; test dedicato | `chapter_track.py`, `test_chapter_audit.py` |
| 7. prestazioni | fatto: vista filtrata cache per `(filter, revision)`, mappe file→riga; test strutturale | `chapter_track.py`, `test_translate_view.py` |
| 8. debito e documentazione | fatto: `set_units` completo, `state()` selection-aware, extra TOC etichettati, estimate documentato, AGENTS aggiornato | `progress_model.py`, `estimate.py`, `AGENTS.md` |

**Verifica**: 403 test desktop OK (1 skip), scenario harness 11/11, console-clean
7/7, gemello 23 OK. Commit desktop `a2e3f1e`, gemello `46f1daa`.

**Limiti dichiarati**:

- lo stato all'apertura è quello dell'**ultimo run** per la lingua sorgente/
  destinazione corrente; il cambio modello/stile è coperto dal join su
  `noesis_resume`, ma senza un nuovo run il pannello non sa quale modello è
  attivo nel selettore;
- il benchmark 7.500/20.000 voci non è stato eseguito: la cache del filtro è
  verificata strutturalmente, non con una misura di latenza;
- la selezione mista file+ancora resta documentata, non reinterpretata: i
  totali sono per documento, come da contratto.

## Verdetti dei critici (verbatim)

- **Luna**: `APPROVE_WITH_CHANGES` — «buona base per l'ordine TOC e la selezione con ancora, ma cache, stato di run fermo, semantica del 100% e costi dei filtri meritano verifica e correzioni mirate.»
- **GLM**: `APPROVE_WITH_CHANGES` — «dopo cancel/fail pulse e shimmer continuano all'infinito; segmenti in errore contati in done; alla riapertura nessuna traccia di cache/run precedente.»

```json
{
  "verdict": "APPROVE_WITH_CHANGES",
  "blockers": [],
  "majors": [
    "La banda non mostra la copertura cache all'apertura.",
    "finish(ok=True) può promuovere a completo un documento con delta incompleti.",
    "Il 100% conta segmenti processati anche quando alcuni sono in errore.",
    "Dopo cancel/fail gli stati running/error possono mantenere animazioni attive.",
    "I filtri todo/done possono avere costo quadratico con molti heading.",
    "Una selezione vuota nel wizard può avviare la traduzione dell'intero libro."
  ],
  "minors": [
    "Un heading può restare visibile per un documento fratello allo stesso livello.",
    "Href duplicati e voci fuori spine non hanno identità/gestione verificate.",
    "Mancano test per alcune combinazioni critiche e per i filtri su 20.000 voci."
  ],
  "must_keep": [
    "Una riga per voce TOC in ordine di lettura, preservando le ancore.",
    "Progressi e totali sui documenti unici senza duplicarli per voce TOC.",
    "Heading mantenuti quando il loro sottoalbero contiene righe visibili.",
    "Payload lazy delle righe e aggiornamenti progressivi coalescenti."
  ]
}
```

```json
{
  "verdict": "APPROVE_WITH_CHANGES",
  "blockers": [],
  "majors": [
    "dopo cancel/fail pulse e shimmer continuano all'infinito (chapter_track.py:452-459, 416-427)",
    "segmenti in errore contati in done: overall_percent arriva a 100% con capitolo rosso (progress_model.py:170-172, 332-336)",
    "alla riapertura nessuna traccia di cache/run precedente: manca lo stato 'già tradotto' (main.py:434-453; piano per pagina calcolato solo nel run, book.py:746-754)"
  ],
  "minors": [
    "finish(ok=True) promuove done>0 a totale (progress_model.py:415-416)",
    "refresh() è O(entries) per delta, peggio col filtro todo attivo in run (chapter_track.py:308-382)",
    "_section_has_visible_child ignora la profondità dei documenti: sibling stesso depth preso per figlio (chapter_track.py:325-336)",
    "heading mai grigie anche a sottoalbero escluso (progress_model.py:296-299)",
    "href duplicati rompono l'invariante di key() (progress_model.py:73-80)",
    "documenti fuori TOC con label nome file grezzo in coda (progress_model.py:255-260)",
    "TOC del libro parsato 3 volte per apertura/avvio (main.py:425-453, 1479-1489)"
  ],
  "alternatives": [
    "stato 'cached/interrotto' via cache.info persistito (1 riga a book.py:754) invece di un'architettura di introspezione cache",
    "fermare pulse/shimmer rispettando il flag finished già esistente invece di nuovi stati UI",
    "escludere i segmenti in errore da overall() invece di introdurre una doppia percentuale"
  ],
  "must_keep": [
    "lista piatta in ordine TOC con gerarchia (contratto banda 2)",
    "throttle single-flight + DeltaBatch worker->GUI",
    "totali su documenti unici (tracked) e selezione per ancora con isolate_chapters",
    "payload per riga costruito dal delegate + revision-based repaint",
    "finish(ok=False) non finge completamento"
  ]
}
```

## Riconciliazione del Concilio

| # | rilievo | chi | severità | decisione | motivo |
|---|---------|-----|----------|-----------|--------|
| 1 | Vista raggruppata per stato | Luna: serve una proiezione; GLM: è la direzione sbagliata | MEDIA | **Rifiutato come default; accettato come vista opzionale** | L'ordine di lettura è il contratto; i filtri già offrono «tradotti/da tradurre». Una proiezione raggruppata è utile solo se richiesta esplicitamente, e va costruita senza toccare il modello |
| 2 | Severità di `finish(ok=True)` | Luna MAJOR, GLM MINOR | MAJOR (rischio) | **Accettato Luna, con la nota di GLM** | La simulazione conferma 1/10→10/10; è raro nel flusso attuale ma il modello non controlla l'invariante, quindi resta un rischio di correttezza |
| 3 | Costo dei filtri | Luna MAJOR, GLM MINOR | MEDIA | **Ridimensionato a MEDIA** | La complessità è confermata; la soglia di saturazione no. Serve un benchmark prima di un intervento strutturale |
| 4 | Stato cache all'apertura | Luna: join per documento; GLM: persistere `plan` | MAJOR | **Accettato il join; `plan` come ottimizzazione** | `plan` da solo non dà lo stato cached per scope; il join `page`/`original` ↔ `noesis_resume` è la strada corretta. La tabella `cache` ha `page`, la resume no |
| 5 | Selezione vuota = libro intero | Solo Luna | MAJOR | **Accettato** | Verificato nel codice: `[]` → `None` → `chapters=None` |
| 6 | Heading sibling | Entrambi | MEDIA | **Accettato** | Simulazione: `_section_has_visible_child` restituisce `True` per un sibling d0 |
| 7 | Heading mai grigie | Solo GLM | MINOR | **Accettato come documentazione** | Le heading non sono capitoli; il contratto «gli altri grigi» vale per le voci documento. Da chiarire in AGENTS, non è un bug |
| 8 | Etichetta/posizione extra TOC | Solo GLM | MINOR | **Accettato** | La coda con nome file grezzo è povera per una vista di stato |
| 9 | TOC parsato 3 volte | Solo GLM | MINOR | **Accettato** | Misurabile; riusare le unità della `_show_toc` |
| 10 | Commento «O(visible)» | Solo GLM | MINOR | **Accettato** | Il commento è falso: `refresh()` è O(entries) |

## Verdetti finali

- **Luna**: `APPROVE_WITH_CHANGES` — la base è buona, ma cache, run fermo, semantica del 100% e costi dei filtri vanno corretti.
- **GLM**: `APPROVE_WITH_CHANGES` — cancel/fail animati, errori contati in `done`, nessuna traccia della cache alla riapertura.

**Confidenza complessiva**: alta sui cinque bug confermati (codice + simulazione), media sulle soglie di performance e sui casi di selezione mista.
