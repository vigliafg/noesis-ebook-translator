# Liste dei motori: una regola di visibilità per il desktop, il contratto del CLI intatto

- **Richiesta** (verbatim): «la lista dei motori llm che risulata dal menu a tendina dei wizard di traduzione non riporta i motori non LLM (inseriti sempre) e quelli LLM (devono essere visualizzati solo quelli scelti e configurati nel wizarda di onbarding e in quello di configurazione delle impotstazioni. controlla qste aincongruenza architetturale»
- **Obiettivo**: nelle liste di **selezione** del desktop i motori non-LLM restano sempre presenti e i motori LLM — storici o provider curati — compaiono **solo se configurati**; la CLI continua a mostrare tutto, perché lì il motore si sceglie *prima* di digitare la chiave.
- **Criteri di successo**:
  1. con configurazione vuota `desktop_engine_names()` contiene i **12 non-LLM** (Google×6, DeepL×3, MicrosoftEdge, Youdao, Baidu) e **nessun** LLM (nessun Gemini/ChatGPT/Claude/DeepSeek/OpenRouter, nessun provider curato);
  2. salvando una chiave per un LLM (dalla pagina *Traduzione* delle Impostazioni, dal wizard di traduzione o da uno slot provider), quel motore compare nel wizard, nel nastro e nel combo del giudice; rimossa la chiave, sparisce;
  3. `appconfig.engine_names()` **non cambia**: la CLI e il suo test continuano a vedere il registro completo;
  4. suite desktop verde, monofile del gemello rigenerato e parità verde.
- **Non-obiettivi**: l'onboarding resta sui provider curati (nessuna pagina per i non-LLM); `book.list_engine_names()` e il registro `builtin_engines` non cambiano; nessun flag `enabled` nuovo per motore; nessun badge "da configurare"; non si tocca la pagina *Provider*, la politica degli slot né il percorso di traduzione.
- **Assunzioni** (dalle risposte dell'utente): il wizard di onboarding **non** deve offrire i motori non-LLM; i 6 LLM storici devono **sparire** dalla lista finché non configurati.

## Vincoli dal repository

- `appconfig.py` è in `CORE_MODULES` del gemello (`../noesis-ebook-translator-engine/tools/sync_from_desktop.py:66`) e il gemello ha un test di parità che rigenera il monofile dal desktop (`tests/test_sync_parity.py:25-32`): **dopo la modifica la sync è obbligatoria** (`AGENTS.md`).
- `engine_supports_prompt()` (`appconfig.py:250-257`) è già la definizione di "LLM" nel progetto (usata da `ui/analysis_page.py:138` e `ui/translate_wizard.py:190`): nessuna semantica nuova.
- Il TUI del gemello sceglie il motore e digita la chiave **nello stesso form** (`frontend.py:173-187`): filtrare `engine_names()` renderebbe gli LLM non configurabili da lì.
- i18n: nessuna chiave nuova (nessun testo nuovo).
- Test che toccano la lista: `tests/test_provider_slots.py:48-59`, `tests/test_gui.py:26,39`, `tests/test_provider_ui.py:313,330,359,374`, `tests/test_wizard_estimate.py:55`, `tests/console_probe.py:130`.

## Stato attuale

- **Due registri che si sovrappongono**: `engines/__init__.py:22-28` (`builtin_engines` = 18 motori verbatim **+** i 17 generati dai provider curati; `engines/openai_compatible.py:223-230` salta i provider `builtin`, quindi OpenRouter esiste solo come motore verbatim) e `provider_catalog.py` (18 provider curati, `openrouter` compreso). Punto di contatto: `_provider_id_by_engine():168-172` (nome motore → id provider).
- **Una sola regola di visibilità**, in `appconfig.engine_names():212-229`: i 18 verbatim sono **sempre** in lista; dei provider curati entra solo chi ha uno slot abilitato. → i 6 LLM storici (Gemini, ChatGPT, Claude, ChatGPT(Azure), DeepSeek, OpenRouter) sono **sempre** proposti anche senza chiave: è l'incongruenza che l'utente ha visto.
- `set_provider_slots():323-338` **specchia** ogni slot in `engine_preferences`: abilitato → `api_keys`/`model`/`endpoint`; disabilitato → `api_keys=[]`, `model=None`, `endpoint=None`. Quindi `engine_preferences` è già la sorgente unica di "questo motore ha credenziali", per **entrambe** le famiglie.
- Altre scritture di `engine_preferences`: `settings_dialog.apply():372-377` (chiave del motore selezionato nella pagina *Traduzione*) e `main.py:1447-1450` (chiave/modello digitati nel wizard di traduzione, salvati all'avvio della traduzione). `_slots_from_engine_preferences():341-367` semina gli slot da lì alla prima migrazione (`ensure_defaults():138-143`).
- Superfici di **selezione** (4): `ui/translate_wizard.py:80`, `ui/workflow_bar.py:598` (combo iniziale del nastro), `main.py:371-379` (`_reload_engines`, la ricarica), `ui/settings_dialog.py:228` (giudice qualità).
- Superfici di **configurazione**: pagina *Traduzione* (`settings_dialog.py:139` → `legacy_engine_names()`), pagina *Provider* (slot), onboarding (`wizard.py:70` → `provider_choices()`).
- **Correzione di un errore del primo giro**: la bozza v1 sosteneva che `legacy_engine_names():239-247` avesse un "filtro morto" (id confrontati con nomi). **Falso**: `set(_provider_id_by_engine())` è un insieme di **nomi** ed esclude già OpenRouter — verificato a runtime, `legacy_engine_names()` ha 17 voci contro 18 di `builtin_engine_names()` e la differenza è esattamente `{'OpenRouter'}`. Il docstring è già soddisfatto, non c'è nulla da correggere.

## Approccio proposto

La regola di visibilità esiste già ma è **solo per i provider curati** ed è nella funzione **condivisa col CLI**. Non si tocca quella: si aggiunge accanto una funzione di selezione per il desktop.

```
# appconfig.py
def _engine_is_configured(name: str) -> bool:
    """A motore LLM è usabile quando ha credenziali: chiave o endpoint custom."""
    pref = get_engine_preference(name)
    return bool(pref.get("api_keys")) or bool(pref.get("endpoint"))

def desktop_engine_names() -> list[str]:
    """Lista di *selezione* del desktop: non-LLM sempre, LLM solo se configurati.

    Desktop-only: la CLI usa ``engine_names()``, che resta completa perché il TUI
    sceglie il motore prima di digitare la chiave.
    """
```

Il ramo "slot abilitato" è **inutile**: `set_provider_slots` ha già specchiato lo stato dello slot in `engine_preferences` (abilitato con chiave/endpoint → presente; disabilitato → azzerato). Una funzione di due righe copre entrambe le famiglie.

**Perché non in `engine_names()`**: la funzione è inlina­ta nel monofile del CLI, dove il motore si sceglie prima della chiave (`frontend.py:173-187`) — filtrarla là renderebbe gli LLM non configurabili dalla TUI. È la decisione su cui i due critici divergevano: GLM voleva la regola nella funzione condivisa (aggiornando l'assert del gemello), Luna l'ha bloccata. **Decido per Luna**: la regola resta nel desktop, il contratto del CLI non si tocca, e il gemello non richiede alcun edit manuale.

**Conseguenza dichiarata**: uno slot abilitato **senza** né chiave né endpoint (caso limite: provider che spera in una variabile d'ambiente) non comparirà più in lista — il motore legge le chiavi dalla configurazione (`engines/base.py:55-57,110-113`), quindi non sarebbe comunque usabile. Oggi comparirebbe. Reinserire chiave o endpoint lo riporta in lista.

## Passi

1. **Funzione di selezione** — file: `noesis_ebook_translator/appconfig.py`
   - `_engine_is_configured()` (2 righe) e `desktop_engine_names()` (filtro `engine_supports_prompt(e.name) and not _engine_is_configured(e.name)`); `desktop_engine_names` va aggiunto a `__all__` (`appconfig.py:23-33`). `engine_names()` **non** si tocca.
   - Verifica: estendere `tests/test_provider_slots.py:48-59` — config vuota → `Google(Free)New`/`DeepL`/`MicrosoftEdge(Free)` presenti e `ChatGPT`/`Gemini`/`Claude`/`Groq` assenti; `set_engine_preference("ChatGPT", api_keys=["k"])` → presente; slot abilitato → `Groq` presente, disabilitato → assente; slot abilitato senza chiave → assente; `Custom endpoint` con solo `endpoint` → presente. Un test separato fissa il contratto: `engine_names()` contiene ancora tutto (inclusi i 6 storici).
   - Rischio: basso. Stima **S**.
2. **Quattro punti d'innesto** — file: `ui/translate_wizard.py:80`, `ui/workflow_bar.py:598`, `main.py:371-379`, `ui/settings_dialog.py:228`
   - Le superfici di **selezione** passano a `desktop_engine_names()`. La combo iniziale del nastro (`workflow_bar.py:598`) conta quanto `_reload_engines`: senza di essa la barra mostrerebbe LLM non configurati finché non si ricarica. Le superfici di **configurazione** (pagina *Traduzione*, pagina *Provider*, onboarding) restano invariate.
   - Verifica: test GUI che all'apertura della finestra, con configurazione pulita, la combo del nastro non contenga `ChatGPT`; e che ne contenga `Google(Free)New`.
   - Rischio: basso/medio (quattro punti, uno dei quali all'avvio). Stima **S**.
3. **Test che davano il motore per presente** — file: `tests/test_gui.py:39`, `tests/test_provider_ui.py:359,374`, `tests/test_wizard_estimate.py:55`, `tests/console_probe.py:130`
   - `OpenRouter`, `ChatGPT`, il motore fittizio `Fake` (`tests/fixtures.py:308-345`: ha `prompt`, quindi è un LLM senza credenziali) e `Groq` vanno **configurati** esplicitamente nel test (`set_engine_preference(..., api_keys=[...])` o slot), non dati per presenti. `Fake` è il caso più delicato: senza chiave sparisce dal combo e i test dell'analisi del testo (`tests/test_wizard_estimate.py:74-88`) non eserciterebbero più il percorso LLM.
   - Verifica: `python -m unittest discover -s tests -v`.
   - Rischio: basso, ma è il passo con più attrito (sono test altrui). Stima **S/M**.
4. **Sync del gemello** — file: `../noesis-ebook-translator-engine/`
   - `cd ../noesis-ebook-translator-engine && python tools/sync_from_desktop.py && python -m unittest discover -s tests`. Nessun edit manuale: `engine_names()` è invariata, quindi l'assert di `tests/test_engine.py:9-18` resta verde. La sync è obbligata dalla parità del monofile.
   - Verifica: parità verde, suite del gemello verde, `git diff` del gemello limitato al monofile rigenerato.
   - Rischio: basso. Stima **S**.

**Totale: M**

## Alternative considerate (e perché scartate)

- **Regola dentro `engine_names()`** (proposta da GLM): "una sola funzione" e nessun doppione, ma la funzione è condivisa e il TUI sceglie il motore **prima** della chiave → gli LLM diventerebbero non configurabili dalla CLI, oltre a rompere l'assert del gemello. Scartata.
- **Filtro solo nella UI, senza toccare `appconfig.py`** (alternativa B di GLM): evita la sync (nessuna modifica a un modulo condiviso) ma sparpaglia la regola su quattro call site, e basta dimenticarne uno per far rientrare l'incongruenza. Scartata: la funzione in `appconfig.py` costa **un comando** di sync.
- **Flag `enabled` per motore in `engine_preferences`**: più esplicito, ma stato nuovo da migrare e due fonti di verità con gli slot.
- **Mostrare i non configurati con un badge "da configurare"**: scartata dall'utente.
- **Parametro `configured_only=False` su `engine_names()`**: zero funzioni nuove, ma tocca una firma condivisa — stessa obiezione della prima alternativa.

## Riconciliazione del Concilio

### Primo giro

| # | rilievo | chi | severità | decisione | motivo |
|---|---------|-----|----------|-----------|--------|
| 1 | `engine_names()` è condivisa col CLI, che chiede la chiave **dopo** aver scelto il motore | Luna | BLOCKER | **accettato** | verificato in `frontend.py:173-187`: la regola va in una funzione desktop separata; `engine_names()` invariata |
| 2 | La diagnosi del "filtro morto" in `legacy_engine_names()` è falsa | Luna + GLM | BLOCKER | **accettato** | **errore mio**, verificato a runtime (17 vs 18, differenza `{'OpenRouter'}`): passo eliminato |
| 3 | La migrazione `provider_slots_v2` non regge >4 provider né slot pieni; è doppia scrittura di uno stato già coerente | GLM + Luna | BLOCKER (GLM) / MAJOR (Luna) | **accettato** | `engine_preferences` è già la sorgente unica (mirror in `set_provider_slots`, `appconfig.py:323-338`): migrazione eliminata, limite documentato |
| 4 | `_is_configured` con sole chiavi non copre lo slot abilitato senza chiave | Luna | MAJOR | **parzialmente accettato** | il caso è reale ma **fuori perimetro**: un motore senza chiave né endpoint non è usabile (le chiavi si leggono da `engines/base.py:55-57,110-113`). Criterio riscritto ("slot abilitato **con credenziali**") e conseguenza dichiarata nei Rischi; test esplicito per lo slot senza chiave |
| 5 | Il motore fittizio `Fake` (LLM senza chiave) sparisce dal combo del wizard e i test dell'analisi lo davano per presente | Luna | MAJOR | **accettato** | passo 3: `Fake` configurato nel test (`tests/fixtures.py:308-345`, `tests/test_wizard_estimate.py:55`) |
| 6 | Il wizard di traduzione scrive a sua volta la chiave del provider: il Provider non è l'unico proprietario della preferenza | Luna | MAJOR | **accettato come analisi, fuori scope** | `main.py:1447-1450` riscrive `engine_preferences` per un motore curato: è una scelta di prodotto, non un difetto di lista. Va in *Domande aperte* |
| 7 | Combo del giudice: una preferenza salvata che sparisce viene riscritta vuota all'apply; e `quality_judge_engine` non è letto da nessuno | Luna | MINOR | **accettato come analisi, fuori scope** | due bug preesistenti (`settings_dialog.py:229,357`), elencati in *Domande aperte*; il piano non li peggiora oltre il necessario |
| 8 | Ridurre il piano a una funzione + un filtro; niente migrazione, niente filtro per nome | GLM | MAJOR | **accettato** | il piano finale ha 4 passi di cui uno è un comando di sync |
| 9 | Il passo "sync" è incompleto: va aggiornato l'assert di `test_engine.py` del gemello | GLM | MAJOR | **superato** | adottando la separazione desktop/CLI, `engine_names()` resta completa e quell'assert resta verde: nessun edit |
| 10 | Il cambio tocca anche giudice e nastro, non solo il wizard | GLM | MINOR | **accettato** | sono due dei quattro punti d'innesto, dichiarati nei criteri e nei test |
| 11 | Convertire il criterio 1 in estensione di `test_provider_slots.py:48-59` | GLM | MINOR | **accettato** | passo 1, nessun file di test nuovo |
| 12 | Il doppio proprietario della chiave provider è un danno reale o teorico? | GLM | domanda | **chiarito** | reale ma minore: il wizard riscrive `engine_preferences` senza aggiornare lo slot (`main.py:1447-1450`), quindi lo slot può ripristinare la chiave vecchia. Fuori scope, in *Domande aperte* |
| 13 | La lista del giudice non diventa vuota (c'è "auto"), ma una preferenza non disponibile viene azzerata | Luna | MINOR | **accettato come analisi** | comportamento coerente con "motore non più configurato", ma silenzioso: documentato nei Rischi |

### Secondo giro (delta: funzione separata, niente migrazione)

| # | rilievo | chi | severità | decisione | motivo |
|---|---------|-----|----------|-----------|--------|
| 14 | Manca il **quarto** punto d'innesto: la combo del nastro è popolata in `workflow_bar.py:598`, non solo da `main._reload_engines` | Luna + GLM | MAJOR / BLOCKER | **accettato** | verificato: la lista è costruita lì e ricaricata in `main.py:371-379` → il piano passa da 3 a **4** call site |
| 15 | `_engine_is_configured` può dimezzarsi: il ramo slot è ridondante, il mirror è già in `engine_preferences` | GLM | MAJOR | **accettato** | funzione da 2 righe; uniforma il criterio ("configurato = usabile") e toglie una dipendenza |
| 16 | Aggiungere la funzione a `__all__` (`appconfig.py:23-33`) | GLM | MINOR | **accettato** | la parità di export col monofile non la vedrebbe |
| 17 | Nome: `desktop_engine_names` descrive *chi* la chiama; `selectable_engine_names` sarebbe più esplicito | GLM | MINOR | **rifiutato** | gli altri abitanti del modulo (`builtin_engine_names`, `legacy_engine_names`) descrivono l'insieme, non l'uso: `desktop_` è il contrasto che serve ora, e il docstring spiega il perché |
| 18 | La nota sul limite ">4 provider" sovrastima il danno: il wizard permette comunque di cambiare chiave e modello | Luna | MINOR | **accettato** | limite riscritto come "impossibile gestire slot/endpoint da una pagina", con la nota che il wizard può ancora ri-reinserire le credenziali |
| 19 | Ordine: funzione + test unitario → call site → fix dei test dipendenti → sync | GLM | MINOR | **accettato** | i test "che davano il motore per presente" si sistemano dopo che il comportamento è fissato dal test unitario |

Nessun BLOCKER residuo dopo il secondo giro; il disaccordo su *dove* mettere la regola è stato deciso a favore di Luna con la motivazione tecnica (il flusso del TUI), non per mediazione.

## Verdetto dei critici

- **Luna** (primo giro): `REJECT` — «la modifica condivisa, così descritta, rende non configurabili dal TUI i motori LLM nascosti e poggia anche su una diagnosi errata del filtro OpenRouter».
- **Luna** (secondo giro, sul delta): `APPROVE_WITH_CHANGES` — «il blocker originario è chiuso, ma va filtrata anche la combo iniziale del nastro» (1 MAJOR, 1 MINOR).
- **GLM** (primo giro): `APPROVE_WITH_CHANGES` — «l'osservazione architetturale è vera e la sede è quella giusta, ma la bozza restringe il lavoro di metà».
- **GLM** (secondo giro, sul delta): `APPROVE_WITH_CHANGES` — «il piano è quasi minimo ma manca il quarto call site (ribbon) e `_engine_is_configured` può dimezzarsi» (1 BLOCKER, 1 MAJOR, 3 MINOR).

## Rischi e mitigazioni

1. **Uno slot abilitato senza chiave né endpoint sparisce dalla lista** (oggi compare). Mitigazione: criterio riscritto e test dedicato; reinserire chiave o endpoint lo riporta; nessun dato viene cancellato.
2. **Un provider configurato oltre il quarto slot** resta visibile tramite `engine_preferences` ma non è gestibile da una pagina (lo slot non esiste). Limite preesistente, documentato: oggi quegli stessi motori sono **invisibili**.
3. **Test altrui da toccare** (passo 3): è il passo con più attrito e il più facile da fare male, cioè "aggiustando" il test invece del comportamento. Mitigazione: ogni modifica al test deve configurare il motore tramite le stesse API della UI (`set_engine_preference`, slot), non con scorciatoie.
4. **Sync del gemello dimenticata**: la parità del monofile diventa rossa. Mitigazione: passo 4 esplicito, ultimo per costruzione.

## Test e verifica

- `python -m unittest tests.test_provider_slots tests.test_engine tests.test_gui tests.test_provider_ui tests.test_wizard_estimate -v`.
- `python -m unittest discover -s tests -v` (suite completa desktop).
- `cd ../noesis-ebook-translator-engine && python tools/sync_from_desktop.py && python -m unittest discover -s tests`.
- Verifica manuale: Impostazioni → Traduzione, salvare una chiave per `ChatGPT` e riaprire il wizard (deve comparire); cancellarla e riaprire (non deve comparire); stesso giro su uno slot provider (es. Groq) e sul giudice qualità.
- **Restano non verificati** (dichiarato dai critici): l'esito delle suite prima dell'implementazione e l'idempotenza di una migrazione che il piano non fa più.

## Criteri di accettazione

1. Configurazione pulita: il wizard, il nastro e il combo del giudice mostrano i 12 non-LLM e nessun LLM.
2. Chiave salvata (Impostazioni → Traduzione, wizard, o slot provider) → il motore compare nei tre punti; rimossa → sparisce.
3. `appconfig.engine_names()` invariata e `tests/test_engine.py:9-18` del gemello verde.
4. Suite desktop e del gemello verdi; monofile rigenerato, `git diff` del gemello limitato al monofile.

## Domande aperte / condizioni per l'assenso

1. **Slot abilitato senza chiave** (punto 1 dei Rischi): **risolto** — si conserva il comportamento di oggi: uno slot abilitato resta selezionabile anche senza chiave (chiave da variabile d'ambiente, endpoint custom). Vedi la *Revisione* in coda al piano.
2. **Bug preesistenti fuori scope**, scoperti dai critici e non toccati: `quality_judge_engine` è salvato ma **mai letto** (`settings_dialog.py:229,357`) — il giudizio usa il motore del nastro (`main.py:1170-1174`); il wizard di traduzione riscrive la chiave di un provider senza aggiornare lo slot (`main.py:1447-1450`), che può ripristinare quella vecchia. Vuoi che diventino due piani separati?

## Revisione 2026-10-17 (dopo l'implementazione)

Il piano è stato implementato e **due decisioni sono cambiate sotto la spinta dei test**, non delle opinioni.

### Il passo 1 ha richiesto due aggiunte

1. `_engine_is_configured()` è **unione**: per un provider curato conta lo **slot abilitato** *oppure* le credenziali in `engine_preferences`; per un motore verbatim solo le credenziali.
2. `set_provider_slots()` ora **ripulisce il mirror dei provider che spariscono dalla lista** (`previous_enabled - enabled(normalized)`).

### Perché: il test che ha smentito il secondo giro

GLM, nel secondo giro, chiedeva di dimezzare la funzione («il ramo `provider_slots` è ridondante: `set_provider_slots` specchia già tutto in `engine_preferences`»). Sembrava corretto e l'ho implementato. La **suite completa** l'ha bocciato subito:

```
FAIL: test_engine_names_only_show_enabled_providers
  set_provider_slots([...groq...])  →  "Groq" presente
  set_provider_slots([])            →  AssertionError: 'Groq' unexpectedly found
```

Causa: `set_provider_slots` azzera il mirror solo per gli slot **che riceve**; uno slot che *sparisce dalla lista* non viene mai inviato, quindi il suo `api_keys` resta in `engine_preferences` e il motore rimosso dall'utente continuava a comparire in lista. Con il criterio "solo credenziali" quel mirror stantio diventa visibile all'utente.

Esito: **rilievo respinto con l'evidenza**, e il rilievo MAJOR del **primo** giro di Luna («`_is_configured` basato solo su `api_keys`/`endpoint` non copre lo slot abilitato») è **confermato** — l'unione è la formulazione giusta. La causa radice (mirror mai ripulito) è stata corretta alla fonte invece di aggirata nel predicato: era il difetto che rendeva *sbagliata* anche la regola precedente, solo invisibile perché la lista si basava sullo slot.

### Cosa resta come da piano

Nessun'altra deviazione: `engine_names()` invariata, quattro punti d'innesto, test che configurano il motore invece di darlo per presente, sync del gemello. L'ipotesi "slot abilitato senza chiave sparisce" è stata **scartata**: si conserva il comportamento attuale.

Fuori piano, ma dovuto perché il cambio è **visibile all'utente**: una voce in `CHANGELOG.md` (`[Unreleased] → Changed`) e due paragrafi in `README.md` (§*Motori supportati*), che prima affermava «l'app espone tutti i motori».

### Verifica eseguita

| Controllo | Esito |
|---|---|
| `python -m unittest discover -s tests` (desktop) | **366 test, OK** (1 skip) |
| `tests.test_provider_slots` (4 test nuovi + 1 esteso) | OK |
| `cd ../noesis-ebook-translator-engine && python tools/sync_from_desktop.py` | monofile rigenerato (9 840 righe) |
| `python -m unittest discover -s tests` (gemello) | **23 test, OK** (1 skip) |
| `git status` del gemello | solo `noesis_ebook_translator_engine.py` + `ENGINE_SOURCE.json` (il sync registra sempre commit e versione) |
| `tests/test_engine.py` del gemello (contratto CLI) | verde: `engine_names()` non è cambiata |

**Non verificato**: il comportamento manuale nelle pagine Impostazioni (salvare/cancellare una chiave e riaprire il wizard) — richiede un desktop con display.
