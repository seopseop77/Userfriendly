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

- `<pending>` infra: GitHub Actions release-agent.yml (wheel on agent/v* tag)
- `04eaa98` agent: bump version 0.1.0 + ADR-0034
- `dabbf3e` docs: trim STATUS.md to essential current state
- `f6f64ab` infra: fix signup deploy build context (cd into the package)
- `36174ca` infra: GitHub Actions — auto-deploy both fly apps on main push

## Where we paused

**Thin-agent release pipeline — CI workflow landed, local build verified.**

- ADR-0034 locked: GitHub Releases wheel is the sole distribution channel
  for `claude-manage` (no PyPI, no binary, no Homebrew).
- `packages/llm_tracker_agent/pyproject.toml` version `0.0.1` → `0.1.0`.
- `.github/workflows/release-agent.yml` — `push` of tag `agent/v*` runs
  `uv build --out-dir dist` and attaches the wheel + sdist to the
  GitHub Release via `softprops/action-gh-release@v2`. **No PyPI publish.**
- Local verification: wheel
  `llm_tracker_agent-0.1.0-py3-none-any.whl` built clean; `pip --dry-run`
  reports `Would install llm-tracker-agent-0.1.0`; entry point
  `claude-manage` present.
- Worklog: `docs/worklog/2026-05-21-agent-release-pipeline.md`.

**Signup deploy + proxy redeploy remain operator-owned** (see worklog
`2026-05-21-signup-app.md` for commands; unchanged).

## Next single step

Add a `## Participant Installation` section to `docs/deploy.md` with
requirements (Python 3.11+), `pip install <WHEEL_URL>` /
`pipx install <WHEEL_URL>`, `claude-manage setup <YOUR_TOKEN>`, and the
`claude-manage` / `claude-manage --help` run lines. Use `<WHEEL_URL>` as
a placeholder — fill in for real after the operator pushes the first
`agent/v0.1.0` tag.

After that: swap `[GITHUB_RELEASE_URL]` in the signup app's
`templates/success.html` for the real release-asset URL, then redeploy
the signup app.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
