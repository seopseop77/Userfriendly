# 2026-05-07 · plugin disable config + introspection

**Author**: Claude Code
**Session trigger**: User: "config 형태로 바꾸고, llm-tracker plugins 형태로 현재 plugin 확인할 수 있는 형태로 만들어줘." Disable mechanism keyed on `manifest.name`, restart-required (no live-reload).
**Related docs**: ADR-0013 (plugin disable config), ADR-0014 (`llm-tracker plugins` + `/admin/plugins` introspection), CLAUDE.md §10 (env var + CLI flag + HTTP path are public-interface contracts), prior worklog `docs/worklog/2026-05-07-claude-manage.md` (sister CLI ergonomics work)

## Interpretation

User asked for two things in sequence:

1. A way to disable a specific plugin without uninstalling its package
   or editing `pyproject.toml`. They explicitly chose **manifest-name
   matching** over entry-point-name matching for the operator-visible
   identifier ("manifest name이 직관적").
2. A way to inspect what plugins the **currently running** proxy
   actually loaded — not what *would* load. Drives the choice of
   HTTP introspection over a static entry-points scan.

User confirmed the implication that config changes only take effect on
proxy restart (no live reload), and explicitly deferred a `--restart`
flag on `claude-manage` for now.

Three additions land together because they belong to the same operator
mental model: "set env var → restart proxy → run `llm-tracker plugins`
to confirm". Two ADRs (0013 disable, 0014 introspection) capture the
public-interface decisions per CLAUDE.md §10.

## What was done

### Decision records (commit 0a43502)

- Created `docs/decisions/0013-plugin-disable-config.md` — env-driven
  denylist `LLMTRACK_PLUGINS_DISABLED`, matches `manifest.name`,
  audit kind `plugin_skipped` with reason `disabled_by_config`.
- Created `docs/decisions/0014-plugins-introspection.md` —
  `GET /admin/plugins` returns the live `_manifests` view, `llm-tracker
  plugins` HTTPs the proxy and pretty-prints, route registered before
  the catch-all so it isn't forwarded upstream.

### Disable config (ADR-0013) — commit 161505d

- Modified `packages/llm_tracker/src/llm_tracker/config.py` —
  `Settings.plugins_disabled: Annotated[list[str], NoDecode]`. The
  `NoDecode` annotation keeps pydantic-settings from JSON-decoding
  the env var; a `field_validator(mode="before")` splits the CSV
  string with whitespace trim and empty-slot drop.
- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - `PluginHost.__init__` accepts `plugins_disabled: frozenset[str]
    | set[str] | None = None`, frozen on store.
  - In `load_plugins`, after `_find_manifest` returns a valid
    manifest, the host now checks `manifest.name in
    self._plugins_disabled` and writes a `plugin_skipped` audit row
    (`outcome="denied"`, detail `{"reason": "disabled_by_config"}`)
    *before* signature verification — so a flapping `.sig` on a
    disabled plugin doesn't spam the audit log.

### Introspection (ADR-0014) — commit 161505d

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - New `self._manifests: list[PluginManifest]`, populated in load
    order alongside `self._plugins.append(plugin)`.
  - New `loaded_plugins() -> list[dict]` returns `{name, version,
    hooks, capabilities, allowed_modes}` per loaded manifest.
- Modified `packages/llm_tracker/src/llm_tracker/proxy/app.py`:
  - Lifespan passes `frozenset(settings.plugins_disabled)` to
    `PluginHost`.
  - New `GET /admin/plugins` route registered **before** the
    catch-all so FastAPI's in-order dispatch reaches it first.
- Modified `packages/llm_tracker/src/llm_tracker/cli/main.py` — new
  `plugins` subcommand: GETs `http://{host}:{port}/admin/plugins`
  with a 2 s timeout, formats `name<24 v<8 hooks=… modes=…`, exits 1
  with stderr message on `httpx.HTTPError`.

### Tests (commit 161505d)

- Modified `packages/llm_tracker/tests/test_plugin_host.py` (+4 tests):
  - `test_load_plugins_skips_disabled_by_config` — denylist hit
    short-circuits before the verifier (asserted by an explosive
    `_verify_manifest` monkeypatch) and writes the `plugin_skipped`
    audit row with the right shape.
  - `test_load_plugins_disabled_match_is_manifest_name_not_ep_name`
    — pins ADR-0013's matching-key choice; an EP-name match must not
    skip, a manifest-name match must.
  - `test_loaded_plugins_returns_serialisable_view` — `_manifests`
    populates and `loaded_plugins()` returns the documented shape.
  - `test_loaded_plugins_empty_before_load` — bare host has `[]`.
- Created `packages/llm_tracker/tests/test_config.py` (+5 tests):
  default, CSV, empty-slot collapse, list passthrough, env-var path.
- Created `packages/llm_tracker/tests/proxy/test_admin.py` (+3 tests):
  handler returns the loaded view, handles missing `plugin_host`
  gracefully (returns `[]`), and FastAPI route ordering — admin index
  precedes catch-all index in `app.routes`.
- Created `packages/llm_tracker/tests/test_cli_plugins.py` (+4 tests):
  happy path, empty set, unreachable proxy → exit 1, custom
  `--host`/`--port` reaches the right URL.

## Decisions

- **Match key = `manifest.name`**, not the entry-point name (ADR-0013).
  Operator-visible identifier; aligns with audit logs and signing
  artifacts. Cost: one extra TOML read per disabled plugin per
  startup (negligible).
- **Gate position = after manifest parse, before signature verify**.
  ADR-0013 §Decision: a flapping `.sig` on a *disabled* plugin should
  not write `manifest_rejected` rows; the disable should win first.
  The verifier monkeypatch in `test_load_plugins_skips_disabled_by_config`
  pins this ordering.
- **Field annotation: `Annotated[list[str], NoDecode]`** —
  pydantic-settings v2 JSON-decodes complex env-var values *before*
  any field_validator runs. `NoDecode` opts out of that step so
  `LLMTRACK_PLUGINS_DISABLED=foo,bar` lands as a raw string the
  validator can split. Discovered when the env-var test surfaced a
  `JSONDecodeError`.
- **HTTP introspection over DB scan** (ADR-0014). Reading
  `AuditLog` for the most recent `proxy_started` would mis-report a
  crashed proxy as "loaded"; an HTTP probe distinguishes live from
  dead by definition. The new `/admin/plugins` route is registered
  before the catch-all — FastAPI dispatches in order, so any new
  admin route must follow the same precedent.
- **No live reload, no `--restart`** — explicitly user-deferred. The
  proxy reads settings only during `lifespan`; a denylist edit while
  the proxy is up is a no-op until the next start. Documented in
  ADR-0013 §Consequences.

## Verification

```
$ .venv/bin/python3.12 -m pytest -q
189 passed, 4 warnings in 1.60s
```

Targeted run on the changed surfaces:

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker/tests/test_config.py \
    packages/llm_tracker/tests/test_plugin_host.py \
    packages/llm_tracker/tests/proxy/test_admin.py \
    packages/llm_tracker/tests/test_cli_plugins.py -q
34 passed in 0.71s
```

Ruff on the changed files:

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker/src/llm_tracker/config.py \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker/src/llm_tracker/proxy/app.py \
    packages/llm_tracker/tests/test_config.py \
    packages/llm_tracker/tests/test_plugin_host.py \
    packages/llm_tracker/tests/proxy/test_admin.py \
    packages/llm_tracker/tests/test_cli_plugins.py
All checks passed!
```

Manual smoke: not yet run end-to-end against a live proxy. The
`llm-tracker plugins` happy path is covered by respx in unit tests,
but a real `claude-manage` → `llm-tracker plugins` integration check
remains pending alongside the long-deferred Phase 1b manual e2e.

## What's left / known limits

- **Manual e2e against a live proxy.** Boot the proxy with
  `LLMTRACK_PLUGINS_DISABLED=token_counter`, run `llm-tracker plugins`,
  confirm `token_counter` is absent and an audit row with
  `kind=plugin_skipped` exists. Bundles into the long-deferred
  Phase-1b manual check.
- **No allowlist (`plugins_enabled`).** ADR-0013 §Open questions
  defers this. Layer on later if a security posture demands
  default-deny.
- **No auth on `/admin/*`.** Proxy listens on `127.0.0.1` by default;
  if a future deployment binds to a wider interface, the admin
  endpoint will need a token (separate ADR).
- **No `--json` on `llm-tracker plugins`.** Human-pretty output only.
  Adding `--json` is a non-breaking extension when a downstream
  consumer needs it.

## Handoff

Phase 1c (`scope_guard`) is still on deck — the work this session
unblocks is **operator UX for the disable knob**, which scope_guard
will need once it ships (operators will want to turn it off when
debugging false positives). After this checkpoint, the next single
step remains the long-deferred Phase-1b manual e2e against real
Anthropic traffic, now with the additional check that
`LLMTRACK_PLUGINS_DISABLED` round-trips through `llm-tracker plugins`.

## Suggestions (untouched)

- **Pre-existing ruff errors** unrelated to this work: I001 in
  `cli/main.py:17-19` (alembic imports split by a blank line),
  F541/E501 in `tests/perf/report_first_token_latency.py`. Existed
  prior to this session (introduced by 3010aae or earlier). Not
  touched per CLAUDE.md §2.3 surgical-changes; flag for a future
  cleanup pass.
- **Consolidate audit-rejection vocabulary.** `manifest_rejected`,
  `capability_denied`, `plugin_skipped` all mean "plugin did not
  appear in `loaded_plugins()`". A future ADR could collapse them to
  one `kind="plugin_load_failed"` with a structured `reason`
  taxonomy, simplifying CLI/UI consumers. Not urgent.
- **`/admin/health`.** A liveness/readiness endpoint is a natural
  follow-up but has wider blast radius; warrants its own ADR.
