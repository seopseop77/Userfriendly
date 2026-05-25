# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-25

## Active worklog

`docs/worklog/2026-05-25-uv-tool-install.md`

## Recent commits (last 5)

- `<pending>` docs: backfill 2b73b4c hash in STATUS + worklog
- `2b73b4c` signup: inline style for pre no-wrap (CDN class insufficient)
- `f55d18b` docs: backfill 2b4f573 hash in STATUS + worklog
- `2b4f573` signup: idempotent uv bootstrap + no-wrap code blocks
- `a1c5af7` docs: backfill ff5fac0 hash in STATUS + worklog

## Where we paused

**Participant install recommendation switched from `pip install <wheel>` to
`uv tool install <wheel>` (ADR-0035, amends ADR-0034).**

- Trigger: operator hit PEP 668 (`error: externally-managed-environment`)
  on Homebrew Python 3.12 when copying the success-page Step 1. Same
  failure reproduces on Debian/Ubuntu apt, recent Fedora, Arch, and WSL.
- ADR-0035 picks `uv tool install <wheel-url>` because uv ships its own
  Python interpreter — PEP 668 becomes structurally irrelevant, and the
  participant's machine no longer needs Python pre-installed.
- Distribution channel (GitHub Releases wheel, ADR-0034) unchanged. CI
  workflow `.github/workflows/release-agent.yml` unchanged. Only the
  install command in `success.html` and `docs/deploy.md` changed.
- ADR-0034's status carries an "Amendment note" pointing to ADR-0035;
  its distribution-channel decision stands.
- Follow-up: operator hit two UX issues on first-run (brew uv shadowed
  by astral uv from copy-paste; long Step 2 command visually wrapped).
  Fixed by wrapping the uv bootstrap in a `command -v uv` POSIX guard
  and adding `whitespace-pre` to every step `<pre>` block.
- Follow-up 2: after redeploy operator confirmed `command -v` shows
  but Step 2 *still wrapped* — same Tailwind class worked on Step 1.
  Rendered HTML inspection ruled out hidden chars / class diffs.
  Likely a Tailwind CDN JIT quirk we can't reproduce server-side.
  Switched to inline `style="white-space:pre;word-break:keep-all;overflow-wrap:normal"`
  on every step `<pre>` — specificity 1000 wins regardless of CDN
  state. Tests updated assert inline style renders on all 5 pre
  blocks.
- Test: `pytest packages/llm_tracker_signup/tests/test_app.py -q` →
  3 passed / 3 skipped (DB-touching skips unchanged from prior session).
- Worklog: `docs/worklog/2026-05-25-uv-tool-install.md` (incl. follow-up
  section).

## Next single step

**Operator-owned: redeploy the signup app + re-do the participant-#1
install with the new two-line flow.**

```
fly deploy -c packages/llm_tracker_signup/fly.toml
# or push to main and let .github/workflows/deploy-signup.yml run
```

Then, on the operator's own laptop:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL -l
uv tool install https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl
claude-manage --help
```

Sanity-check the deployed success page: visit
`https://llm-tracker-signup.fly.dev/success?token=lts_demo` and confirm
Step 1 renders the `uv tool install …` line (not the old `pip install …`
line). If the old line is still visible, the deploy did not pick up the
template — investigate before re-litigating the ADR.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
