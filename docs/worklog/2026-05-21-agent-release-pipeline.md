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
  (commit `cc2874e`)
- Operator pushed `agent/v0.1.0` after the workflow landed; GitHub
  Actions built and attached
  `llm_tracker_agent-0.1.0-py3-none-any.whl` (5.94 KB) and
  `llm_tracker_agent-0.1.0.tar.gz` to the auto-created Release. Repo
  was renamed `Userfreiendly` → `Userfriendly` in the same window
  (typo fix); release survived the rename via GitHub's auto-redirect.
- Modified
  `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`
  — replaced `[GITHUB_RELEASE_URL]` with the concrete wheel asset URL
  `https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl`.
- Modified `packages/llm_tracker_signup/tests/test_app.py` —
  `test_get_success_renders_token` previously asserted the placeholder
  literal `[GITHUB_RELEASE_URL]` was rendered; now asserts the
  full wheel URL is rendered. Failing on a stale URL is desirable: the
  next time the version bumps, this test prompts the success-page
  update.
- Added per-step Copy buttons in
  `packages/llm_tracker_signup/.../templates/success.html` — each of the
  three `<pre>` code blocks (Install / Configure / Run) now has an
  absolute-positioned Copy button in its top-right corner. Buttons
  share one JS handler driven by `data-copy-target` → `<code id="…">`,
  with a clipboard-API path and a selection-fallback for older browsers.
  The existing token-box copy logic is left untouched.
- Test `test_get_success_renders_token` now also asserts each step's
  `id="step-N-code"` + matching `data-copy-target="step-N-code"` pair
  is rendered.

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

- Signup app redeploy — required to surface the new success page to
  participants (operator: `fly deploy -c packages/llm_tracker_signup/fly.toml`
  or push to main and let GitHub Actions handle it).

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

### Checkpoint D — success.html URL swap + test fix

```
$ grep -n "llm_tracker_agent-0.1.0-py3-none-any.whl" \
    packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html
39:        ...pip install https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl...

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/test_app.py -q
...sss
3 passed, 3 skipped in 0.74s
```

No leftover `GITHUB_RELEASE_URL` placeholders anywhere in the signup
package after the swap.

### Checkpoint E — per-step Copy buttons

```
$ grep -n 'data-copy-target\|id="step-' \
    packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html
40:          <pre ...><code id="step-1-code">...
41:          <button type="button" data-copy-target="step-1-code"
49:          <pre ...><code id="step-2-code">...
50:          <button type="button" data-copy-target="step-2-code"
58:          <pre ...><code id="step-3-code">...
59:          <button type="button" data-copy-target="step-3-code"

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/test_app.py -q
...sss
3 passed, 3 skipped in 0.68s
```

Browser-side behaviour (clipboard write + "Copied" feedback) cannot be
exercised in unit tests; it relies on the same `navigator.clipboard` /
selection-fallback pair the existing token-box button uses, which is
already known to work on the deployed site. Live verification waits
for the next signup deploy.

### Checkpoint F — fix Copy button overlap on long commands

First iteration positioned the Copy button absolutely at the pre's
top-right with `pr-20` padding inside the pre. Long commands (the
Step 1 pip URL and the Step 2 `claude-manage setup ... --server-url
...` line) still passed under the opaque button as the pre scrolled,
making the right edge of the text unreadable.

Fix: dropped `absolute` positioning. Each pre is now a `flex-1
min-w-0` sibling of the Copy button inside a `flex items-stretch
gap-2` container — mirrors the existing token-box layout. The pre
gets the full available width and scrolls horizontally inside its
own clipping box; the button lives outside that clipping box on the
right and never visually intersects the code.

Test untouched — `id="step-N-code"` / `data-copy-target="step-N-code"`
pairs survived the layout change.

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/test_app.py -q
...sss
3 passed, 3 skipped in 1.58s
```

## Handoff

In-repo work is closed out. The remaining step is operator-owned:

- **Redeploy the signup app** so the new success page (with the concrete
  wheel URL) reaches participants:
  ```
  fly deploy -c packages/llm_tracker_signup/fly.toml
  # or just push to main and let .github/workflows/deploy-signup.yml run.
  ```
- After redeploy, sanity-check by hitting the live `/success?token=lts_demo`
  and confirming the rendered `pip install ...` line points at the
  v0.1.0 wheel asset URL.

## Suggestions (untouched)

- `[tool.hatch.version]` source-from-VCS could remove the manual version
  bump step later; not worth setting up before release #2.
- A second workflow `release-server.yml` mirroring this one (tag
  `server/v*`) could replace the current always-deploy-on-main posture
  for the server, giving release-gated control. Out of scope here; bring
  it up in the next infra session.
