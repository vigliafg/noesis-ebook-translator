from .base import Base
from .google import (
    GoogleFreeTranslateNew, GoogleFreeTranslateHtml, GoogleFreeTranslate,
    GoogleBasicTranslate, GoogleBasicTranslateADC, GoogleAdvancedTranslate,
    GeminiTranslate)
from .openai import ChatgptTranslate
from .anthropic import ClaudeTranslate
from .deepl import DeeplTranslate, DeeplProTranslate, DeeplFreeTranslate
from .youdao import YoudaoTranslate
from .baidu import BaiduTranslate
from .microsoft import MicrosoftEdgeTranslate, AzureChatgptTranslate
from .deepseek import DeepseekTranslate
from .openrouter import OpenRouterTranslate

# NOTE (Noesis override): the upstream plugin registers the full engine set here;
# the fork this app is based on had dropped the ChatGPT/Azure/Gemini/Claude
# entries. This project wants *all* plugin engines available, so they are
# restored. This is the only engine file that is intentionally not verbatim.
builtin_engines: tuple[type[Base], ...] = (
    GoogleFreeTranslateNew, GoogleFreeTranslateHtml, GoogleFreeTranslate,
    GoogleBasicTranslate, GoogleBasicTranslateADC, GoogleAdvancedTranslate,
    GeminiTranslate, ChatgptTranslate, ClaudeTranslate, AzureChatgptTranslate,
    DeepseekTranslate, OpenRouterTranslate, DeeplTranslate, DeeplProTranslate,
    DeeplFreeTranslate, MicrosoftEdgeTranslate, YoudaoTranslate,
    BaiduTranslate)
