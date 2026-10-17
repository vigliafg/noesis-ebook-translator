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
  pulsante *Aggiorna modelli* e aggiornamento automatico dopo 24 ore.
- **Test automatico del modello**: una traduzione breve verifica il modello
  scelto e l'esito compare inline (`✓ Modello OK · 1,2s` oppure il motivo);
  l'ultimo esito resta visibile nel ribbon come **badge ✓/✗**.
- `tools/fetch_provider_catalog.py` per rigenerare lo snapshot (con `--check`)
  e una workflow settimanale che segnala quando è invecchiato.

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
- `tools/fetch_provider_catalog.py --check` confrontava anche `generated_at`,
  quindi falliva sempre: ora confronta solo modelli e rotte e indica i provider
  cambiati.
