# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-21

## Active worklog

`docs/worklog/2026-05-21-agent-release-pipeline.md`

## Recent commits (last 5)

- `<pending>` signup: per-step Copy buttons on success page
- `ffb476a` signup: success page — concrete v0.1.0 wheel URL
- `bcb7d50` docs: backfill cc2874e hash in STATUS + worklog
- `cc2874e` docs: participant install section for claude-manage
- `70972c5` infra: GitHub Actions wheel release for agent

## Where we paused

**Thin-agent v0.1.0 release published; signup success page wired up.**

- Release `agent/v0.1.0` is live on GitHub with wheel
  `llm_tracker_agent-0.1.0-py3-none-any.whl` (5.94 KB) attached.
- Repo renamed `Userfreiendly` → `Userfriendly` (typo fix). Release
  survived the rename; canonical wheel URL is now
  `https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl`.
- `success.html` of the signup app has the concrete URL baked in (no
  more `[GITHUB_RELEASE_URL]` placeholder). Route tests updated; 3
  passed / 3 skipped on `pytest packages/llm_tracker_signup/tests/test_app.py`.
- `docs/deploy.md` `## Participant Installation` left with `<WHEEL_URL>`
  placeholder by design — deploy.md is a generic guide, not a per-
  release artefact.
- Worklog: `docs/worklog/2026-05-21-agent-release-pipeline.md`.

**Proxy redeploy still operator-owned** (see worklog
`2026-05-21-signup-app.md` for commands; unchanged).

## Next single step

**Operator-owned: redeploy the signup app** so participants see the new
success page with the live wheel URL:

```
fly deploy -c packages/llm_tracker_signup/fly.toml
# or push to main and let .github/workflows/deploy-signup.yml run
```

Sanity-check after deploy: hit `https://llm-tracker-signup.fly.dev/success?token=lts_demo`
and confirm the rendered Step 1 `pip install ...` line carries the
v0.1.0 wheel URL.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
