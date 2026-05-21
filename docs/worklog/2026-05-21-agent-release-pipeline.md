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
  private).
- Modified `packages/llm_tracker_agent/pyproject.toml` — version
  `0.0.1` → `0.1.0`. License (`Proprietary (internal research use)`),
  `[project.scripts] claude-manage`, and
  `[tool.hatch.build.targets.wheel] packages = ["src/llm_tracker_agent"]`
  were already correct and left untouched.

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

## Verification

```
$ git log -1 --oneline
<pending — first checkpoint commit below>
```

(Filled in at each checkpoint.)

## What's left / known limits

- GitHub Actions workflow file — pending (next step).
- Local `uv build` verification + wheel filename capture — pending.
- `docs/deploy.md` participant install section — pending.
- Signup template `[GITHUB_RELEASE_URL]` placeholder swap — **out of
  scope this session**; requires the first real release URL.

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
