# Distribution and update strategy (analysis)

**Status**: analysis document, preserved for historical context. The
distribution decision is now sealed in **ADR-0003** (Accepted, 2026-05-03):
monorepo with per-package `pyproject.toml` (uv workspace), per-package
hatchling build, git URL install for the demo phase, PyPI deferred.

The analysis below predates the framework pivot and the multi-package
decision — read ADR-0003 first.

## The problem

The proxy runs on the user's machine, so *something* has to be installed
locally — that fact is unavoidable. But how often the user must pull code
changes themselves is a design choice we can shape.

Key insight: what we want to change frequently is **policy, rules, and task
definitions**. The actual proxy / scrub / storage code stabilizes and rarely
changes. Splitting these two cadences in distribution sharply reduces user
friction.

After the pivot, the same insight applies but partitioned by package:
- The **framework core** is the slowest-moving piece.
- **Plugins** move at their own pace (fast, slow, abandoned, forked).
- **Rules / policies / task definitions** can be shipped via a plugin's
  data plane without code changes.

## Options

### Option A — PyPI package + `pip install -U`

The standard. `pip install llm-tracker`; updates via `pip install -U`.

- Pros: standard tooling; pip handles dependencies.
- Cons: requires Python on the user's box; updates require an explicit
  command.

### Option B — Single binary (PyInstaller / Nuitka / shiv)

Bundle Python and code into one executable so users without a Python env
can run.

- Pros: one file; easy install.
- Cons: cross-platform build pipeline; code signing; updates still manual.

### Option C — Auto-update built in

On startup, the proxy checks for a new version against a central server and
either prompts to upgrade or pulls automatically.

- Pros: no user action needed; can force-update.
- Cons: extra infrastructure; security risk demands signing and
  verification.

### Option D — Thin client + data plane hosted centrally

Extreme: the local side only forwards traffic; all processing (extraction,
scrubbing, judging) runs on a central service.

- Pros: one piece of code that almost never changes; improvements roll out
  centrally.
- Cons: every raw byte leaves the user's machine — directly contradicts our
  privacy stance. **Not viable** for this project.

### Option E — Thin core + remotely-synced rules (recommended)

A variant of A. Code ships via a package; policies pull from a remote
source and hot-reload.

- In code: proxy, adapters, scrubbers, judge interfaces, storage. Rarely
  changes once stabilized.
- Remote: TaskDefinitions, judge thresholds, scrub policies, block-message
  templates. Frequent updates without user action.

After the framework pivot, this becomes per-plugin: each plugin can pull
its own rules from its own backend on its own schedule.

## Recommendation

**Option E + Option A + a touch of C**.

1. Distribute `llm-tracker` (the core) via **PyPI** or a private mirror.
2. Recommend installation with `pipx install llm-tracker` (isolated env,
   CLI immediately available).
3. On startup the proxy does **version check** (notify only by default;
   force-update flag for breaking changes) and a **rule sync** (pull
   updated policy/task data into local SQLite).
4. **Do not auto-download/install code.** Operator security trade-off:
   manual upgrades + manifest signatures > automatic install for the
   research-scale audience.

## What the user sees

**First-time enrollment**:

```bash
export LLMTRACK_ENROLL_TOKEN=...     # operator-issued
pipx install llm-tracker
llm-tracker enroll                    # exchange token, fetch task defs
llm-tracker start --task <id>         # start the proxy
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
claude
```

**Daily**: `llm-tracker start --task <id>`. Tasks and rules sync in the
background.

**When code changes (rare)**:

```bash
pipx upgrade llm-tracker
```

Operator notifies via email/Slack. Forced upgrade is achieved by refusing to
start old versions when a critical change ships.

## Future

If usage broadens beyond research participants, revisit Option B (single
binary) and Option C (auto-update). At current scale, E + A is enough.
