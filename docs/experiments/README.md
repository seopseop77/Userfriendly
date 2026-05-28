# Experiments

Probes and ad-hoc investigations of llm-tracker behaviour. Each
subdirectory is one investigation topic with its own README (runbook),
optional helper scripts, and a `results/` folder for per-round writeups.

This track is **separate** from:

- `docs/worklog/` — per-session narrative of code changes.
- `docs/decisions/` — architectural decisions (ADRs).

Use this folder when the goal is "find what breaks" rather than "ship a
change". Each runbook documents how to reproduce a probe consistently;
findings themselves live in `<topic>/results/*.md` and (if confirmed)
in the originating worklog's Suggestions section.
