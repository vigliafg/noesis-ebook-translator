# Analisi — velocità di traduzione con LLM (OpenRouter, `deepseek/deepseek-v4-flash-0731`)

Soggetto: **Rosen's Emergency Medicine**, capitolo **87. Stroke**, 671 segmenti /
140 214 caratteri, English → Italian. Numeri grezzi in `report.md` e
`summary.json`; per-run in `runs/<id>/` (`metrics.json`, `calls.jsonl`,
`quality.json`).

## Quadro d'insieme

| strategia | run | tempo | req/s | costo | qualità (giudice) |
| --- | --- | --- | --- | --- | --- |
| sequenziale (riferimento) | `r01` | **856 s** | 0,78 | $0,0265 | 98,8 |
| concorrenza 5 | `r02` | 160 s (5,4×) | 4,21 | $0,0264 | 97,1 |
| concorrenza 10 | `r03` | 129 s (6,6×) | 5,18 | $0,0264 | 97,9 |
| concorrenza 15 | `r04` | 113 s (7,6×) | 5,94 | $0,0262 | 97,9 |
| concorrenza 20 | `r05` | **112 s (7,7×)** | 6,01 | $0,0266 | 96,2 |
| concorrenza 20, **executor 32** | `r10` | **77 s (11,2×)** | 8,76 | $0,0261 | 98,3 |
| concorrenza 20, **interval 20 s** (default app) | `r09` | **745 s** | 0,90 | $0,0265 | 99,2 |
| concorrenza 10, **reasoning on** | `r06` | 321 s | 2,09 | **$0,0919** | 94,6 |
| **batching** 20 | `r07` | 541 s | 0,06 | **$0,0177** | 97,5 |
| batching 20 + reasoning | `r08` | **fallito** | — | $0,0120 | — |
| **con verifica dei fix** | | | | | |
| concorrenza 20, executor corretto | `r11` | **100 s** | 6,72 | $0,0259 | 97,1 |
| batching 20 con `stream=True` | `r12` | 601 s | 0,06 | $0,0178 | 98,3 |
| **batching parallelo 8** | `r13` | **222 s** | 0,16 | $0,0178 | 97,5 |
| **batching parallelo 8 + stream** | `r14` | **176 s** | 0,20 | $0,0176 | 97,9 |
| **batching parallelo 20** | `r15` | **118 s** | 0,30 | $0,0169 | 97,9 |
| **per-segmento 20 + stream** | `r16` | **62,7 s** | 10,7 | ~$0,026* | 98,8 |
| **batching 20 + stream** | `r17` | 121 s | 0,28 | **$0,0168** | 98,8 |
| **per-segmento 32 + stream** | `r18` | **49,4 s** | 13,6 | ~$0,026* | 97,9 |
| per-segmento 8 + stream (default app) | `r19`/`r21` | 135-170 s | 4-5 | ~$0,026* | 97,1-98,3 |
| per-segmento 20 + stream (2ª misura) | `r20` | 73,3 s | 9,2 | ~$0,026* | 97,1 |

## 1. Parallelismo: si ferma a 8, non a 20

La concorrenza guadagna molto fino a 5 (5,4×), poi sempre meno: 10 → 6,6×,
15 → 7,6×, 20 → 7,7×. La spiegazione è nel codice, non nella rete:

> `lib/handler.py` esegue ogni chiamata con `run_in_executor(None, …)`, cioè sul
> **default executor** del loop. CPython lo dimensiona `min(32, cpu+4)` = **8
> thread su questa macchina (4 CPU)**.

Infatti il parallelismo massimo osservato è **8** in `r03`/`r04`/`r05`/`r06`/`r09`,
mentre in `r10` (pool a 32) arriva a **20** e il tempo scende da 112 a **77 s**
(1,46× a parità di concorrenza, 11,2× sul sequenziale). Il valore scelto nel wizard
(`translate_parallel`) oggi **non è il vero tetto**: lo è il pool del loop.

**Fix verificato (`r11`)**: con l'executor dimensionato su `concurrency_limit` nel
codice (non più solo nell'harness), la run a concorrenza 20 raggiunge **20
chiamate in volo** e chiude in **100 s** (contro 112 s di `r05`; `r10` resta il
riferimento a 77 s con pool 32, che include il margine del pool più largo).

## 2. `request_interval` di default annulla il parallelismo

Con `interval = 20 s` (il default della famiglia OpenAI, che l'app non azzera in
modalità parallela) il run a concorrenza 20 impiega **745 s**, praticamente come il
sequenziale (856 s): 671 chiamate ÷ 20 worker × 20 s ≈ 671 s dominano tutto. Il
guadagno della concorrenza si vede **solo** con `interval = 0`. In altre parole,
nel percorso reale il parametro che decide il tempo non è `translate_parallel` ma
il throttle del motore.

## 3. Reasoning: costo doppio, nessun guadagno

Il modello ragiona per default (~2,27 s per chiamata contro 0,87 s). Con il
reasoning attivo:

* tempo **2,5×** (321 s vs 129 s a parità di concorrenza);
* costo **3,5×** ($0,0919 vs $0,0264) per **228 375 token di ragionamento**, cioè
  2,7 volte i token di traduzione effettivi;
* qualità **peggiore**: giudice 94,6 vs 97,9 e cifre preservate 95,9% vs 100%.

Nei task di traduzione il ragionamento non paga: da spegnere quando il modello lo
permette (`reasoning: {"enabled": false}` — l'harness lo fa fuori dal motore).

## 4. Batching: più economico, molto più lento, fragile

20 segmenti per richiesta (34 richieste invece di 671):

* **–33% di costo** ($0,0177 vs $0,0266): il system prompt si paga 34 volte invece
  di 671 (41 492 token di input contro 110 572);
* **4,8× più lento** del run a concorrenza 20 (541 s; p50 9,5 s, p95 45,8 s) e
  **3,4× più lento del sequenziale**: il loop del batching è seriale e ignora
  `concurrency_limit` (parallelismo massimo osservato: 1);
* qualità inferiore sulle liste: **16,5%** di segmenti identici alla sorgente
  contro 8,2-8,9% degli altri run (voci di bibliografia tradotte meno spesso);
* **con reasoning attivo non funziona**: 4 risposte su 6 finiscono in
  `finish_reason = length` (8 192 `max_tokens` esauriti da ragionamento + JSON
  troncato) → `TranslationFailed` dopo 3 tentativi, nessun EPUB scritto.
* **non funzionava affatto con lo streaming attivo** (il default dell'app):
  `translate_batch` leggeva la risposta con `get_result`, che con `stream=True`
  prende il percorso streaming e fallisce con *«'str' object has no attribute
  'readline'»*. **Fix verificato (`r12`)**: con `stream=True` la run completa le
  671 traduzioni in 34 richieste, qualità 98,3, $0,0178.
* **i batch erano seriali**. Dopo il fix girano in parallelo: `r13` (8 in volo,
  non-stream) **222 s**, `r14` (8 in volo, stream) **176 s**, stesso costo
  ($0,018) e qualità 97,5-97,9. Resta comunque più lento del per-segmento a
  concorrenza piena (100 s), ma costa il **33% in meno**.

## 4-bis. Lo streaming è più veloce, non solo più reattivo

A concorrenza 20 lo stesso run passa da **99,8 s** (non-stream, `r11`) a
**62,7-73,3 s** (stream, `r16`/`r20`): lo streaming sembra più veloce del
25-35%. **Attenzione alla varianza**: il provider oscilla (la stessa
configurazione a c=8 ha dato 170 s e 135 s in due run; il per-request effettivo
varia fra ~1,2 e ~3,0 s). Le differenze sotto il 20% non sono affidabili; la
scalabilità con la concorrenza invece è netta (8 → 20 → 32).
*Il costo di `r16`/`r18` non è nell'`usage` per lo stesso motivo: i token sono
quelli di `r11` (~110,6k in, ~48,5k out, $0,026) perché il testo inviato è
identico.

## 4-ter. Le due configurazioni migliori

| obiettivo | configurazione | tempo | costo | giudice |
| --- | --- | --- | --- | --- |
| **massima velocità** | per-segmento, 32 in parallelo, streaming | **49,4 s** (17,3× il sequenziale) | ~$0,026 | 97,9 |
| **equilibrata** | per-segmento, 20 in parallelo, streaming | 63-73 s | ~$0,026 | ~98 |
| **minor costo** | batching 20, 20 batch in parallelo, streaming | ~121 s | **$0,0168** (−35%) | 98,8 |
| default prudente | per-segmento, 8 in parallelo, streaming | 135-170 s | ~$0,026 | ~98 |

Il punto di equilibrio: a 20 in parallelo il per-segmento fa **62,7 s**; il
batching fa **121 s** ma costa un terzo in meno. La scelta dipende da cosa si
ottimizza — e sono entrambe raggiungibili dal wizard (concorrenza 8 di default,
batching a un click).

## 5. Qualità e costo per unità

Su tutte le strategie: cifre preservate **100%** (tranne il run con reasoning,
95,9%), rapporto di lunghezza 1,11-1,13 (l'italiano è più lungo dell'inglese),
giudice 94,6-99,2. Il 8-9% di "non tradotti" sono in gran parte etichette e
riferimenti che *devono* restare identici (`TABLE 87.1`, `Putamen (44%)`, voci di
bibliografia).

Costo: ~$0,026 per il capitolo (24 500 parole circa) ≈ **$0,0011 / 1000 parole**
per-segmento, **$0,0007** con batching. Il costo non è mai stato un vincolo in
questi test; il tempo sì.

## 6. Difetto collaterale trovato nella stima

`book.py` registrava `run_engine_calls` come numero di **segmenti** (671) anche nel
run batched, che ha fatto **34** richieste. `estimate._observed_latency()` usa
quel valore per calibrare la durata dei run successivi: con il batching la
latenza per chiamata risulta ~0,8 s invece dei ~16 s reali, e la stima della
durata diventa ottimistica. **Corretto**: ora conta le chiamate realmente fatte
(con batching: `ceil(n/20)`), quindi anche i tentativi ripetuti.

## 7. Fix applicati e verificati

| fix | dove | verifica |
| --- | --- | --- |
| executor dimensionato su `concurrency_limit` (tetto 32) | `lib/handler.py` | `r11`: 20 in volo, 100 s |
| niente throttle in parallelo (`request_interval=0`) | `main.py` + preferenza motore | test `test_parallel_removes_the_engine_throttle` |
| reasoning spento di default (`translate_reasoning`) | `engines/openai.py`, `openrouter.py`, `appconfig`, `book` | `r06` vs `r05`; test su body/override |
| batch non-stream letto come JSON | `engines/openrouter.py` | `r12`: 671/671, 34 richieste |
| batching parallelo (8 richieste) | `lib/translation.py` | `r13` 222 s, `r14` 176 s |
| retry dei soli ID mancanti + JSON riparato | `lib/translation.py`, `engines/openrouter.py` | test dedicati |
| `batch_size` configurabile (wizard + stima) | `appconfig`, `estimate`, wizard | test |
| glossario in Impostazioni e nei batch | `ui/settings_dialog.py`, `lib/translation.py` | test di run |
| retry con jitter e `Retry-After` | `lib/translation.py` | — |
| giudice: streaming + reasoning off | `quality/judge.py` | test |
| `run_engine_calls` = richieste reali | `book.py` | test `test_batching_records_requests_not_segments` |
| giudice legge le risposte in streaming | `quality/judge.py` | test `test_engine_judge_reads_a_streamed_reply` |

## Raccomandazioni

1. **Parallelismo di default** — **fatto**: il wizard parte da 8 richieste in
   parallelo e "sequenziale" resta un click per i motori rate-limited (856 s
   contro 63 s sul capitolo di prova).
2. **Streaming**: è il default dell'app ed è anche il percorso più veloce
   (62,7 s contro 99,8 s a c=20). Non spegnerlo per "leggere l'usage": il costo
   si ricava dai token, identici.
3. **Batching**: con i batch in parallelo a 20 il costo scende a $0,0169 (35% in
   meno del per-segmento) per ~2× il tempo. È la scelta giusta per un libro
   intero non presidiato; il per-segmento resta la scelta per la massima velocità.
4. **Executor e throttle** — **fatti**: executor dimensionato su
   `concurrency_limit` (tetto 32) e nessun throttle in parallelo.
5. **Reasoning spento** — **fatto** (`translate_reasoning=False`, dove supportato).
6. **Retry e rate limit** — **fatto** (jitter + `Retry-After`); una concorrenza
   adattiva (AIMD) resta un'evoluzione possibile.
7. **Glossario** — **fatto** (Impostazioni + batching).
8. **Merge dei segmenti** — **non esposto**: `ElementHandlerMerge` fonde i
   segmenti ma `add_translations` cerca la traduzione per contenuto del singolo
   elemento e con i fusi non la trova. Serve distribuire la traduzione per
   separatore (con misura di qualità dedicata); il batching copre già gran parte
   del beneficio.
9. **Auto-correzione dei segmenti scarsi** — non implementata: il giudice misura
   per segmento, ma ritradurre i sospetti richiede una soglia e una seconda
   passata con cache separata. Da progettare con una misura.

## Riproduzione

```bash
python tools/speedtest.py prepare
python tools/speedtest.py matrix          # ~1,5 h, 10 run
python tools/speedtest.py report
```

Nota di ambiente: misurazione wall-clock su una macchina a 4 CPU con 8 thread di
executor, rete condivisa; `stream` spento per leggere il `usage` esatto.
