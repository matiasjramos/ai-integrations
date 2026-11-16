"""Gemini adapter with a manual function-calling loop (automatic calling disabled).

Same shape as the Claude loop: call -> run requested functions -> send all
responses back in one turn -> repeat until the model answers with text.
"""

import copy
import logging

from google.genai import errors, types

from .chat import ChatError
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SPECS, ToolExecutor

logger = logging.getLogger(__name__)

_LIMIT_MSG = "Sorry, I couldn't complete that request. Could you rephrase or try again?"
_EMPTY_MSG = "Sorry, I couldn't generate an answer. Please try again."
_TRANSIENT_CODES = {429, 503}  # rate limit / overloaded: retrying elsewhere can help


def _message_for_status(code: int | None) -> str:
    """Separate config errors (fix the setup, retrying won't help) from transient ones."""
    if code == 404:
        return "Model not found. Check GEMINI_MODEL in your .env."
    if code in (401, 403):
        return "The Gemini API key is invalid or lacks access. Check GEMINI_API_KEY."
    if code in _TRANSIENT_CODES:
        return "The assistant is busy right now. Please try again shortly."
    return "The assistant had a problem. Please try again."


def _gemini_schema(schema: dict) -> dict:
    """Copy without additionalProperties: not all Gemini endpoints accept it."""
    clean = copy.deepcopy(schema)
    clean.pop("additionalProperties", None)
    return clean


def _build_tool() -> types.Tool:
    return types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=s.name, description=s.description,
            parameters_json_schema=_gemini_schema(s.input_schema),
        )
        for s in TOOL_SPECS
    ])


class GeminiChatSession:
    def __init__(self, client, model: str, executor: ToolExecutor, max_iterations: int,
                 fallback_model: str | None = None):
        self._client = client
        self._model = model
        # Tried in order; the fallback only kicks in on transient capacity errors.
        self._models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        self.last_model = model
        self._executor = executor
        self._max_iterations = max_iterations
        self._history: list[types.Content] = []
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[_build_tool()],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def send(self, user_text: str) -> str:
        checkpoint = len(self._history)
        self._history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
        )
        try:
            return self._run_loop()
        except errors.APIError as exc:
            del self._history[checkpoint:]
            code = getattr(exc, "code", None)
            # Google's status/message describe the failure and never contain the key.
            logger.error(
                "Gemini API error: code=%s status=%s model=%s message=%s",
                code, getattr(exc, "status", None), self.last_model, getattr(exc, "message", None),
            )
            raise ChatError(_message_for_status(code)) from None
        except OSError as exc:  # ConnectionError/TimeoutError are OSError subclasses
            del self._history[checkpoint:]
            logger.error("Gemini network error: %s", type(exc).__name__)
            raise ChatError("Could not reach the assistant service. Please try again.") from None

    def _run_loop(self) -> str:
        for _ in range(self._max_iterations):
            response = self._generate()
            self._track_usage(response)
            if not response.candidates or response.candidates[0].content is None:
                return _EMPTY_MSG
            self._history.append(response.candidates[0].content)  # unchanged
            calls = response.function_calls
            if not calls:
                return response.text or _EMPTY_MSG
            parts = []
            for call in calls:
                result = self._executor.execute(call.name, dict(call.args or {}))
                payload = ({"error": result.content} if result.is_error
                           else {"result": result.content})
                parts.append(types.Part.from_function_response(
                    name=call.name, response=payload))
            self._history.append(types.Content(role="tool", parts=parts))
        return _LIMIT_MSG

    def _generate(self):
        """Call the primary model; on 429/503 retry once on the fallback model.

        Capacity errors are transient and model-specific, so another model usually
        answers. Config errors (400/401/403/404) are re-raised: switching won't fix them.
        """
        for i, model in enumerate(self._models):
            self.last_model = model
            try:
                return self._client.models.generate_content(
                    model=model, contents=self._history, config=self._config,
                )
            except errors.APIError as exc:
                is_last = i == len(self._models) - 1
                if exc.code not in _TRANSIENT_CODES or is_last:
                    raise
                logger.warning("Gemini %s unavailable (code=%s); falling back to %s",
                               model, exc.code, self._models[i + 1])
        raise AssertionError("unreachable: _models is never empty")

    def _track_usage(self, response) -> None:
        meta = getattr(response, "usage_metadata", None)
        self.usage["input_tokens"] += getattr(meta, "prompt_token_count", 0) or 0
        self.usage["output_tokens"] += getattr(meta, "candidates_token_count", 0) or 0
