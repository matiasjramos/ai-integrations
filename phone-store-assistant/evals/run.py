"""Run the eval cases against the configured provider.

Usage (from phone-store-assistant/): python -m evals.run [--provider gemini|claude]
[--delay SECONDS] [--case ID] [--category NAME] [--retries N]
"""

import argparse
import dataclasses
import sys
import time
from collections import defaultdict
from pathlib import Path

from phone_store_assistant.chat import create_chat_session
from phone_store_assistant.config import VALID_PROVIDERS, load_settings

from .harness import ERROR, FAIL, PASS, CaseResult, load_cases, run_case

CASES_PATH = Path(__file__).with_name("cases.json")


def _rate(passed: int, failed: int) -> str:
    # ERROR cases are infrastructure noise and are not part of the quality rate.
    return f"{100 * passed // (passed + failed)}%" if passed + failed else "n/a"


def summarize(results: list[CaseResult]) -> tuple[list[str], int, int, int]:
    """Per-category table lines plus (passed, failed, errors)."""
    by_cat: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_cat[r.case.category].append(r)
    lines = [f"{'category':<22}{'pass':>5}{'fail':>6}{'error':>7}{'rate':>7}"]
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(r.status == PASS for r in rs)
        f = sum(r.status == FAIL for r in rs)
        e = sum(r.status == ERROR for r in rs)
        lines.append(f"{cat:<22}{p:>5}{f:>6}{e:>7}{_rate(p, f):>7}")
    passed = sum(r.status == PASS for r in results)
    failed = sum(r.status == FAIL for r in results)
    errors = sum(r.status == ERROR for r in results)
    return lines, passed, failed, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--provider", choices=sorted(VALID_PROVIDERS),
                        help="override LLM_PROVIDER")
    parser.add_argument("--delay", type=float, default=4.0,
                        help="seconds between cases (free-tier pacing)")
    parser.add_argument("--case", help="run only this case id")
    parser.add_argument("--category", help="run only this category")
    parser.add_argument("--retries", type=int, default=2,
                        help="retries per case when the provider is busy")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.provider:
        settings = dataclasses.replace(settings, llm_provider=args.provider)
    cases = [c for c in load_cases(CASES_PATH)
             if (not args.case or c.id == args.case)
             and (not args.category or c.category == args.category)]
    if not cases:
        print("No cases match the filters.")
        return 2

    print(f"Provider: {settings.llm_provider} | cases: {len(cases)}")
    results: list[CaseResult] = []
    for i, case in enumerate(cases):
        if i:
            time.sleep(args.delay)
        result = run_case(
            case,
            lambda executor: create_chat_session(settings, executor),
            settings.catalog_json_path,
            retries=args.retries,
        )
        results.append(result)
        print(f"[{result.status}] {case.category}/{case.id}")
        for reason in result.reasons:
            print(f"    - {reason}")

    lines, passed, failed, errors = summarize(results)
    print("\n" + "\n".join(lines))
    print(f"\nTotal: {passed} passed, {failed} failed, {errors} errors "
          f"(pass rate {_rate(passed, failed)}, errors excluded)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
