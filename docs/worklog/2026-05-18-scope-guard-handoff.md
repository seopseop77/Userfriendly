# 2026-05-18 · scope_guard track — handoff

**Author**: Claude Code
**Session trigger**: "이 파트를 다른 사람이 맡아서 하기로 했거든. 그래도
이걸 나중에 plugin으로 넣을 수도 있으니까 일단 이 상태로 남겨두고 다른
작업을 수행하도록 할 수 있을까? 이 쪽 파트는 적당히 마무리하고."
**Related docs**: ADR-0030, ADR-0031, prior worklogs
`2026-05-18-scope-guard-impl.md` and `2026-05-18-gemini-provider-swap.md`.

## Interpretation

The scope_guard track is being handed to a separate owner. The current
code stays — both for future plugin reuse and as the reference
implementation if the new owner reframes the feature (e.g. moves it
out of the plugin host into an offline analysis job). This session
does **no further scope_guard implementation work**; it only marks
the track inactive so the next session does not auto-resume it.

The earlier session's question — "왜 플러그인이냐 vs. 분석 코드로
빠져야 하는 거 아니냐" — was not resolved here. It is recorded for the
new owner under "Open architecture question" below.

## What was done

- Created this worklog as the explicit inactive marker.
- Updated `docs/STATUS.md` to point at this file as the active
  worklog, replace the "Next active step" with "no active scope_guard
  work — track handed off", and add the new "Queued follow-up:
  scope_guard architecture re-examination" entry.

No code, no migration, no test, no plugin manifest change. The
implementation as of commit `0c1ca9d` is the handoff snapshot.

## Snapshot at handoff

**Code**:

- `packages/llm_tracker_plugin_scope_guard/` — full plugin (8 source
  files + 7 test files + `pyproject.toml` + `plugin.toml`).
- `packages/llm_tracker_server/alembic/versions/0010_scope_guard_tables.py`,
  `0011_scope_alerts_retention.py`,
  `0012_scope_chunks_embed_dim_768.py` — the three migrations.
- Core (`packages/llm_tracker/`, `packages/llm_tracker_server/` aside
  from the three migration files above) was **not touched** by the
  scope_guard track. Plugin discovery is entry-point based, so the
  host did not require any core edit.

**Provider**: Gemini (`text-embedding-004` + `gemini-2.5-flash`) per
ADR-0031. `OPENAI_API_KEY` is no longer read anywhere; the active env
var is `GEMINI_API_KEY`. `scope_chunks.embedding` is `vector(768)`.

**Tests**: 38 offline scope_guard tests pass; full repo suite 213
passed + 26 DB-skipped on the OpenAI-era CP8 baseline. Same numbers
on the Gemini swap. No regressions in the rest of the repo from any
scope_guard CP.

**Database posture (production / fly.io)**: The three migrations
(0010 / 0011 / 0012) deploy as part of any `alembic upgrade head`
run. They are non-destructive on a fresh DB (new tables, new
`pg_cron` job, empty column). `scope_chunks` is empty by the
operator's confirmation at ADR-0031-acceptance time; if any prior
deploy populated it under `vector(1536)`, migration 0012 erases the
column — but the same confirmation implies that has not happened.

## How to keep the plugin dormant

The cleanest dormancy posture is **leave the code in tree, disable
the plugin at runtime**:

```
fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server
```

Effect: the host still discovers the entry-point, but
`PluginHost.load_plugins` skips it (per `docs/plugins.md` and the
plugin-disable mechanism). The plugin's `on_init` does not run, no
Gemini egress happens, no rows land in `scope_alerts`. Removing the
secret re-enables it without any code change.

Alternatives considered:

- **Don't set `GEMINI_API_KEY` on fly**. Also works (the plugin's
  fail-closed `on_init` disables itself with a `structlog.warning`),
  but every process start logs a `scope_guard.disabled` line. The
  `LLMTRACK_PLUGINS_DISABLED` route keeps logs clean.
- **Remove the workspace member from root `pyproject.toml`**. Deeper
  dormancy (the package is not even installed), but the next owner
  has to re-register it before they can iterate. Overkill for a
  short-term pause.

## What the new owner picks up

- **`docs/decisions/0030-scope-guard-plugin.md`** — full feature
  design + nine-axis rationale. Status: Accepted; no edits needed.
- **`docs/decisions/0031-scope-guard-gemini-provider.md`** —
  provider swap. Status: Accepted. The deferred question (provider
  diversification framework) is recorded under §"Open questions".
- **`docs/worklog/2026-05-18-scope-guard-impl.md`** — CP1–CP8
  implementation narrative. The "Handoff" / "What's left" sections
  point at operator-side live smoke.
- **`docs/worklog/2026-05-18-gemini-provider-swap.md`** — the
  provider swap commit's worklog with verification logs and the
  35-char `alembic_version` fix-up.

## Open architecture question (carried to the new owner)

Quoted from the earlier session, paraphrased for the worklog:

> scope_guard runs on `on_persisted`, is observe-only, and only
> writes alert rows. Its behavioural contract overlaps almost
> entirely with an offline batch analyser. Is the plugin model the
> right home, or should this be reframed as an analysis job (e.g.
> `pg_cron` worker, ad-hoc operator CLI, or a separate scheduled
> process)?

The current ADR-0030 §Axis 1 only compared synchronous block vs.
asynchronous `on_persisted` — offline batch was **not** considered.
The new owner is invited to add an ADR-0032 if they want to reframe;
the existing plugin code remains usable either way (the
embedding / chunker / pipeline modules port cleanly to an out-of-host
runner).

Trade-off summary, for context:

- Keeping it in the plugin host **reuses**: `HookContext`'s scrubbed
  `request_text()`, `org_id` resolution, `EgressGuard` allowlist +
  audit on Gemini calls, per-plugin disable switch, and the
  automatic per-exchange dispatch.
- Moving it to a batch analyser **gains**: cleanly separated
  "analysis" concern, easier threshold-tuning replay over historical
  `exchanges`, less coupling to the request path. **Loses** all of
  the plugin-host integrations above; they'd need to be rebuilt at
  the analyser layer.

## What's left / known limits

- **Live smoke not performed.** No real `GEMINI_API_KEY` has touched
  the deployed plugin. Whether the new owner runs the smoke as a
  pre-condition for their reframe work is up to them.
- **Dormancy is operator-side, not code-side.** This session does
  not commit any dormancy switch into the repo. The fly.io secret
  above is recommended but not mandated; the new owner can keep the
  plugin live and iterate against it if they prefer.

## Handoff

The scope_guard track is **inactive** as of this worklog. The next
single step is whatever the original requestor lines up next — *not*
a scope_guard CP. If a future session resumes scope_guard work, the
entry point is this file's "What the new owner picks up" list.
