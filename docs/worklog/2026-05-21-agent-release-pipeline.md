# 2026-05-21 · Thin-agent release pipeline (GitHub Releases wheel)

**Author**: Claude Code
**Session trigger**: STATUS.md "Next single step" — write ADR + GitHub
Actions release workflow for `llm_tracker_agent` wheel distribution via
GitHub Releases. After that, update the `[GITHUB_RELEASE_URL]` placeholder
in the signup success template with the real wheel URL.
**Related docs**: ADR-0003 (distribution strategy), ADR-0025 (thin-agent
Python CLI, with deferred channel question), ADR-0034 (this session),
`docs/deploy.md`, `packages/llm_tracker_agent/pyproject.toml`,
`.github/workflows/release-agent.yml`

## Interpretation

The forcing function is the signup app's success page, which currently
contains a `[GITHUB_RELEASE_URL]` placeholder where the participant should
see a real install command. Before that placeholder can be filled, two
things must exist: (1) a decision on **how** the agent is distributed, and
(2) a CI path that produces a stable, versioned download URL.

The Cowork-supplied prompt closes the distribution question (GitHub
Releases wheel, no PyPI, no binary) and asks Claude Code to do the
implementation: write the ADR, sanity-check the agent's `pyproject.toml`,
add the GitHub Actions workflow, do one local build, and document the
participant install path in `docs/deploy.md`. The placeholder swap in the
signup template is a separate follow-up — it requires the first real
release URL, which only exists after the human pushes the first
`agent/vX.Y.Z` tag.

Interpreted scope for this session: ADR + CI + build verification + docs.
Tag pushing and signup-template URL swap are not in scope.

## What was done

- Created `docs/decisions/0034-thin-agent-github-releases.md` — ADR locks
  GitHub Releases wheel as the sole distribution channel for
  `claude-manage`, with explicit alternatives (PyPI, private index,
  Homebrew tap, pre-built binary, `curl|sh`) and an explicit review
  trigger (>200 participants, non-Python audience, or repo flip to
  private). (commit `04eaa98`)
- Modified `packages/llm_tracker_agent/pyproject.toml` — version
  `0.0.1` → `0.1.0`. License (`Proprietary (internal research use)`),
  `[project.scripts] claude-manage`, and
  `[tool.hatch.build.targets.wheel] packages = ["src/llm_tracker_agent"]`
  were already correct and left untouched. (commit `04eaa98`)
- Created `.github/workflows/release-agent.yml` — push of any tag matching
  `agent/v*` (or manual `workflow_dispatch`) installs `uv` (pinned to
  `0.11.8` to match local), runs `uv build --out-dir dist` inside
  `packages/llm_tracker_agent`, and attaches `dist/*.whl` + `dist/*.tar.gz`
  to the release the tag push created via
  `softprops/action-gh-release@v2`. `permissions: contents: write` is set
  at the job level. No PyPI publish. (commit `70972c5`)
- Modified `docs/deploy.md` — appended a `## Participant Installation`
  section covering requirements (Python 3.11+, `pip`/`pipx`), install /
  setup / run / upgrade / uninstall commands. Uses `<WHEEL_URL>` as the
  placeholder participants will copy from the signup app's success page.

## Decisions

- **GitHub Releases wheel, no PyPI** — see ADR-0034 for the full
  rationale. Captured as an ADR (not just worklog) because flipping later
  to PyPI changes the contract participants type at install time.
- **Static `version = "0.1.0"` in `pyproject.toml`** (not `[tool.hatch.
  version]` dynamic). The release flow is "human pushes
  `agent/v0.1.0` → CI builds → wheel attached". The pyproject version is
  bumped by hand in the same commit that produces the tag. Dynamic
  versioning from VCS adds machinery for a release cadence we do not yet
  have.
- **Tag prefix `agent/v*`, not bare `v*`.** Future per-package tags
  (`server/v*`, `signup/v*`) live alongside without colliding, and the
  workflow trigger filter stays straightforward.
- **`uv build --out-dir dist` (not bare `uv build`).** Inside a `uv`
  workspace, bare `uv build` from within a member package still drops the
  artefacts at `<workspace-root>/dist`, not the member's own `dist/`. The
  workflow used to need a brittle `working-directory` + cross-directory
  path. With `--out-dir dist` the build lands at
  `packages/llm_tracker_agent/dist/*` and the
  `softprops/action-gh-release@v2` `files:` glob is the obvious one.
  Confirmed locally — see Verification below.
- **`fail_on_unmatched_files: true`** in the release step. If a future
  refactor changes where artefacts land, the workflow should fail loudly
  instead of cutting an empty release.
- **uv pinned to `0.11.8`** in the workflow. Same version as the local
  build that produced the verified wheel; bumping is a one-line workflow
  edit when needed.

## Verification

### Checkpoint A — ADR + version bump

```
$ git log -1 --oneline
04eaa98 agent: bump version 0.1.0 + ADR-0034
```

### Checkpoint B — local build + workflow

```
$ cd packages/llm_tracker_agent && uv build --out-dir dist
Building source distribution...
Building wheel from source distribution...
Successfully built dist/llm_tracker_agent-0.1.0.tar.gz
Successfully built dist/llm_tracker_agent-0.1.0-py3-none-any.whl

$ ls packages/llm_tracker_agent/dist/
llm_tracker_agent-0.1.0-py3-none-any.whl  (6087 bytes)
llm_tracker_agent-0.1.0.tar.gz            (6157 bytes)

$ .venv/bin/python3.12 -m pip install \
    packages/llm_tracker_agent/dist/llm_tracker_agent-0.1.0-py3-none-any.whl \
    --dry-run
Would install llm-tracker-agent-0.1.0
```

Wheel METADATA confirmed: `Name: llm-tracker-agent`, `Version: 0.1.0`,
`License: Proprietary (internal research use)`,
`Requires-Python: >=3.11`, runtime deps `fastapi`, `httpx[http2]`,
`tomli-w`, `typer`, `uvicorn[standard]`. `entry_points.txt` exposes
`claude-manage = llm_tracker_agent.cli:app`.

Workflow YAML parsed clean via `python -c "import yaml;
yaml.safe_load(open('.github/workflows/release-agent.yml'))"`.

## What's left / known limits

- First tag push (`agent/v0.1.0`) — operator action, not in this session.
- Signup template `[GITHUB_RELEASE_URL]` placeholder swap — **out of
  scope this session**; requires the first real release URL.

### Checkpoint C — participant install section

```
$ grep -n "^## Participant Installation\|^### " docs/deploy.md \
    | tail -8
425:## Participant Installation
436:### Requirements
444:### Install
457:### Setup
469:### Run
482:### Upgrading
495:### Uninstall
```

`<WHEEL_URL>` is left as the placeholder participants will copy from the
signup app's success page once the first `agent/v0.1.0` tag is pushed.

## Handoff

After this worklog finishes:

1. Human pushes the first `agent/v0.1.0` git tag. CI builds and attaches
   the wheel.
2. Copy the resulting asset URL into
   `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`
   replacing `[GITHUB_RELEASE_URL]`, then commit + redeploy signup.

## Suggestions (untouched)

- `[tool.hatch.version]` source-from-VCS could remove the manual version
  bump step later; not worth setting up before release #2.
- A second workflow `release-server.yml` mirroring this one (tag
  `server/v*`) could replace the current always-deploy-on-main posture
  for the server, giving release-gated control. Out of scope here; bring
  it up in the next infra session.
