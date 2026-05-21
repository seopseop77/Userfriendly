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

- `<pending>` agent: bump version to 0.1.0 + ADR-0034 (GitHub Releases wheel)
- `dabbf3e` docs: trim STATUS.md to essential current state
- `f6f64ab` infra: fix signup deploy build context (cd into the package)
- `36174ca` infra: GitHub Actions — auto-deploy both fly apps on main push
- `c3c08ab` signup: Dockerfile + fly.toml build wiring

## Where we paused

**Thin-agent release pipeline — ADR + version bump landed; CI workflow next.**

- ADR-0034 locked: GitHub Releases wheel is the sole distribution channel
  for `claude-manage` (no PyPI, no binary, no Homebrew). Review trigger
  documented (>200 participants / non-Python audience / private repo flip).
- `packages/llm_tracker_agent/pyproject.toml` version `0.0.1` → `0.1.0`.
- Worklog: `docs/worklog/2026-05-21-agent-release-pipeline.md`.

**Signup deploy + proxy redeploy remain operator-owned** (see prior STATUS
in worklog `2026-05-21-signup-app.md` for the exact commands; nothing
changes about that track).

## Next single step

Add `.github/workflows/release-agent.yml` — tag `agent/v*` triggers
`uv build` in `packages/llm_tracker_agent` and attaches `dist/*.whl`
(plus sdist) to the GitHub Release via `softprops/action-gh-release@v2`.
**No PyPI publish.** Verify locally with `uv build` and capture the wheel
filename in the worklog before committing.

After CI lands: add a `## Participant Installation` section to
`docs/deploy.md` (`<WHEEL_URL>` placeholder until the first tag is pushed).

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
