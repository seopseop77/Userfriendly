# 2026-05-25 · Swap participant install recommendation to `uv tool install`

**Author**: Claude Code
**Session trigger**: Operator tried `pip3.12 install <wheel-url>` on their own
mac as participant #1, hit `error: externally-managed-environment` from PEP
668 / Homebrew Python. After a back-and-forth on alternatives, operator
asked: "옵션 B로 가는 ADR 작성하고, 그거에 따라서 success 페이지나 이런
거까지 수정해줘" (i.e. ADR + downstream docs/UI in one pass).
**Related docs**: ADR-0034 (distribution channel — wheel on GitHub
Releases, amended), ADR-0035 (this session's output),
`docs/deploy.md#participant-installation`,
`packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`

## Interpretation

The forcing function was a real PEP 668 failure on participant #1's
machine. ADR-0034's recommended `pip install <wheel-url>` /
`pipx install <wheel-url>` was the proximate cause, and its
justifying premise — "every Claude Code user has Python 3.11+" — turned
out to be factually wrong (Claude Code is npm/Node, not Python). The
audience-friendly fix is `uv tool install`: uv ships its own Python so
PEP 668 stops being relevant for our install flow.

Scope of this session, as I read it:

- New ADR justifying the swap (Option B from the chat: uv tool install).
- Update the user-facing surfaces that hand out the install command
  (`success.html` + `docs/deploy.md`).
- Update the existing route test so the new recommended command is
  asserted and the old `pip install` line cannot silently come back.
- Do NOT change the distribution channel itself (still GitHub Releases
  wheel) or the release CI workflow — those are correct under ADR-0034
  and untouched.

I did not build the `curl | sh` bootstrap script (Option 4 in ADR-0035)
nor the PyInstaller single-binary path (Option 5); both are left as
open questions in ADR-0035 §Open questions.

## What was done

- Created `docs/decisions/0035-thin-agent-uv-tool-install.md` —
  ADR-0035, "Thin-agent install command: `uv tool install`". Documents
  the PEP 668 incident, the factual error in ADR-0034 reason #2
  (Claude Code is Node-based, not Python-based), the five options
  considered, and the chosen Option 3 (`uv tool install`). Distribution
  channel and release CI are explicitly left unchanged. (commit ff5fac0)
- Modified `docs/decisions/0034-thin-agent-github-releases.md` — status
  line updated to `Accepted (install command amended by ADR-0035,
  2026-05-25)`; prepended an "Amendment note" callout pointing readers
  at ADR-0035 for the current install command. ADR-0034's
  distribution-channel decision (Option 1 in that ADR) is preserved.
  (commit ff5fac0)
- Modified
  `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html` —
  Step 1 ("Install") becomes a two-substep block: (a) install uv via the
  `astral.sh/uv` shell installer with a `<details>` disclosure for the
  Windows PowerShell equivalent, then (b) `uv tool install <wheel-url>`.
  Each new command snippet gets its own `step-1-uv-code` /
  `step-1-uv-win-code` id and a copy button using the existing
  `data-copy-target` pattern. The wheel URL and the `step-1-code` /
  `step-2-code` / `step-3-code` ids are preserved so the existing route
  tests still cover them. Steps 2 and 3 unchanged. (commit ff5fac0)
- Modified `docs/deploy.md` — rewrote "Participant Installation →
  Requirements" to lead with uv (no Python prerequisite) and demote
  `pip` / `pipx` to a fallback paragraph that names the PEP 668
  hazard explicitly. "Install" block now shows uv install + uv tool
  install; "Upgrading" / "Uninstall" become `uv tool install --force`
  and `uv tool uninstall`. Appended a new "Fallback: `pipx` / `pip`
  (not recommended)" section that retains the previous commands for
  participants who insist. (commit ff5fac0)
- Modified `packages/llm_tracker_signup/tests/test_app.py` —
  `test_get_success_renders_token` now asserts (a) the rendered Step 1
  contains `uv tool install https://github.com/seopseop77/Userfriendly`,
  (b) it contains the `curl -LsSf https://astral.sh/uv/install.sh | sh`
  bootstrap line, and (c) `step-1-uv-code` / `step-1-uv-win-code` ids
  are present with matching `data-copy-target` buttons. The existing
  assertions on the wheel URL and the three primary step ids are kept
  unchanged. (commit ff5fac0)

## Decisions

- **Treated ADR-0035 as an amendment to ADR-0034, not a supersession.**
  ADR-0034 split into two coupled choices: distribution channel (still
  correct — GitHub Releases wheel) and install command (broken — `pip
  install` under PEP 668). Marking the entire ADR Superseded would
  mis-signal that the wheel-on-Releases decision is up for re-litigation;
  it isn't. The amendment-note approach keeps ADR-0034 readable as
  history while pointing forward to ADR-0035 for the current install
  command. ADR-0035 §Decision spells out exactly what ADR-0034 keeps
  vs. loses.
- **Kept the wheel URL and CI workflow (`.github/workflows/release-agent.yml`)
  untouched.** uv tool install consumes the same standard wheel artifact;
  no release-side change is needed. Verified by reading ADR-0034 §Operating
  shape and noting that "asset URL" is the only contract uv depends on.
- **Did not build Option 4 (`curl | sh` bootstrap script).** Tempting —
  it would collapse Step 1 from two commands to one — but it introduces a
  new script artifact to author, test cross-shell, and keep in sync per
  release. Filed as ADR-0035 §Open question instead so we can revisit
  after seeing how the two-line flow lands with real participants.
- **Did not pre-empt Option 5 (PyInstaller single binary).** Already in
  ADR-0034's open questions and gated by code-signing cost; ADR-0035
  defers without changing its priority.
- **Used `<details>` for the Windows PowerShell variant on the success
  page.** Keeps the macOS/Linux/WSL command visually primary (the
  expected majority of participants) without hiding the Windows option.
  Each variant has its own copy button so neither audience is
  second-class.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/test_app.py -q
...sss                                                                   [100%]
3 passed, 3 skipped in 0.57s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_signup/tests/test_app.py
All checks passed!
```

The 3 skipped tests are the DB-touching `app_with_engine`-based ones that
require `LLMTRACK_TEST_DATABASE_URL` — same baseline as the prior session
(`2026-05-21-agent-release-pipeline.md`), not a regression introduced
here.

Operator-side manual verification (PEP 668 incident that triggered this
ADR) — already captured in the session transcript:
- `/opt/homebrew/Cellar/python@3.12/3.12.12_2/Frameworks/Python.framework/Versions/3.12/lib/python3.12/EXTERNALLY-MANAGED`
  confirmed present → `pip3.12 install <wheel-url>` correctly refuses
  with the PEP 668 error message.
- `/usr/bin/python3` (Apple 3.9.6) has no marker but is < 3.11 so the
  wheel's `requires-python = ">=3.11"` would refuse it anyway.

I did **not** end-to-end-test the new `uv tool install <wheel-url>`
flow on the operator's machine in this session — that's the natural
"participant #1 again, this time with the new command" step the
operator can run as the next manual sanity check.

## What's left / known limits

- **Operator-owned: redeploy signup app to Fly** so the live success
  page picks up the new Step 1. Same redeploy command as the prior
  session.
- **Operator-owned: re-do participant #1 install with the new command.**
  Expected:
  ```
  curl -LsSf https://astral.sh/uv/install.sh | sh
  exec $SHELL -l                                # pick up updated PATH
  uv tool install https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.0/llm_tracker_agent-0.1.0-py3-none-any.whl
  claude-manage --help
  ```
- **No automation around upgrades.** ADR-0035 keeps the manual
  re-distribute-the-URL model from ADR-0034. Auto-update remains
  out of scope.
- **Bootstrap-script consolidation (`curl | sh` one-liner)** — left as
  ADR-0035 §Open question. Decide after first real participant install.

## Handoff

**Next single step**: operator redeploys the signup app to Fly and then
re-runs the install on their own machine using the new two-line flow,
to confirm `claude-manage --help` resolves and the success page renders
the updated Step 1 in production:

```
fly deploy -c packages/llm_tracker_signup/fly.toml
# or push to main and let .github/workflows/deploy-signup.yml run
# then visit https://llm-tracker-signup.fly.dev/success?token=lts_demo
```

If the production page still shows the old `pip install ...` line, the
deploy didn't pick up the template change — investigate the Docker
image layer cache before re-litigating the ADR.

## Follow-up touch-ups (same session)

Operator ran the new two-line flow on their own laptop and surfaced two
small UX issues that landed before the redeploy:

1. **Brew uv → astral uv shadow.** Operator already had `uv` from
   Homebrew; copy-pasting `curl … | sh` installed a second uv at
   `~/.local/bin/uv` and pushed `~/.local/bin` ahead of
   `/opt/homebrew/bin` in PATH. Both uvs work but the update channel
   splits (`brew upgrade` vs `uv self update`). The `<details>`/skip
   note in Step 1 wasn't enough to prevent the muscle-memory copy-paste.
   Fix: wrap the bootstrap line in a POSIX guard
   (`command -v uv >/dev/null || curl …`) so an already-installed uv
   short-circuits the install. (commit pending)
2. **Step 2 command visually wrapped onto two lines** in the operator's
   browser when `proxy_server_url` is set to the live Fly URL — the
   combined `claude-manage setup <token> --server-url …` exceeds the
   pre block's render width and Tailwind's `overflow-x-auto` did not
   prevent wrap on its own. Fix: add `whitespace-pre` to every step
   `<pre>` so `white-space: pre` is locked in regardless of preflight
   defaults; `overflow-x-auto` then yields a horizontal scrollbar
   instead of a visual wrap. Copy still produces a clean single-line
   string because the DOM never had a newline in the first place — the
   visual wrap was CSS-only. (commit pending)

### What was done (follow-up)

- Modified
  `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html` —
  Step 1a `<code id="step-1-uv-code">` now reads
  `command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh`.
  Added `whitespace-pre` to all five step `<pre>` blocks
  (step-1-uv, step-1-uv-win, step-1, step-2, step-3). (commit pending)
- Modified `packages/llm_tracker_signup/tests/test_app.py` — the
  uv-bootstrap assertion now requires the full guarded line including
  `command -v uv >/dev/null ||` prefix so a regression to the bare
  `curl … | sh` form fails fast. The literal `>` is verbatim in the
  rendered body — Jinja autoescape only touches `{{ variable }}`
  outputs, not static template text. (commit pending)

### Verification (follow-up)

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/test_app.py -q
...sss                                                                   [100%]
3 passed, 3 skipped in 0.47s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_signup/tests/test_app.py
All checks passed!
```

Operator-side visual verification of the wrap fix is still pending the
Fly redeploy (same as the main worklog body — the redeploy is the
forcing function).

## Suggestions (untouched)

- **Bake a `Last updated` timestamp into `success.html`** so we can tell
  at a glance whether the deployed copy is the post-ADR-0035 version
  without having to grep its source. Not done in this session; trivial
  if we want it later.
- **Consider linking ADR-0035 from the success page footer** as a
  participant-facing rationale for why we recommend uv. Probably noise
  for the average participant; mentioned for completeness.
- **Windows PowerShell equivalent of the `command -v` guard** would be
  `if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { irm … | iex }`,
  uglier and harder to copy-paste. Left as-is for now — the
  `<details>` disclosure already implies "use if needed".
