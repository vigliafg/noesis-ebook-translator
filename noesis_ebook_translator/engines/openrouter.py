import json
import os
from calibre.utils.localization import _
from .openai import ChatgptTranslate
from ..lib.utils import log, request

class OpenRouterTranslate(ChatgptTranslate):
    name = 'OpenRouter'
    alias = 'OpenRouter'
    endpoint = 'https://openrouter.ai/api/v1/chat/completions'
    
    # Specialized Italian literary translator prompt
    prompt = (
        "Sei un traduttore letterario esperto dall'inglese all'italiano, con profonda conoscenza della letteratura anglosassone. "
        "Il tuo obiettivo è produrre traduzioni accurate, fluide e idiomatiche che preservino fedeltà semantica, stile e tono originale. "
        "Usa un italiano colto ed elegante. Mantieni invariati paragrafi, dialoghi e capitoli. "
        "Rispondi SOLO con la traduzione pura, senza introduzioni o spiegazioni."
    )

    models: list[str] = [
        'deepseek/deepseek-chat', 
        'google/gemini-flash-1.5', 
        'openai/gpt-4o-mini',
        'meta-llama/llama-3.1-70b-instruct'
    ]
    model: str | None = models[0]

    def __init__(self):
        super().__init__()
        self.model = self.config.get('model', self.model)
        # Note: ChatgptTranslate.get_headers uses self.api_key which is set in GenAI.__init__ via self.config.get('api_keys')
        # We ensure OpenRouter specific headers are included.

    def get_headers(self):
        headers = super().get_headers()
        headers.update({
            'HTTP-Referer': 'https://github.com/vigliafg/Ebook-Translator-Calibre-Plugin',
            'X-Title': 'Ebook-Translator-Calibre-Plugin',
        })
        return headers

    def get_body(self, text):
        body_json = json.loads(super().get_body(text))
        body_json['max_tokens'] = 8192
        # Add reasoning_effort: "low" for supported models
        if self.model and ("gpt-oss" in self.model or "o1" in self.model or "deepseek-reasoner" in self.model):
            body_json["reasoning_effort"] = "low"
        return json.dumps(body_json)

    def translate_batch(self, segments):
        """
        High-speed batch translation using ID-indexed JSON to ensure perfect alignment.
        """
        to_translate = {str(i): seg for i, seg in enumerate(segments)}
        
        batch_system_prompt = self.get_prompt() + (
            "\n\nCRITICAL: Return a JSON object where each key corresponds to the input ID "
            "and the value is the translated string. Return ONLY the JSON object. "
            "Example: {\"0\": \"traduzione 1\", \"1\": \"traduzione 2\"}"
        )
        
        messages = [
            {"role": "system", "content": batch_system_prompt},
            {"role": "user", "content": json.dumps(to_translate, ensure_ascii=False)}
        ]
        
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192,
        }
        
        # reasoning_effort for batch too
        if self.model and ("gpt-oss" in self.model or "o1" in self.model or "deepseek-reasoner" in self.model):
            data["reasoning_effort"] = "low"
            
        try:
            params = {
                'url': self.endpoint,
                'data': json.dumps(data),
                'headers': self.get_headers(),
                'method': 'POST',
                'timeout': 180, 
            }
            response = request(**params)
            
            # Using ChatgptTranslate.get_result to extract content from OpenRouter's OpenAI-compatible response
            result_text = self.get_result(response)
            if not result_text:
                return None
                
            # Parse the JSON from the model
            try:
                # Robust extraction of JSON from model output
                clean_json = result_text
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                else:
                    start_idx = clean_json.find('{')
                    end_idx = clean_json.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        clean_json = clean_json[start_idx:end_idx+1]
                
                translated_data = json.loads(clean_json)
                
                results = []
                for i in range(len(segments)):
                    idx_str = str(i)
                    if idx_str in translated_data:
                        results.append(str(translated_data[idx_str]).strip())
                    else:
                        # Fallback for missing ID in JSON
                        results.append("") 
                
                return results
            except Exception as e:
                log.error(f"Failed to parse JSON batch response: {e}")
                return None
                
        except Exception as e:
            log.error(f"Batch request failed: {e}")
            return None
