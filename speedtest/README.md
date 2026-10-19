# Speed test — traduzione LLM su OpenRouter

Misura la **velocità reale** del motore di traduzione su un capitolo vero, con un
modello vero e una chiave vera. Serve a decidere come tarare il wizard (quanta
concorrenza, batching sì/no, quanto "ragionamento" lasciare al modello).

## Soggetto

| | |
| --- | --- |
| Libro | `corpus1/Rosen's Emergency Medicine 10ed 2023 SLIM.epub` |
| Capitolo | **87. Stroke** (`XHTML/B9780323757898000876/CH0087_1224-1242_….xhtml#B9780323757898000876`, pp. 1224-1242) |
| Segmenti | **671** traducibili (698 voci, 140 214 caratteri, il più lungo 1 907) |
| Motore | `OpenRouter` |
| Modello | `deepseek/deepseek-v4-flash-0731` |
| Lingua | English → Italian |

## Le tre strategie

1. **Parallelismo di chiamata** — `concurrency_limit` = 1 / 5 / 10 / 15 / 20,
   sempre col `request_interval` a 0. Il valore di default dell'engine OpenAI family
   è **20 s** fra due chiamate: un run extra (`r09`) lo tiene per mostrare quanto
   pesa. Un altro run (`r10`) alza a 32 il *default executor* del loop, perché
   `Handler` esegue ogni HTTP con `run_in_executor(None, …)` e CPython dimensiona
   quel pool a `min(32, cpu+4)` → **8 thread su questa macchina**: oltre 8 la
   concorrenza non può salire senza quell'override.
2. **Batching** — `online_batching`: 20 segmenti concatenati in una sola richiesta
   JSON (la dimensione è cablata in `lib/translation.py`). Due run: con e senza
   reasoning.
3. **Effort minimo** — il modello **ragiona per default** (~150 token di
   ragionamento anche per un segmento di cinque parole). L'harness inietta
   `reasoning: {"enabled": false}` nell'HTTP (non nel motore): `r05` vs `r06`,
   `r07` vs `r08`. Le chiamate del giudice hanno sempre il reasoning spento, così
   i punteggi restano confrontabili.

## Metodo

Ogni run è un **sottoprocesso** con `NOESIS_CONFIG_DIR` e `cache_path` propri
(`speedtest/runs/<id>/`): nessun run può leggere le traduzioni di un altro, quindi
ogni misura è a freddo. `tools/speedtest.py`:

* avvolge `request` in tutti i moduli già importati per registrare **ogni** chiamata
  HTTP (durata, token di prompt/completamento/ragionamento, cache hit, costo reale
  da `usage`, errori) in `calls.jsonl`;
* esegue in streaming **spento**: così il `usage` arriva nel corpo JSON e i numeri
  non sono stimati;
* a fine run calcola le metriche (`metrics.json`) e la **qualità**
  (`quality.json`/`quality.md`): metriche offline su tutti i segmenti + giudice AI
  a campione (12 segmenti) con **lo stesso modello**.

### Output di un run (`speedtest/runs/<id>/`)

| file | contenuto |
| --- | --- |
| `translated.epub` | EPUB tradotto (solo il capitolo; conserva gli asset del libro) |
| `calls.jsonl` | una riga per chiamata HTTP: fase, modello, secondi, token, costo, errore |
| `metrics.json` | aggregato + stato finale + stats della cache (righe, tradotte, marker) |
| `quality.json` / `quality.md` | metriche di qualità e campioni del giudice |
| `run.log` | note dell'harness |

I file pesanti (`runs/`, `matrix.log`) sono in `.gitignore`: si versionano lo
strumento e il report aggregato.

## Comandi

```bash
python tools/speedtest.py prepare                        # piano e conteggi (nessuna chiamata)
python tools/speedtest.py run --id prova --concurrency 20 --max-seconds 20
python tools/speedtest.py matrix                         # tutta la matrice (~1,5 h)
python tools/speedtest.py matrix --only r05-conc20,r06-conc10-reasoning
python tools/speedtest.py report                         # report.md + summary.json
```

## Come leggere i risultati

* `report.md` / `summary.json` — tabella per run: tempo, secondi/segmento,
  richieste/s, token, costo reale, p50/p95, parallelismo massimo osservato,
  qualità.
* Confronti chiave: `r02`→`r05` (guadagno della concorrenza), `r05` vs `r09`
  (quanto costa il throttle di default), `r05` vs `r06` (quanto costa il
  reasoning), `r03` vs `r07` (per-segmento vs batching a 20).
