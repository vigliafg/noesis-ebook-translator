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
