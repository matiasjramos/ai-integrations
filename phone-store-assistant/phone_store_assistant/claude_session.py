"""Claude adapter with a manual tool-use loop (no SDK tool runner), so every step is visible.

Loop: send history -> if stop_reason == "tool_use", run each tool and return ALL
results in one user message -> repeat until the model ends its turn.
"""

import json
import logging

import anthropic

from .chat import ChatError
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SPECS, ToolExecutor

logger = logging.getLogger(__name__)

_USAGE_FIELDS = ("input_tokens", "output_tokens",
                 "cache_read_input_tokens", "cache_creation_input_tokens")
_LIMIT_MSG = "Sorry, I couldn't complete that request. Could you rephrase or try again?"
_REFUSAL_MSG = "Sorry, I can't help with that request."
_TOOLS = [
    {"name": s.name, "description": s.description, "input_schema": s.input_schema,
     "strict": True}
    for s in TOOL_SPECS
]


class ClaudeChatSession:
    def __init__(self, client, model: str, effort: str, executor: ToolExecutor,
                 max_iterations: int):
        self._client = client
        self._model = model
        self._effort = effort
        self._executor = executor
        self._max_iterations = max_iterations
        self._history: list[dict] = []
        self.usage = dict.fromkeys(_USAGE_FIELDS, 0)

    def send(self, user_text: str) -> str:
        checkpoint = len(self._history)
        self._history.append({"role": "user", "content": user_text})
        try:
            return self._run_loop()
        except anthropic.RateLimitError:
            self._rollback(checkpoint)
            raise ChatError("The assistant is busy right now. Please try again shortly.") from None
        except anthropic.APIConnectionError:
            self._rollback(checkpoint)
            raise ChatError("Could not reach the assistant service. Please try again.") from None
        except anthropic.AuthenticationError:
            self._rollback(checkpoint)
            raise ChatError("The assistant is not configured correctly (API key).") from None
        except anthropic.APIStatusError as exc:
            self._rollback(checkpoint)
            logger.error("Anthropic API error: status=%s", exc.status_code)
            raise ChatError("The assistant had a problem. Please try again.") from None

    def _rollback(self, checkpoint: int) -> None:
        del self._history[checkpoint:]

    def _run_loop(self) -> str:
        for _ in range(self._max_iterations):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=self._history,
                output_config={"effort": self._effort},
                cache_control={"type": "ephemeral"},  # auto-caches the stable prefix
            )
            self._track_usage(response)
            # Full content list unchanged: thinking blocks must be passed back.
            self._history.append({"role": "assistant", "content": response.content})
            reason = response.stop_reason
            if reason == "tool_use":
                self._history.append({"role": "user", "content": self._run_tools(response)})
            elif reason == "pause_turn":
                continue
            elif reason == "refusal":
                return _REFUSAL_MSG
            elif reason == "max_tokens":
                return (self._text(response) + "\n\n(The reply was cut short.)").strip()
            else:  # end_turn
                return self._text(response)
        return _LIMIT_MSG

    def _run_tools(self, response) -> list[dict]:
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = self._executor.execute(block.name, block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result.content),
                "is_error": result.is_error,
            })
        return results

    @staticmethod
    def _text(response) -> str:
        return "".join(b.text for b in response.content if b.type == "text")

    def _track_usage(self, response) -> None:
        usage = getattr(response, "usage", None)
        for field in _USAGE_FIELDS:
            self.usage[field] += getattr(usage, field, 0) or 0
