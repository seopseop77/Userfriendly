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

- `cc2874e` docs: participant install section for claude-manage
- `70972c5` infra: GitHub Actions wheel release for agent
- `04eaa98` agent: bump version 0.1.0 + ADR-0034
- `dabbf3e` docs: trim STATUS.md to essential current state
- `f6f64ab` infra: fix signup deploy build context (cd into the package)

## Where we paused

**Thin-agent release pipeline — code-complete in this repo.**

- ADR-0034: GitHub Releases wheel is the sole distribution channel for
  `claude-manage` (no PyPI, no binary, no Homebrew).
- `packages/llm_tracker_agent/pyproject.toml` version → `0.1.0`.
- `.github/workflows/release-agent.yml` — `push` of `agent/v*` builds and
  attaches the wheel + sdist to the GitHub Release. **No PyPI publish.**
- Local verification: `llm_tracker_agent-0.1.0-py3-none-any.whl` built
  clean; `pip --dry-run` says `Would install llm-tracker-agent-0.1.0`.
- `docs/deploy.md` — `## Participant Installation` section added with
  `<WHEEL_URL>` placeholder.
- Worklog: `docs/worklog/2026-05-21-agent-release-pipeline.md`.

**Signup deploy + proxy redeploy remain operator-owned** (see worklog
`2026-05-21-signup-app.md` for commands; unchanged).

## Next single step

**Operator-owned**: push the first `agent/v0.1.0` git tag. Then copy
the resulting wheel asset URL into:

1. `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`
   (swap `[GITHUB_RELEASE_URL]`), then redeploy the signup app.
2. `docs/deploy.md` `## Participant Installation` (replace each `<WHEEL_URL>`
   placeholder with the real URL).

Tag push:

```
git tag agent/v0.1.0
git push origin agent/v0.1.0
```

Then watch the run at GitHub → Actions → "Release llm-tracker-agent" and
confirm `llm_tracker_agent-0.1.0-py3-none-any.whl` is attached to the
auto-created release.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
