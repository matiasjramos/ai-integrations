"""ChatSession port and provider factory.

Each adapter owns its native history format and manual tool loop; the UI only
sees send(text) -> reply.
"""

from typing import Protocol

from .config import Settings
from .tools import ToolExecutor


class ChatError(Exception):
    """Unrecoverable provider error. The message is safe to show to the user.

    `transient` marks capacity errors (rate limit / overloaded) where retrying later can help.
    """

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class ChatSession(Protocol):
    def send(self, user_text: str) -> str: ...


def create_chat_session(settings: Settings, executor: ToolExecutor, client=None) -> ChatSession:
    # Lazy imports: only the selected provider's SDK is needed at runtime.
    if settings.llm_provider == "claude":
        import anthropic

        from .claude_session import ClaudeChatSession

        return ClaudeChatSession(
            client or anthropic.Anthropic(), settings.anthropic_model, settings.effort,
            executor, settings.max_tool_iterations,
        )
    if settings.llm_provider == "gemini":
        from google import genai

        from .gemini_session import GeminiChatSession

        return GeminiChatSession(
            client or genai.Client(), settings.gemini_model, executor,
            settings.max_tool_iterations,
            fallback_model=settings.gemini_fallback_model,
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")
