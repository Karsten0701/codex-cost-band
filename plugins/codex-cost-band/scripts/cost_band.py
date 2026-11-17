#!/usr/bin/env python3
"""Read the newest Codex CLI rollout log and print a usage summary."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# USD per million tokens. This is an API-equivalent estimate, not subscription billing.
PRICES = {
    "gpt-6-astra": (5.0, 0.5, 25.0),
    "gpt-6.1-sol": (1.0, 0.05, 5.0),
    "gpt-6.1-terra": (0.5, 0.025, 2.5),
    "gpt-6-luna": (0.05, 0.005, 0.25),
    "gpt-5.3-codex": (1.75, 0.175, 14.0),
}


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def find_latest_session(root: Path) -> Path | None:
    sessions = root / "sessions"
    if not sessions.is_dir():
        return None
    candidates = list(sessions.rglob("rollout-*.jsonl"))
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def read_usage(path: Path) -> dict:
    latest = None
    last = None
    turns = 0
    model = None
    context_window = None
    timestamps = []
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = row.get("timestamp")
        if timestamp:
            try:
                timestamps.append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
            except ValueError:
                pass
        payload = row.get("payload") or {}
        if row.get("type") == "task_started":
            turns += 1
        if row.get("type") == "turn_context":
            model = payload.get("model") or payload.get("model_id") or model
        if row.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        info = payload.get("info") or {}
        context_window = info.get("model_context_window") or context_window
        cumulative = info.get("total_token_usage")
        if cumulative:
            latest = cumulative
            last = info.get("last_token_usage") or last
            model = payload.get("model") or payload.get("model_id") or model
    return {
        "total": latest or {},
        "last": last or {},
        "turns": turns,
        "model": model,
        "context_window": context_window,
        "timestamps": timestamps,
    }


def money(value: float) -> str:
    return f"${value:.4f}"


def estimate(usage: dict, model: str | None) -> float | None:
    if not model:
        return None
    rates = PRICES.get(model.lower())
    if not rates:
        return None
    total = usage.get("total", {})
    input_tokens = int(total.get("input_tokens", 0) or 0)
    cached_tokens = int(total.get("cached_input_tokens", 0) or 0)
    output_tokens = int(total.get("output_tokens", 0) or 0)
    regular_input = max(input_tokens - cached_tokens, 0)
    input_rate, cached_rate, output_rate = rates
    return (
        regular_input * input_rate
        + cached_tokens * cached_rate
        + output_tokens * output_rate
    ) / 1_000_000


def main() -> int:
    path = find_latest_session(codex_home())
    if path is None:
        print("No Codex CLI session log found under CODEX_HOME/sessions.")
        return 1

    usage = read_usage(path)
    total = usage["total"]
    if not total:
        print(f"No token usage found in the latest session: {path.name}")
        return 1

    input_tokens = int(total.get("input_tokens", 0) or 0)
    cached_tokens = int(total.get("cached_input_tokens", 0) or 0)
    output_tokens = int(total.get("output_tokens", 0) or 0)
    all_tokens = int(total.get("total_tokens", input_tokens + output_tokens) or 0)
    model = usage["model"]
    cost = estimate(usage, model)
    times = usage["timestamps"]
    duration = max((times[-1] - times[0]).total_seconds(), 0) if len(times) > 1 else 0
    minutes, seconds = divmod(round(duration), 60)

    print(f"Codex session: {path.stem.removeprefix('rollout-')}")
    print(f"Model: {model or 'unknown'}")
    print(f"Messages: {usage['turns']}")
    print(f"Time: {minutes}m {seconds}s (session log span)")
    print(f"Tokens: {all_tokens:,} total | {input_tokens:,} input ({cached_tokens:,} cached) | {output_tokens:,} output")
    if usage["context_window"]:
        print(f"Context window: {int(usage['context_window']):,} tokens")
    if cost is None:
        print("API-equivalent cost: unavailable (model is unknown or has no bundled price)")
    else:
        last_cost = estimate({"total": usage["last"]}, model)
        print(f"API-equivalent cost: {money(cost)}")
        if last_cost is not None:
            print(f"Last response estimate: {money(last_cost)}")
    print("Note: API-equivalent estimate only; Codex subscription usage is billed separately.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
