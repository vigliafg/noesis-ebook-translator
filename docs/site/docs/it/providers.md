# Provider

Oltre ai motori integrati (ChatGPT, Claude, Gemini, DeepSeek, DeepL, Google, …)
l'app può tenere **fino a 4 provider configurati contemporaneamente**, ognuno con
la **propria chiave API** e il **proprio modello**.

Si configurano in **Impostazioni → Provider** (o nel wizard di primo avvio):

- **OpenCode**, **OpenCode Go**, **OpenRouter**, **Groq**, **Mistral**,
  **xAI (Grok)**, **Together**, **Fireworks**, **DeepInfra**, **Cerebras**,
  **SambaNova**, **NVIDIA NIM**, **Moonshot (Kimi)**, **Z.AI (GLM)**,
  **Alibaba (DashScope)**, **Novita**, **HuggingFace**, più un **endpoint
  personalizzato** (Ollama, LM Studio, vLLM, LiteLLM…).

Le liste modelli vengono lette **live** dal provider (con fallback incluso per
l'uso offline) e aggiornate con *Aggiorna modelli*. Il modello scelto viene
**testato automaticamente**: viene inviata una traduzione breve e l'esito compare
inline (`✓ modello OK · 1,2s`, oppure `✗ motivo` con *Riprova*).

Solo i provider **abilitati** compaiono nel ribbon/wizard e il provider si sceglie
a ogni traduzione.

I modelli che richiedono un protocollo diverso dall'endpoint OpenAI (p.es. Claude
e Gemini su OpenCode Go) vengono nascosti: restano solo quelli traducibili. Se la
lista in cache ha più di 24 ore, l'app la riaggiorna da sola.

Il test del modello parte anche dal wizard «Traduci»: l'esito resta visibile nel ribbon come badge ✓/✗ accanto al modello.
