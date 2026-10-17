# Changelog

Le modifiche rilevanti dell'app. Il formato segue
[Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il versionamento è
`v<major>.<minor>.<patch>` (definito in `noesis_ebook_translator/__init__.py`).

Il changelog parte da qui: le versioni precedenti non avevano un file dedicato,
la storia completa è nei commit (`git log`).

## [Unreleased]

### Added

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
- `tools/fetch_provider_catalog.py` per rigenerare lo snapshot incluso nel
  bundle (utile solo per lo sviluppo: l'app si aggiorna dalla UI).

### Changed

- `appconfig.engine_names()` elenca i motori del plugin più **solo i provider
  abilitati**, così ribbon e wizard restano corti.
- La sonda del modello è **thread-safe**: costruisce una sottoclasse transitoria
  invece di mutare la configurazione condivisa del motore condiviso, e forza
  `stream=False` (una sola richiesta breve).
- Documentazione: nuova pagina *Providers* (5 lingue) e README aggiornato.

### Fixed

- I modelli che richiedono un protocollo diverso dall'endpoint OpenAI (p.es.
  Claude e Gemini su OpenCode/OpenCode Go) vengono **nascosti** invece di fallire
  a metà traduzione.
- Il wizard di primo avvio non supportava l'**endpoint personalizzato**: ora ha
  il campo URL base e la sonda lo usa.
