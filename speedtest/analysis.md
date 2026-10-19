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

`book.py` registra `run_engine_calls` come numero di **segmenti** (671) anche nel
run batched, che ha fatto **34** richieste. `estimate._observed_latency()` usa
quel valore per calibrare la durata dei run successivi: con il batching la
latenza per chiamata risulta ~0,8 s invece dei ~16 s reali, e la stima della
durata diventa ottimistica. Va registrato il numero di **richieste** effettive
(con batching: `ceil(n/20)`).

## Raccomandazioni

1. **Dimensionare l'executor del loop a `concurrency_limit`** (o passare un
   executor esplicito in `Handler`): senza questo, `translate_parallel` sopra ~8
   su una macchina a 4 CPU è di fatto inerte. Guadagno misurato a c=20: 1,46×.
2. **Non lasciare `request_interval = 20 s` in modalità parallela** (azzerarlo o
   ridurlo): altrimenti la concorrenza scelta non produce effetto (745 s vs 112 s).
3. **Spegnere il reasoning** per la traduzione sui motori che lo supportano
   (preferenza dell'app o default per motore): 2,5× tempo e 3,5× costo in meno,
   qualità uguale o migliore.
4. **Batching opt-in e irrobustito**: batch adattivo, `max_tokens` più alto o
   suddivisione, riparazione del JSON, invio dei batch in **parallelo**; oggi è
   conveniente solo in costo e non convive col reasoning.
5. **Correggere `run_engine_calls`** per il batching (stima della durata).

## Riproduzione

```bash
python tools/speedtest.py prepare
python tools/speedtest.py matrix          # ~1,5 h, 10 run
python tools/speedtest.py report
```

Nota di ambiente: misurazione wall-clock su una macchina a 4 CPU con 8 thread di
executor, rete condivisa; `stream` spento per leggere il `usage` esatto.
