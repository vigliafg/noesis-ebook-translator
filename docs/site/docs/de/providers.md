# Anbieter

Neben den eingebauten Engines (ChatGPT, Claude, Gemini, DeepSeek, DeepL, Google,
…) kann die App **bis zu 4 Anbieter gleichzeitig** verwalten, jeder mit eigenem
**API-Schlüssel** und **Modell**.

Konfiguration unter **Einstellungen → Anbieter** (oder im Willkommens-Assistenten):

- **OpenCode**, **OpenCode Go**, **OpenRouter**, **Groq**, **Mistral**,
  **xAI (Grok)**, **Together**, **Fireworks**, **DeepInfra**, **Cerebras**,
  **SambaNova**, **NVIDIA NIM**, **Moonshot (Kimi)**, **Z.AI (GLM)**,
  **Alibaba (DashScope)**, **Novita**, **HuggingFace**, plus ein **eigener
  Endpunkt** (Ollama, LM Studio, vLLM, LiteLLM…).

Modelllisten werden **live** geladen (mit mitgeliefertem Offline-Fallback) und
über *Modelle aktualisieren* erneuert. Das gewählte Modell wird **automatisch
getestet**: eine kurze Übersetzung wird gesendet und das Ergebnis erscheint inline
(`✓ Modell OK · 1,2 s` oder `✗ Grund` mit *Wiederholen*).

Nur **aktivierte** Anbieter erscheinen im Ribbon/Assistenten; der Anbieter wird
bei jeder Übersetzung gewählt.

Modelle, die ein anderes Protokoll als den OpenAI-Endpunkt benötigen (z. B.
Claude und Gemini bei OpenCode Go), werden ausgeblendet: es werden nur die
übersetzbaren aufgeführt. Ist die zwischengespeicherte Liste älter als 24
Stunden, aktualisiert die App sie selbst.
