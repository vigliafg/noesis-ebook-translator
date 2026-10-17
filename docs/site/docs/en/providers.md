# Providers

Besides the built-in engines (ChatGPT, Claude, Gemini, DeepSeek, DeepL, Google,
…) the app can keep **up to 4 providers configured at the same time**, each with
its own **API key** and **model**.

Configure them in **Settings → Providers** (or during the welcome wizard):

- **OpenCode**, **OpenCode Go**, **OpenRouter**, **Groq**, **Mistral**,
  **xAI (Grok)**, **Together**, **Fireworks**, **DeepInfra**, **Cerebras**,
  **SambaNova**, **NVIDIA NIM**, **Moonshot (Kimi)**, **Z.AI (GLM)**,
  **Alibaba (DashScope)**, **Novita**, **HuggingFace**, plus a **custom
  endpoint** (Ollama, LM Studio, vLLM, LiteLLM…).

Model lists are fetched **live** from the provider (with a bundled fallback for
offline use) and refreshed with *Refresh models*. The chosen model is **tested
automatically**: a short translation is sent and the result appears inline
(`✓ model OK · 1.2s`, or `✗ reason` with *Retry*).

Only the **enabled** providers appear in the ribbon/wizard, and you pick the one
to use at every translation.

Models that need a different protocol than the OpenAI endpoint (e.g. Claude and
Gemini on OpenCode Go) are hidden: only the translatable ones are listed. When
the cached list is older than 24 hours, the app refreshes it automatically.

The model test also runs from the Translate wizard, and the outcome stays visible in the ribbon as a ✓/✗ badge next to the model.
