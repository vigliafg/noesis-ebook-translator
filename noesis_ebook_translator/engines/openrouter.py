import json
import os
from calibre.utils.localization import _
from .openai import ChatgptTranslate
from ..lib.utils import log, request


def _parse_json_object(text):
    """Best-effort JSON object from a model reply.

    Models wrap the object in prose or code fences, and a truncated reply loses
    its closing brace. Strip the fences, cut to the outer braces, then repair a
    missing tail (``{"0": "a", "1": "b"``) by closing the open string/brace so
    the segments that *did* arrive are usable instead of losing the whole batch.
    """
    if not isinstance(text, str):
        return None
    clean = text.strip()
    if "```json" in clean:
        clean = clean.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in clean:
        clean = clean.split("```", 1)[1].split("```", 1)[0].strip()
    start = clean.find('{')
    if start == -1:
        return None
    end = clean.rfind('}')
    candidate = clean[start:end + 1] if end != -1 else clean[start:]
    try:
        return json.loads(candidate)
    except ValueError:
        pass
    # Truncated reply: only the closing brace is missing -> just close it.
    try:
        return json.loads(candidate.rstrip().rstrip(',') + '}')
    except ValueError:
        pass
    # Otherwise the last pair was cut mid-string: drop pairs from the end until
    # what is left parses. A half-translated string must never be accepted.
    cut = candidate.rstrip().rstrip('}')
    comma = cut.rfind(',')
    while comma != -1:
        try:
            return json.loads(cut[:comma] + '}')
        except ValueError:
            comma = cut.rfind(',', 0, comma)
    return None


class OpenRouterTranslate(ChatgptTranslate):
    name = 'OpenRouter'
    alias = 'OpenRouter'
    endpoint = 'https://openrouter.ai/api/v1/chat/completions'

    # OpenRouter is a generic gateway with no vendor-tuned value; 1.0 made
    # short, context-free segments drift (a chapter title "Stroke" came out as
    # both "Ictus" and "Colpo"). Keep it low and let the genre addendum decide
    # the style. Per-engine/user settings can still override it.
    temperature = 0.2

    #: OpenRouter accepts the ``reasoning`` object, so the caller may switch the
    #: model's internal reasoning off. Opt-in on purpose: a vendor that does not
    #: know the field answers 400, so no engine gets it unless it says so.
    reasoning_supported = True

    # No persona of its own: the neutral prompt of ``ChatgptTranslate`` is the
    # right default for any genre. The per-book specialisation comes from the
    # app's genre analysis (style addendum appended by ``book.translate_epub``).
    # A hard-coded *literary* prompt here made short segments of a medical
    # textbook come out as "colpo" (blow) instead of "ictus" (stroke).

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
        }
        # A batch needs room for every segment *and* the JSON syntax: the old
        # fixed 8192 came back truncated (finish_reason "length") as soon as the
        # model also reasoned, and then the whole JSON was unparseable.
        self.batch = True
        try:
            self.apply_max_tokens(
                data, json.dumps(to_translate, ensure_ascii=False))
        finally:
            self.batch = False
        self.apply_reasoning(data)

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
            
            # Using ChatgptTranslate.get_result to extract content from OpenRouter's OpenAI-compatible response.
            # The batch body is never streamed (``data`` has no ``stream`` key),
            # so it must be parsed as a plain JSON response: ``get_result`` would
            # take the streaming path whenever the engine default is
            # ``stream=True`` (which it is) and fail with "'str' object has no
            # attribute 'readline'".
            streamed = self.stream
            self.stream = False
            try:
                result_text = self.get_result(response)
            finally:
                self.stream = streamed
            if not result_text:
                return None
                
            # Parse the JSON from the model
            try:
                translated_data = _parse_json_object(result_text)
                if not isinstance(translated_data, dict):
                    raise ValueError('reply is not a JSON object')

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
