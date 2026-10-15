from .claude import ClaudeProvider
from .codex import CodexProvider
from .gemini import GeminiProvider

PROVIDERS = {provider.id: provider for provider in (ClaudeProvider(), CodexProvider(), GeminiProvider())}
