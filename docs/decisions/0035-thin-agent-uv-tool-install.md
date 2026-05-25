# ADR-0035 · Thin-agent install command: `uv tool install` (amends ADR-0034)

- **Status**: Accepted
- **Date**: 2026-05-25
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0034 (distribution channel — GitHub Releases wheel,
  unchanged by this ADR), ADR-0025 (thin agent language — Python),
  `docs/deploy.md#participant-installation`,
  `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`,
  `docs/worklog/2026-05-25-uv-tool-install.md`

## Context

ADR-0034 settled the **distribution channel** (GitHub Releases wheel) but
combined it with an **install-command recommendation** — "participants run
`pip install <wheel-url>` or `pipx install <wheel-url>`". That second piece
broke immediately when the project operator, acting as participant #1 on
2026-05-25, copied the success-page Step 1 verbatim:

```
pip3.12 install https://github.com/.../llm_tracker_agent-0.1.0-py3-none-any.whl
error: externally-managed-environment
```

The Homebrew Python 3.12 distribution ships PEP 668's `EXTERNALLY-MANAGED`
marker at
`/opt/homebrew/Cellar/python@3.12/3.12.12_2/.../python3.12/EXTERNALLY-MANAGED`,
which causes plain `pip install` to refuse. The same friction reproduces on
Debian/Ubuntu apt Python, recent Fedora, Arch, and any WSL Ubuntu — i.e.
the most common dev-laptop Python sources.

This was foreseeable. ADR-0034 §Review trigger #2 explicitly named
"a participant segment without Python 3.11+ appears" as a re-open trigger.
The real-world signal is **stronger** than that wording: even participants
*with* Python often have a PEP-668-managed Python that refuses
system-wide installs, and ADR-0034 reason #2 ("audience already has the
dependency we need — every participant is a Claude Code user, therefore has
Python 3.11+") was a factual misread of Claude Code's runtime. Claude Code
is a Node/npm tool (`@anthropic-ai/claude-code`); it does not require
Python at all. The premise that every participant arrives with a usable
Python 3.11+ was never true.

The distribution channel itself — wheel attached to a GitHub Release tag —
remains correct under ADR-0034's other two reasons (license fit, minimal
ops). Only the **install command recommended to the participant** needs to
change, and only the docs/UI that hand that command out (success page +
`docs/deploy.md#participant-installation`).

## Options considered

1. **Plain `pip install <wheel-url>`** *(current, ADR-0034 default)*.
   Breaks under PEP 668 on Homebrew/apt/Fedora/Arch/WSL Python. Recovering
   requires either `--break-system-packages` (risks the system Python) or
   manual venv activation per session. No PATH integration for the
   `claude-manage` entry point.

2. **`pipx install <wheel-url>`**. Solves PEP 668 and PATH. But pipx is
   itself a Python package — installing it from `pip` hits the same PEP
   668 wall, so the participant must first `brew install pipx` (mac) /
   `apt install pipx` (Ubuntu) / equivalent. The dependency chain just
   moves up one step; participants with no Python yet still have to install
   Python first.

3. **`uv tool install <wheel-url>` (this ADR's choice).** uv is a single
   static Rust binary distributed via `astral.sh/uv` install scripts (no
   Python required to install uv itself). `uv tool install` is the
   `pipx install` equivalent — isolated environment + PATH-registered
   entry point. uv additionally **bootstraps its own Python interpreter**
   (`python-build-standalone`, ~150 MB on disk, one-time) when no
   compatible Python is on PATH, so PEP 668 becomes structurally
   irrelevant: uv never touches the system or Homebrew Python.

4. **`curl | sh` bootstrap script attached to the release.** A wrapper
   that internally does (install uv) → (`uv tool install <wheel>`) →
   (PATH check). Strictly a thin layer over Option 3. Worth doing if we
   want a single copy-paste line, but the operational cost is a new
   shell script to author, test on macOS/Linux/Windows-via-Git-Bash, and
   keep in sync with each release. Deferred — Option 3 is one extra
   command for the participant and zero extra script for us.

5. **PyInstaller / Nuitka single binary per OS×arch.** Zero
   participant-side runtime requirement. Cost: cross-compile matrix,
   per-OS code signing (macOS notarization in particular), and a new
   CI pipeline that the current single GHA `release-agent.yml` does not
   carry. Still on the table as an ADR-0034 §Open-question item; this
   ADR does not pre-empt it.

## Decision

**Pick Option 3 — `uv tool install <wheel-url>` becomes the recommended
participant install command.** Three reasons:

1. **Structurally invalidates PEP 668 for this audience.** uv ships its
   own Python and its own isolated tool environments. The participant's
   system / Homebrew / apt Python is never touched, so the
   `externally-managed-environment` error class disappears for our install
   flow regardless of which Python (if any) the participant happens to
   have. This is a property no `pip`/`pipx` recommendation can match
   without first solving the "install a non-system Python" problem.

2. **Holds for Python-less participants** — the segment ADR-0034 §Review
   trigger #2 named. Since uv downloads `python-build-standalone` on
   first need, a participant whose laptop has zero Python installed runs
   the same two commands and gets a working `claude-manage`. ADR-0034's
   "audience already has Python 3.11+" premise no longer needs to be
   true.

3. **Strict subset of the previous operational surface.** The wheel
   artifact, the release tag (`agent/vX.Y.Z`), the CI workflow
   (`.github/workflows/release-agent.yml`), and the asset URL are all
   unchanged. The only delta is the string we paste into
   `success.html` and `docs/deploy.md`. No new infra, no new account,
   no new build step. ADR-0034's distribution-channel decision (Option 1
   in that ADR) stands.

### Operating shape (delta from ADR-0034)

- The participant runs **two commands** instead of one. First-time:

  ```
  curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS / Linux / WSL
  uv tool install <wheel-url>
  ```

  Windows PowerShell first-line equivalent:

  ```
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  Participants who already have `uv` installed (because they use it for
  other Python work) skip the first line. `uv tool install --force <url>`
  upgrades in place.

- `claude-manage` is auto-registered on the user's PATH by uv's tool-install
  flow (uv adds `~/.local/bin` to PATH during `curl | sh`). Steps 2 and 3
  on the success page (`claude-manage setup …` / `claude-manage`) are
  byte-identical to ADR-0034's flow — only Step 1 changes.

- The `pip install` / `pipx install` paths still *work* for participants
  who insist on them (the wheel itself is format-standard), they are just
  no longer the recommended path and no longer documented as the primary
  flow.

## Consequences

### Enables

- Participants on any OS / any Python-state combination follow the same
  Step 1, with no PEP 668 detours and no Python prerequisite. The signup
  page stops being a triage queue for install errors.
- The "Python 3.11+ required" footnote becomes implementation-detail,
  not participant-visible. uv resolves it silently.
- Future agent releases can bump `requires-python` (e.g. to 3.12) without
  asking every participant to upgrade their system Python — uv pulls the
  needed interpreter on demand.

### Forecloses (for now)

- Single-line install. We accept two lines (install uv, then install
  agent) until either Option 4 (bootstrap script) or Option 5 (single
  binary) is built.
- Recommending `pip install` in any first-class participant doc. Plain
  pip stays as a fallback paragraph, not the headline command.

### Reversibility

High. The wheel artifact and URL are unchanged — reverting to
`pip install <url>` is a docs/template edit. Switching forward to a
bootstrap script (Option 4) or a single binary (Option 5) is also
additive over the wheel and does not invalidate this ADR's flow for
participants who chose uv.

### What ADR-0034 keeps / loses

- **Keeps**: distribution channel (GitHub Releases wheel), release-tag
  trigger (`agent/v*`), CI workflow, no-PyPI stance, reversibility
  argument, all three Review triggers.
- **Loses**: the specific `pip install` / `pipx install` lines under
  "Operating shape → Participant install" and the implicit assumption
  that every participant has a working Python 3.11+. ADR-0034's status
  is updated to **Accepted (install command amended by ADR-0035)** —
  the distribution-channel decision itself stands; only the recommended
  install command is superseded by this ADR.

## Open questions

- **`curl | sh` bootstrap script** (Option 4 above). Worth scoring once
  the two-line flow accumulates participant feedback. The win is one
  copy-paste line; the cost is a maintained script tested across
  shells/OSes.
- **Pre-built single binary** (Option 5). Tied to ADR-0034 §Open
  questions and still gated by the same code-signing cost. This ADR
  does not change its priority.
- **uv install-script supply-chain trust.** `curl | sh` from
  `astral.sh/uv` carries the standard `curl | sh` caveat. Acceptable
  for the current research-participant audience (same trust posture as
  `rustup`/`nvm`/`brew`'s own install scripts); revisit if the audience
  shifts to higher-assurance contexts.
