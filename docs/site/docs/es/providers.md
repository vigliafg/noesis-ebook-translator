# Proveedores

Además de los motores integrados (ChatGPT, Claude, Gemini, DeepSeek, DeepL,
Google, …), la app puede mantener **hasta 4 proveedores configurados a la vez**,
cada uno con su **clave de API** y su **modelo**.

Se configuran en **Ajustes → Proveedores** (o durante el asistente inicial):

- **OpenCode**, **OpenCode Go**, **OpenRouter**, **Groq**, **Mistral**,
  **xAI (Grok)**, **Together**, **Fireworks**, **DeepInfra**, **Cerebras**,
  **SambaNova**, **NVIDIA NIM**, **Moonshot (Kimi)**, **Z.AI (GLM)**,
  **Alibaba (DashScope)**, **Novita**, **HuggingFace**, más un **endpoint
  personalizado** (Ollama, LM Studio, vLLM, LiteLLM…).

Las listas de modelos se obtienen **en vivo** (con respaldo incluido para uso sin
conexión) y se actualizan con *Actualizar modelos* (un proveedor), *Actualizar todas las listas* en Ajustes, o desde el asistente inicial. El modelo elegido se **prueba
automáticamente**: se envía una traducción breve y el resultado aparece inline
(`✓ modelo OK · 1,2 s`, o `✗ motivo` con *Reintentar*).

Solo los proveedores **activados** aparecen en la cinta/asistente; el proveedor se
elige en cada traducción.

Los modelos que necesitan otro protocolo distinto del endpoint OpenAI (p. ej.
Claude y Gemini en OpenCode Go) se ocultan: solo se listan los traducibles. Si la
lista en caché tiene más de 24 horas, la app la actualiza sola.

La prueba del modelo también se lanza desde el asistente «Traducir»; el resultado queda visible en la cinta como insignia ✓/✗ junto al modelo.
