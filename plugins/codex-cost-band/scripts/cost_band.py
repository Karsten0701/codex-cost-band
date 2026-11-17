#!/usr/bin/env python3
"""Read the newest Codex CLI rollout log and print a usage summary."""

from __future__ import annotations

import json
import os
import argparse
import sys
import time
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


def find_session(root: Path, session_id: str | None = None) -> Path | None:
    sessions = root / "sessions"
    if not sessions.is_dir():
        return None
    candidates = list(sessions.rglob("rollout-*.jsonl"))
    if session_id:
        candidates = [path for path in candidates if path.stem.endswith(session_id)]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def read_usage(path: Path) -> dict:
    latest = None
    last = None
    turns = 0
    model = None
    context_window = None
    first_timestamp = None
    last_timestamp = None
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = row.get("timestamp")
        if timestamp:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                first_timestamp = first_timestamp or parsed
                last_timestamp = parsed
            except ValueError:
                pass
        payload = row.get("payload") or {}
        if row.get("type") == "event_msg" and payload.get("type") == "task_started":
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
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
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


def report(path: Path) -> str:
    usage = read_usage(path)
    total = usage["total"]
    if not total:
        return f"No token usage found in the latest session: {path.name}"

    input_tokens = int(total.get("input_tokens", 0) or 0)
    cached_tokens = int(total.get("cached_input_tokens", 0) or 0)
    output_tokens = int(total.get("output_tokens", 0) or 0)
    all_tokens = int(total.get("total_tokens", input_tokens + output_tokens) or 0)
    model = usage["model"]
    cost = estimate(usage, model)
    start, end = usage["first_timestamp"], usage["last_timestamp"]
    duration = max((end - start).total_seconds(), 0) if start and end else 0
    minutes, seconds = divmod(round(duration), 60)

    lines = [
        f"Codex session: {path.stem.removeprefix('rollout-')}",
        f"Model: {model or 'unknown'}",
        f"Messages: {usage['turns']}",
        f"Time: {minutes}m {seconds}s (session log span)",
        f"Tokens: {all_tokens:,} total | {input_tokens:,} input ({cached_tokens:,} cached) | {output_tokens:,} output",
    ]
    if usage["context_window"]:
        lines.append(f"Context window: {int(usage['context_window']):,} tokens")
    if cost is None:
        lines.append("API-equivalent cost: unavailable (model is unknown or has no bundled price)")
    else:
        last_cost = estimate({"total": usage["last"]}, model)
        lines.append(f"API-equivalent cost: {money(cost)}")
        if last_cost is not None:
            lines.append(f"Last response estimate: {money(last_cost)}")
    lines.append("API-equivalent estimate only; Codex subscription usage is billed separately.")
    return "\n".join(lines)


def watch(session_id: str | None, refresh: float) -> int:
    if refresh <= 0:
        print("Refresh interval must be greater than zero.", file=sys.stderr)
        return 2
    root = codex_home()
    fixed_session = find_session(root, session_id) if session_id else None
    if session_id and fixed_session is None:
        print(f"No session found matching {session_id!r}.", file=sys.stderr)
        return 1

    last_change = object()
    try:
        while True:
            path = fixed_session or find_session(root)
            if path is None:
                content = "No Codex CLI session found. Waiting for one..."
                change = None
            else:
                stat = path.stat()
                change = (path, stat.st_mtime_ns, stat.st_size)
                content = report(path)
            if change != last_change:
                if sys.stdout.isatty():
                    print("\033[2J\033[H", end="")
                print("Codex Cost Band — Live")
                print(content)
                print(f"\nRefreshing every {refresh:g}s · Ctrl+C to stop")
                last_change = change
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report or watch local Codex session usage.")
    subparsers = parser.add_subparsers(dest="command")
    watch_parser = subparsers.add_parser("watch", help="continuously display a Codex session")
    watch_parser.add_argument("--session", help="session ID to watch instead of the newest session")
    watch_parser.add_argument("--refresh", type=float, default=1.0, help="refresh interval in seconds (default: 1)")
    args = parser.parse_args(argv)

    if args.command == "watch":
        return watch(args.session, args.refresh)

    path = find_session(codex_home())
    if path is None:
        print("No Codex CLI session log found under CODEX_HOME/sessions.")
        return 1
    print(report(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
