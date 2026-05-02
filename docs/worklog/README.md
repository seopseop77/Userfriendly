# Worklog

A record of every non-trivial Claude Code work session.

## Rules

- Filename: `YYYY-MM-DD-<slug>.md` (e.g., `2026-04-25-proxy-skeleton.md`).
- Same date + same topic → append to the existing file.
- New topic → new file.
- Template: copy `TEMPLATE.md` to start.
- **Update during work, not at completion.** Cutoff resilience is the
  whole point.

## Worklog vs. ADR

- Worklog: what was done, how it was verified, what's next — narrative.
- ADR: why A instead of B, hard-to-reverse decisions — decision record.
  See `../decisions/`.

If both apply, write both. The worklog should reference the ADR like
"this decision is in ADR-NNNN".
