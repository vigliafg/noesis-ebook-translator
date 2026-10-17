# Fournisseurs

En plus des moteurs intégrés (ChatGPT, Claude, Gemini, DeepSeek, DeepL, Google,
…), l'application peut garder **jusqu'à 4 fournisseurs configurés en même
temps**, chacun avec sa **clé API** et son **modèle**.

Ils se configurent dans **Paramètres → Fournisseurs** (ou pendant l'assistant de
bienvenue) :

- **OpenCode**, **OpenCode Go**, **OpenRouter**, **Groq**, **Mistral**,
  **xAI (Grok)**, **Together**, **Fireworks**, **DeepInfra**, **Cerebras**,
  **SambaNova**, **NVIDIA NIM**, **Moonshot (Kimi)**, **Z.AI (GLM)**,
  **Alibaba (DashScope)**, **Novita**, **HuggingFace**, plus un **endpoint
  personnalisé** (Ollama, LM Studio, vLLM, LiteLLM…).

Les listes de modèles sont récupérées **en direct** (avec un repli intégré hors
ligne) et actualisées via *Actualiser les modèles*. Le modèle choisi est **testé
automatiquement** : une courte traduction est envoyée et le résultat s'affiche
inline (`✓ modèle OK · 1,2 s`, ou `✗ raison` avec *Réessayer*).

Seuls les fournisseurs **activés** apparaissent dans le ruban/l'assistant ; le
fournisseur se choisit à chaque traduction.

Les modèles qui nécessitent un autre protocole que l'endpoint OpenAI (p. ex.
Claude et Gemini sur OpenCode Go) sont masqués : seuls les modèles traduisibles
sont listés. Si la liste en cache a plus de 24 heures, l'app l'actualise seule.

Le test du modèle se lance aussi depuis l'assistant « Traduire » ; le résultat reste visible dans le ruban sous forme de badge ✓/✗ à côté du modèle.
