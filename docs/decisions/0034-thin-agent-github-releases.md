# ADR-0034 · Thin-agent distribution channel: GitHub Releases (wheel)

- **Status**: Accepted (install command amended by ADR-0035, 2026-05-25)
- **Date**: 2026-05-21
- **Author**: Claude Code (drafting) / Claude Cowork (decision)
- **Related**: ADR-0003 (monorepo + per-package pyproject + git URL install),
  ADR-0025 (thin agent — Python CLI), ADR-0035 (install command —
  `uv tool install`), `docs/deploy.md`,
  `docs/worklog/2026-05-21-agent-release-pipeline.md`

> **Amendment note (2026-05-25, ADR-0035)**: the *distribution channel*
> decision (Option 1 — GitHub Releases wheel) stands. The recommended
> *install command* — `pip install <url>` / `pipx install <url>` in the
> §Operating-shape block and §Decision reason #2's "audience already has
> Python 3.11+" premise — were superseded by ADR-0035 after PEP 668 broke
> the flow on participant #1's Homebrew Python. Treat the `pip install` /
> `pipx install` snippets below as historical; current participant
> instructions live in `docs/deploy.md#participant-installation` and the
> signup app's `success.html`.

## Context

ADR-0025 settled the *implementation language* of the thin local agent
(`claude-manage`) as Python, and explicitly left the **future distribution
channel** as an open question (ADR-0025 §Open questions). The agent is now
code-complete (`packages/llm_tracker_agent`), Phase 3b is moving into the
participant-onboarding step, and the signup app's success page already
needs a real install URL — the `[GITHUB_RELEASE_URL]` placeholder in
`packages/llm_tracker_signup/.../templates/success.html` is the concrete
forcing function. Lock the channel before the first external participant
copies an install command.

The audience for `claude-manage` is not generic Python users; it is a
hand-picked set of **Claude Code users**. By construction every participant
already has Python (Claude Code requires it) and is comfortable running a
single shell command. The framework license is *Proprietary (internal
research use)* (see `pyproject.toml`); public PyPI publication would mis-
classify the package and surface it to an audience it is not intended for.

The deployment story for server and signup app (ADR-0022, Fly.io) is
operator-driven and orthogonal — this ADR concerns only the agent wheel
that ships to participants' laptops.

## Options considered

1. **GitHub Releases — wheel attached to each git tag.** Tag `agent/vX.Y.Z`
   triggers CI to build `packages/llm_tracker_agent/dist/*.whl` and attach
   it to the release. Participants install with
   `pip install <release-asset-url>` or `pipx install <release-asset-url>`.
2. **PyPI (public).** Standard distribution. Index account, public package
   name reservation, dependency on `pypi.org` uptime.
3. **Internal / private PyPI index.** Self-hosted (`devpi`, `pypiserver`) or
   commercial (`Cloudsmith`, `GitHub Packages PyPI`). Auth required.
4. **Homebrew tap.** A small tap repo exposing a Python-via-Homebrew
   formula. Mac-only without extra work; participants who use Linux/WSL
   are not covered.
5. **Pre-built single binary.** PyInstaller / Nuitka producing per-OS
   binaries. Zero runtime dependency for the participant.
6. **`curl | sh` installer.** A shell script that fetches the wheel and
   pipx-installs it.

## Decision

**Option 1 — GitHub Releases wheel as the sole distribution channel.**
Three reasons:

1. **License fit.** The package is proprietary/internal-research-use. PyPI
   (public) mis-targets the audience and creates a discoverable artifact we
   do not want indexed. GitHub Releases keeps the artifact reachable by URL
   without listing it in a public package index.
2. **Audience already has the dependency we need.** Every participant is a
   Claude Code user, therefore has Python 3.11+ and the tooling (`pip` /
   `pipx`) to consume a wheel. Building per-OS binaries or a Homebrew
   formula adds operational cost (cross-compile matrix, tap maintenance)
   for zero participant benefit.
3. **Simplest ops, no external accounts.** A wheel built by an existing
   GitHub Actions runner and attached to the same tag the human pushes is
   the smallest moving part that still gives a stable, versioned install
   URL. No PyPI account, no tap repo, no signing service.

The wheel-only stance also avoids re-doing the work the next time the
choice resurfaces: it sits next to ADR-0003's "PyPI publication is deferred
until external usage demands it" — *external* here is internal research
participants, not the broader Python community, so the trigger ADR-0003
talks about has not fired.

### Operating shape

- Trigger: pushing a git tag matching `agent/v*` (e.g. `agent/v0.1.0`).
  The tag namespace is per-package — server and signup get their own tag
  prefixes when those packages need release tagging.
- CI: `.github/workflows/release-agent.yml` runs `uv build` inside
  `packages/llm_tracker_agent`, then `softprops/action-gh-release@v2`
  attaches `dist/*.whl` (and the sdist `dist/*.tar.gz`) to the release the
  tag push auto-created. **No PyPI publish step.**
- Participant install:
  ```
  pip install <wheel-asset-url>
  # or
  pipx install <wheel-asset-url>
  ```
  The asset URL changes on each release (versioned filename); each install
  is one-time per participant per upgrade.
- Repo visibility: this ADR assumes the GitHub repo is **public** — release
  assets on a public repo need no auth token to download. If the repo is
  flipped to private later, the install command grows a token query string
  and the participant instructions must be updated; that flip itself is a
  separate decision.

## Consequences

### Enables

- A first stable install command we can paste into the signup app's success
  page (`[GITHUB_RELEASE_URL]` placeholder swaps to a real
  `https://github.com/.../releases/download/agent/v0.1.0/...whl`).
- Reproducible, versioned installs — participants on different days install
  the same artifact byte-for-byte, because the asset is immutable once the
  release is published.
- Painless agent rollback: re-publish a prior tag, hand out that URL.

### Forecloses (for now)

- Discovery via `pip search` / `pypi.org` browsing.
- `pip install llm-tracker-agent` without a URL. We accept this — the
  audience receives the URL through the signup flow, not by guessing a
  package name.
- Auto-resolved transitive upgrades from PyPI's resolver. Pinned wheel URL
  installs ignore later same-name releases; participants only get a new
  version when they install a new URL.

### Reversibility

High. Switching to PyPI later is a mechanical addition of one CI step
(`uv publish`) plus a name reservation, while the GitHub Releases artifact
stays as a parallel channel. No participant-side breakage on the
transition — the existing wheel URLs keep resolving.

## Review trigger

Re-open this ADR if **any one** of these happens:

- Participant count exceeds **200**, at which point pasting URLs into a
  signup page stops scaling and PyPI's name lookup is the better UX.
- A participant segment without Python 3.11+ appears (e.g. non-developer
  reviewers), at which point a binary or hosted-runner option needs scoring.
- The repository becomes private, which changes the auth story for the
  download URL and may warrant a hosted internal index instead.

Until any of those fire, the wheel-on-GitHub-Releases path stands.

## Open questions

- **Code signing** for the wheel — out of scope at single-digit / low-double-
  digit participant count; revisit at the review trigger above.
- **Yanked-release semantics** — GitHub Releases supports deleting an asset
  but cached `pip` resolutions on participant laptops will still install
  from cache. If we need a forced upgrade, the path is a new tag, not a
  re-publish of the old one.
