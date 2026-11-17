# Codex Cost Band

A Codex plugin that reports usage from local Codex CLI session logs: cumulative tokens, estimated session time, message count, context tokens, and an API-equivalent cost estimate when a bundled model price is available.

It cannot add a live strip above the Codex prompt. Codex plugins currently expose skills, MCP tools, and lifecycle hooks rather than a prompt-area UI extension. Ask Codex to **show the cost band** to run the reporter. The dollar figure is an API-equivalent estimate, not the cost or quota usage of a ChatGPT/Codex subscription. Unknown models show token totals without a price estimate.

The reporter reads the newest modified file under `CODEX_HOME/sessions` (or `~/.codex/sessions`) and does not transmit log contents. If several sessions are active, the newest file may not be the intended one.

## Install

From this repository:

```text
codex plugin marketplace add Karsten0701/codex-cost-band
```

Then open the Codex plugin browser with `/plugins`, select **Local Mods**, and install **Codex Cost Band**. Local marketplace plugin installation is currently done through the plugin browser.

## Run locally

```text
python plugins/codex-cost-band/scripts/cost_band.py
```

On Windows, `py -3 plugins/codex-cost-band/scripts/cost_band.py` is also supported.

