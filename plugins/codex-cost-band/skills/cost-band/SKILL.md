---
name: cost-band
description: Show token usage, elapsed work time, message count, context usage, and an API-equivalent cost estimate for the latest Codex CLI session.
---

# Codex Cost Band

When the user asks for the cost band, current session cost, or session usage, run the bundled read-only reporter:

Use the absolute path to this installed plugin's `scripts/cost_band.py`, deriving the plugin root from the skill file's installed path. Do not use a workspace-relative path.

```bash
python "<plugin-root>/scripts/cost_band.py"
```

On Windows, use `py -3` if `python` is unavailable. Show the reporter's output without presenting its API-equivalent estimate as the user's subscription charge. If the reporter cannot identify a model price, report the token and time totals and say that the cost estimate is unavailable.

The reporter reads local Codex rollout logs and does not send their contents anywhere. It chooses the most recently modified session log, so explain that this is a best-effort choice if multiple Codex sessions are active.
