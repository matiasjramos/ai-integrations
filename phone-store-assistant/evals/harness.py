"""Eval harness: scripted conversations scored with deterministic checks.

Each case runs in isolation (fresh session, in-memory SQLite, LogNotifier, bundled JSON
catalog), so results never depend on earlier cases and no real lead is ever notified.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from phone_store_assistant.catalog import JsonCatalog
from phone_store_assistant.chat import ChatError
from phone_store_assistant.leads import SqliteLeadRepository
from phone_store_assistant.notifier import LogNotifier
from phone_store_assistant.tools import ToolExecutor, ToolResult

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"

CHECK_KEYS = {
    "tools_called", "tools_not_called", "lead_created", "lead_product_id",
    "reply_contains_any", "reply_not_contains", "max_reply_chars",
}
_LIST_CHECKS = {"tools_called", "tools_not_called", "reply_contains_any", "reply_not_contains"}


class CaseError(ValueError):
    """A case definition is malformed."""


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    turns: tuple[str, ...]
    checks: dict


@dataclass
class CaseResult:
    case: Case
    status: str
    reasons: list[str] = field(default_factory=list)  # failed checks, or the error
    reply: str = ""
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    is_error: bool


class RecordingExecutor:
    """Drop-in ToolExecutor that records every call, so checks can inspect the trace."""

    def __init__(self, inner: ToolExecutor):
        self._inner = inner
        self.calls: list[ToolCall] = []

    def execute(self, name: str, args: dict) -> ToolResult:
        result = self._inner.execute(name, args)
        self.calls.append(ToolCall(name, args, result.is_error))
        return result


def parse_case(raw: dict) -> Case:
    if not isinstance(raw, dict):
        raise CaseError("case must be an object")
    cid = raw.get("id")
    if not isinstance(cid, str) or not cid:
        raise CaseError("case needs a non-empty string 'id'")
    for key in ("category", "turns", "checks"):
        if key not in raw:
            raise CaseError(f"{cid}: missing '{key}'")
    turns, checks = raw["turns"], raw["checks"]
    if not isinstance(raw["category"], str) or not raw["category"]:
        raise CaseError(f"{cid}: 'category' must be a non-empty string")
    if (not isinstance(turns, list) or not turns
            or not all(isinstance(t, str) and t.strip() for t in turns)):
        raise CaseError(f"{cid}: 'turns' must be a non-empty list of strings")
    if not isinstance(checks, dict) or not checks:
        raise CaseError(f"{cid}: 'checks' must be a non-empty object")
    unknown = set(checks) - CHECK_KEYS
    if unknown:
        raise CaseError(f"{cid}: unknown checks {sorted(unknown)}")
    for key in _LIST_CHECKS & set(checks):
        value = checks[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CaseError(f"{cid}: '{key}' must be a list of strings")
    if "lead_created" in checks and not isinstance(checks["lead_created"], bool):
        raise CaseError(f"{cid}: 'lead_created' must be a boolean")
    if "lead_product_id" in checks and not isinstance(checks["lead_product_id"], str):
        raise CaseError(f"{cid}: 'lead_product_id' must be a string")
    if "max_reply_chars" in checks:
        limit = checks["max_reply_chars"]
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise CaseError(f"{cid}: 'max_reply_chars' must be a positive integer")
    return Case(cid, raw["category"], tuple(turns), checks)


def load_cases(path: str | Path) -> list[Case]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise CaseError("cases file must contain a list")
    cases = [parse_case(r) for r in raw]
    ids = [c.id for c in cases]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise CaseError(f"duplicate case ids: {duplicated}")
    return cases


def evaluate(checks: dict, reply: str, calls: list[ToolCall], leads: list) -> list[str]:
    """Return one reason per failed check (empty list means the case passed)."""
    failed: list[str] = []
    called = {c.name for c in calls}
    lowered = reply.lower()
    for name in checks.get("tools_called", []):
        if name not in called:
            failed.append(f"tool not called: {name}")
    for name in checks.get("tools_not_called", []):
        if name in called:
            failed.append(f"tool called but forbidden: {name}")
    if "lead_created" in checks and checks["lead_created"] != bool(leads):
        failed.append(f"lead_created expected {checks['lead_created']}, got {bool(leads)}")
    if "lead_product_id" in checks:
        wanted = checks["lead_product_id"]
        if wanted not in {lead.product_id for lead in leads}:
            failed.append(f"no lead for product {wanted}")
    any_of = checks.get("reply_contains_any")
    if any_of and not any(s.lower() in lowered for s in any_of):
        failed.append(f"reply contains none of {any_of}")
    for s in checks.get("reply_not_contains", []):
        if s.lower() in lowered:
            failed.append(f"reply contains forbidden text: {s!r}")
    limit = checks.get("max_reply_chars")
    if limit is not None and len(reply) > limit:
        failed.append(f"reply too long: {len(reply)} > {limit}")
    return failed


def _is_busy(exc: ChatError) -> bool:
    return "busy" in str(exc).lower()


def run_case(
    case: Case,
    session_factory: Callable[[RecordingExecutor], object],
    catalog_path: str | Path,
    retries: int = 2,
    retry_wait: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> CaseResult:
    """Run one case. A busy provider restarts the whole case (fresh state) up to `retries`
    times; any ChatError that survives is ERROR (infrastructure), never FAIL (quality)."""
    attempt = 0
    while True:
        leads = SqliteLeadRepository(":memory:")
        executor = RecordingExecutor(
            ToolExecutor(JsonCatalog(catalog_path), leads, LogNotifier())
        )
        reply = ""
        try:
            session = session_factory(executor)
            for turn in case.turns:
                reply = session.send(turn)
        except ChatError as exc:
            if _is_busy(exc) and attempt < retries:
                attempt += 1
                sleep(retry_wait)
                continue
            return CaseResult(case, ERROR, [str(exc)], tools=[c.name for c in executor.calls])
        reasons = evaluate(case.checks, reply, executor.calls, leads.list_recent())
        return CaseResult(case, FAIL if reasons else PASS, reasons, reply,
                          [c.name for c in executor.calls])
