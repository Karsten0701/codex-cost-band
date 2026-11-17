#!/usr/bin/env python3
"""Read the newest Codex CLI rollout log and print a usage summary."""

from __future__ import annotations

import json
import os
import argparse
import sys
import time
from datetime import datetime, timezone
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
    rate_snapshot_timestamp = None
    rate_limits = None
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = row.get("timestamp")
        parsed_timestamp = None
        if timestamp:
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                parsed_timestamp = parsed
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
        if payload.get("rate_limits"):
            rate_limits = payload["rate_limits"]
            rate_snapshot_timestamp = parsed_timestamp or rate_snapshot_timestamp
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
        "rate_limits": rate_limits,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "rate_snapshot_timestamp": rate_snapshot_timestamp,
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


def elapsed_label(seconds: float) -> str:
    minutes, seconds = divmod(max(round(seconds), 0), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"


def rate_window(name: str, window: dict, colors: dict[str, str], reset_at: int | None) -> list[str]:
    used = window.get("used_percent")
    if used is None:
        return [f"  {name:<8} Usage unavailable"]
    used = min(max(float(used), 0), 100)
    remaining = max(100 - used, 0)
    filled = round(used / 5)
    color = colors["green"] if used < 65 else colors["yellow"] if used < 90 else colors["red"]
    bar = f"{color}{'█' * filled}{colors['muted']}{'░' * (20 - filled)}{colors['reset']}"
    line = f"  {name:<8} {used:>3.0f}% used  {bar}  {remaining:>3.0f}% left"
    lines = [line]
    if reset_at:
        seconds_left = max(reset_at - int(time.time()), 0)
        lines.append(f"           resets in {elapsed_label(seconds_left)}")
    return lines


def live_screen(path: Path | None, usage: dict | None, refresh: float) -> str:
    color_enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    colors = {
        "reset": "\033[0m" if color_enabled else "",
        "bold": "\033[1m" if color_enabled else "",
        "cyan": "\033[96m" if color_enabled else "",
        "green": "\033[92m" if color_enabled else "",
        "yellow": "\033[93m" if color_enabled else "",
        "red": "\033[91m" if color_enabled else "",
        "muted": "\033[90m" if color_enabled else "",
    }
    reset, bold, cyan, muted = (colors[key] for key in ("reset", "bold", "cyan", "muted"))
    divider = f"{muted}{'─' * 72}{reset}"
    now = datetime.now().astimezone()
    lines = [f"{bold}{cyan}  CODEX COST BAND{reset}  {muted}LIVE  ·  updated {now:%H:%M:%S}{reset}", divider]
    if path is None or usage is None:
        lines.extend(["  Waiting for a local Codex session…", divider, f"  Refreshing every {refresh:g}s  ·  Ctrl+C to stop"])
        return "\n".join(lines)

    total = usage["total"]
    input_tokens = int(total.get("input_tokens", 0) or 0)
    cached_tokens = int(total.get("cached_input_tokens", 0) or 0)
    output_tokens = int(total.get("output_tokens", 0) or 0)
    all_tokens = int(total.get("total_tokens", input_tokens + output_tokens) or 0)
    start = usage["first_timestamp"]
    duration = (now - start.astimezone()).total_seconds() if start else 0
    cost = estimate(usage, usage["model"])
    session_id = path.stem.removeprefix("rollout-")
    lines.extend([
        f"  {bold}{usage['model'] or 'Unknown model'}{reset}  ·  session {session_id}",
        divider,
        f"  {bold}SESSION{reset}    {money(cost) if cost is not None else 'Cost n/a'} API-eq.   ·   {usage['turns']} messages   ·   {elapsed_label(duration)}",
        f"  {all_tokens:,} tokens   ·   {input_tokens:,} input ({cached_tokens:,} cached)   ·   {output_tokens:,} output",
        divider,
        f"  {bold}USAGE WINDOWS{reset}  {muted}(percent remaining · no fixed token quota is exposed){reset}",
    ])

    limits = usage["rate_limits"] or {}
    primary = limits.get("primary") or {}
    secondary = limits.get("secondary") or {}
    if primary:
        lines.extend(rate_window("5-HOUR", primary, colors, primary.get("resets_at")))
    else:
        lines.append("  5-HOUR   Usage snapshot unavailable")
    if secondary:
        lines.extend(rate_window("WEEKLY", secondary, colors, secondary.get("resets_at")))
    else:
        lines.append("  WEEKLY   Usage snapshot unavailable")

    snapshot = usage["rate_snapshot_timestamp"]
    stamp = snapshot.astimezone().strftime("%H:%M:%S") if snapshot else "unknown"
    lines.extend([
        f"  {muted}Limit snapshot {stamp}  ·  refreshes when Codex writes session usage{reset}",
        divider,
        f"  {muted}Refreshing every {refresh:g}s  ·  Ctrl+C to stop  ·  --session ID selects a chat{reset}",
    ])
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

    current_key = None
    current_usage = None
    try:
        while True:
            path = fixed_session or find_session(root)
            if path is not None:
                stat = path.stat()
                key = (path, stat.st_mtime_ns, stat.st_size)
                if key != current_key:
                    current_usage = read_usage(path)
                    current_key = key
            else:
                current_usage = None
                current_key = None
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(live_screen(path, current_usage, refresh), flush=True)
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
