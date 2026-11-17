# Codex Cost Band

A Codex plugin that reports usage from local Codex CLI session logs: cumulative tokens, estimated session time, message count, context tokens, and an API-equivalent cost estimate when a bundled model price is available.

It cannot add a live strip above the Codex prompt. Codex plugins currently expose skills, MCP tools, and lifecycle hooks rather than a prompt-area UI extension. Ask Codex to **show the cost band** to run the reporter. The dollar figure is an API-equivalent estimate, not the cost or quota usage of a ChatGPT/Codex subscription. Unknown models show token totals without a price estimate.

The reporter reads the newest modified file under `CODEX_HOME/sessions` (or `~/.codex/sessions`) and does not transmit log contents. If several sessions are active, the newest file may not be the intended one.

## Install

From this repository:

```text
codex plugin marketplace add Karsten0701/codex-cost-band
```

Then install it with:

```text
codex plugin add codex-cost-band@local-mods
```

Use `codex plugin list` to inspect installed plugins.

## Run locally

```text
python plugins/codex-cost-band/scripts/cost_band.py
```

On Windows, `py -3 plugins/codex-cost-band/scripts/cost_band.py` is also supported.

## Watch a live session

Run `watch.cmd` from this folder to open a live monitor in the current terminal. It refreshes when Codex updates the session log and stops with `Ctrl+C`.

```text
watch.cmd
watch.cmd --session 01a1e9bb-1748-70a2-9b94-c4df5488cac9
watch.cmd --refresh 2
```

The default follows the newest modified local Codex session. Use `--session` when multiple Codex chats are active.

