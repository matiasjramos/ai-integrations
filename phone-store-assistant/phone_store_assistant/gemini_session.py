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


def _message_for_status(code: int | None) -> str:
    """Separate config errors (fix the setup, retrying won't help) from transient ones."""
    if code == 404:
        return "Model not found. Check GEMINI_MODEL in your .env."
    if code in (401, 403):
        return "The Gemini API key is invalid or lacks access. Check GEMINI_API_KEY."
    if code == 429:
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
    def __init__(self, client, model: str, executor: ToolExecutor, max_iterations: int):
        self._client = client
        self._model = model
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
            logger.error("Gemini API error: code=%s model=%s", code, self._model)
            raise ChatError(_message_for_status(code)) from None
        except OSError as exc:  # ConnectionError/TimeoutError are OSError subclasses
            del self._history[checkpoint:]
            logger.error("Gemini network error: %s", type(exc).__name__)
            raise ChatError("Could not reach the assistant service. Please try again.") from None

    def _run_loop(self) -> str:
        for _ in range(self._max_iterations):
            response = self._client.models.generate_content(
                model=self._model, contents=self._history, config=self._config,
            )
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

    def _track_usage(self, response) -> None:
        meta = getattr(response, "usage_metadata", None)
        self.usage["input_tokens"] += getattr(meta, "prompt_token_count", 0) or 0
        self.usage["output_tokens"] += getattr(meta, "candidates_token_count", 0) or 0
