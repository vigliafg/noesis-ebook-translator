# Motore di traduzione: i quattro lavori rimasti dopo il giorno della velocità

- **Richiesta** (verbatim): «conserva questi 4 punti nei piani per domani»
- **Contesto**: il 2026-10-19 abbiamo misurato e corretto il percorso caldo
  (concorrenza, throttle, reasoning, batching, glossario, giudice). Numeri e
  diagnosi stanno in `speedtest/analysis.md`; qui restano i quattro lavori che
  quella giornata ha identificato ma **non** chiuso.
- **Obiettivo**: chiudere i quattro punti senza regressioni, ognuno con una
  misura prima/dopo sullo stesso capitolo (Rosen 87 *Stroke*, 671 segmenti).
- **Non-obiettivi**: cambiare i motori verbatim se non attraverso
  `tools/import_core_from_fork.py`; introdurre nuove dipendenze; toccare il
  lettore o la banda 2; riscrivere la cache.

## Stato di partenza (misurato il 2026-10-19)

| configurazione | tempo | costo | giudice |
| --- | --- | --- | --- |
| sequenziale, senza throttle | 856 s | $0,026 | 98,8 |
| 8 parallele, streaming (default app) | 135-170 s | ~$0,026 | ~98 |
| 20 parallele, streaming | 63-73 s | ~$0,026 | ~98 |
| 32 parallele, streaming | 49,4 s | ~$0,026 | 97,9 |
| batching 20, 20 batch in parallelo, streaming | ~121 s | **$0,0168** | 98,8 |
| reasoning attivo (default prima del fix) | 321 s | $0,092 | 94,6 |

Varianza del provider: ±30% fra run identiche; sotto il 20% di differenza non
tirare conclusioni.

---

## Punto 1 — Merge dei segmenti (`merge_enabled`), oggi non esposto

**Perché è rimasto aperto**: `ElementHandlerMerge.prepare_original`
(`lib/element.py:744`) fonde più elementi in una sola riga separata da
`separator`, ma la scrittura (`ElementHandler.add_translations`,
`lib/element.py:729`) cerca la traduzione con
`translations.get(element.get_content())`: con i segmenti fusi la chiave non
esiste e **nessun testo viene riscritto**. La funzione è quindi dormiente, non
solo nascosta. Esporla oggi produrrebbe un EPUB invariato.

**Approccio**:
1. in `ElementHandlerMerge.prepare_original`, registrare per ogni originale
   fuso la lista degli `eid` che lo compongono e il numero di separatori;
2. override di `add_translations` in `ElementHandlerMerge`: dividere la
   traduzione del paragrafo per `separator` (usando `align_paragraph`, che già
   normalizza i segnaposto) e assegnare le parti agli elementi del gruppo;
3. se il numero di parti non coincide, **fallback**: scrivere l'intera
   traduzione sul primo elemento e lasciare gli altri com'erano, loggando il
   caso (mai testo perso o duplicato in silenzio);
4. esporre la checkbox nel wizard solo dopo una misura che dimostri qualità
   pari e meno richieste.

**Criteri di accettazione**:
- un EPUB con paragrafi brevi, tradotto con `merge_enabled=True`, contiene lo
  stesso numero di paragrafi e lo stesso testo tradotto del percorso normale
  (confronto per file/ordine);
- `format_fidelity` invariato; nessuna eccezione nel canale stderr;
- misura su Rosen 87: richieste e tempo **inferiori** al per-segmento, giudice
  non inferiore di più di 1 punto.

**Rischi**: la divisione per `separator` è fragile se il modello riscrive gli a
capo; mitigare col fallback e con un test su liste e tabelle (`build_styled_epub`
ha già `<ul>/<li>`).

---

## Punto 2 — Auto-correzione dei segmenti scarsi

**Stato**: `quality/` misura già per segmento (vuoti, identici alla sorgente,
rapporto di lunghezza, cifre) e il giudice dà un punteggio a campione. Oggi il
risultato è solo un report: un segmento tradotto male resta nel libro.

**Approccio**:
1. dopo `translation.handle`, raccogliere i segmenti sospetti con regole
   **deterministiche** (vuoto; identico alla sorgente con lunghezza > 40;
   rapporto di lunghezza fuori da [0,5; 2,0]; cifre mancanti);
2. ritradurli **uno per uno** con lo stesso motore/modello ma temperature più
   bassa, in una **cache separata** (suffisso `:repair` nella chiave di resume),
   così un secondo giro non corrompe lo scope normale;
3. accettare la nuova traduzione solo se migliora le metriche del segmento;
   altrimenti tenere la prima;
4. limite: al massimo N segmenti (config, default 2% o 50) per non trasformare
   un libro in una seconda traduzione completa;
5. esporre l'esito nel riepilogo (`Riparati: N/M`).

**Criteri di accettazione**:
- su un libro con errori indotti (il motore `Realistic` sa fallire su un
  segmento) il giro di riparazione recupera i segmenti e non tocca gli altri;
- il costo aggiuntivo resta sotto il 5% su Rosen 87;
- nessun doppio addebito: chi ha già la traduzione buona non viene ritradotto.

**Rischi**: falso positivo sui riferimenti bibliografici (identici alla
sorgente per scelta). Escludere le righe che sembrano citazioni (inizio con
numero + autore, `TABLE x.y`, etichette di figura) prima di riparare.

---

## Punto 3 — Concorrenza adattiva (AIMD)

**Stato**: la concorrenza è un numero fisso (default 8, massimo 32). Ieri 20-32
hanno funzionato su OpenRouter (0 errori), ma un provider più severo risponde
429 e il run resta lento o fallisce. C'è già jitter + `Retry-After`
(`lib/translation.py:76`).

**Approccio**:
1. contatore condiviso di errori per finestra (es. ultimi 20 esiti) nel
   `Handler`: su 429/5xx **dimezzare** i worker attivi (mai sotto 1); dopo K
   successi consecutivi **aumentare** di 1 fino al limite scelto;
2. i worker in eccesso restano in attesa, non vengono distrutti (il pool resta
   dimensionato al massimo);
3. registrare nel `cache.info` la concorrenza **effettiva media**, così la
   stima della durata impara dai run precedenti;
4. opzione per disattivarlo (comportamento attuale) e usarlo come default solo
   dopo una misura con un motore che risponde 429 (il `Realistic` può simulare
   gli errori).

**Criteri di accettazione**:
- con il motore che risponde 429 al 30% delle chiamate, il run **completa**
  tutte le traduzioni e non impiega più del doppio del tempo di un run pulito;
- con il motore pulito, la concorrenza effettiva resta quella scelta (±1);
- i test esistenti sulla concorrenza restano verdi.

**Rischi**: oscillazione. Isteresi obbligatoria (dimezza subito, cresce lento) e
un pavimento a 1.

---

## Punto 4 — Prova su un libro intero

**Stato**: tutte le misure sono su un capitolo (671 segmenti). Cache, prompt
caching, memoria, stabilità e durata su 40 000+ segmenti non sono verificati.
Il corpus locale arriva a **7 541 voci di TOC** (Ferri's) e i libri di
`corpus1/` arrivano a centinaia di MB.

**Approccio**:
1. scegliere un libro intero già presente (`corpus1/`), preferibilmente con TOC
   multilivello e immagini;
2. tradurlo con il **motore fittizio** per verificare gli invarianti
   (`segmenti processati == pianificati`, nessun capitolo `pending`) su scala;
3. tradurne una **sezione reale** (2-3 capitoli) col modello OpenRouter per
   misurare tempo/costo reali e la stabilità della cache;
4. misurare: picco di memoria, dimensione della cache, tempo di apertura,
   tempo di scrittura, ripresa dopo interruzione a metà libro;
5. registrare tutto in `speedtest/` (stesso schema dei run esistenti).

**Criteri di accettazione**:
- run fittizio: 100% dei segmenti, nessun errore, tempo lineare rispetto al
  capitolo (entro il 20%);
- run reale su 2-3 capitoli: nessun 429 non recuperato, costo e durata
  confrontabili con la stima del wizard;
- ripresa: uccidere il processo a metà e rilanciare → 0 segmenti rifatti.

**Rischi**: costo. Limitare la parte reale a 2-3 capitoli e usare
`NOESIS_ONLINE_TESTS=1` per non renderla obbligatoria in CI.

---

## Ordine suggerito

1. **Punto 4** (libro intero, fittizio) — è la rete di sicurezza per gli altri
   tre e non costa nulla.
2. **Punto 1** (merge) — sblocca un risparmio di richieste già previsto dal
   motore; richiede una misura di qualità dedicata.
3. **Punto 3** (AIMD) — robustezza per i provider severi.
4. **Punto 2** (auto-correzione) — il più delicato: dipende dalle metriche e
   dal giudice, e va misurato su errori indotti.

## Test e verifica (comuni)

```bash
python -m unittest discover -s tests -v        # desktop
python tools/scenario_harness.py               # invarianti di stato
python tools/format_fidelity.py src.epub out.epub
cd ../noesis-ebook-translator-engine && python tools/sync_from_desktop.py \
  && python -m unittest discover -s tests      # dopo ogni modifica al motore
```

Ogni punto chiude con: test nuovi, suite verde, gemello risincronizzato e
`CHANGELOG.md` aggiornato.

## Riferimenti

- Misure e diagnosi: `speedtest/analysis.md`, `speedtest/report.md`.
- Harness: `tools/speedtest.py`.
- Motore: `lib/element.py` (merge), `lib/translation.py` (batch, retry),
  `lib/handler.py` (executor), `book.py` (`_configure_translator`,
  `_count_engine_calls`), `estimate.py` (`observed_latency`).
- Qualità: `quality/metrics.py`, `quality/judge.py`, `tools/quality_harness.py`.
