# ADR-0013 · Config-based plugin disable list

- **Status**: Accepted
- **Date**: 2026-05-07
- **Author**: Claude Code (user-approved in chat)
- **Related**: ADR-0005 (framework-first plugin architecture), ADR-0008
  (plugin signing trust model), `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`
  (`load_plugins`), CLAUDE.md §10 (env var names are public-interface
  contracts)

## Context

`PluginHost.load_plugins` discovers plugins via Python entry points
(group `llm_tracker.plugins`) and loads everything it finds. Today the
only ways a plugin can be filtered out are: missing `plugin.toml`,
signature failure, or capability denied for the active mode. There is
no operator-controlled "turn this plugin off" switch.

The user wants to disable a specific plugin without uninstalling its
package or editing `pyproject.toml`. The proxy is a local sidecar so
the disable knob belongs in the same env-prefixed configuration the
rest of the runtime already uses (`LLMTRACK_*`, `pydantic-settings`).

## Options considered

1. **Uninstall the package.** Dropping it from the environment removes
   its entry point. Works today, but heavyweight: requires `uv pip
   uninstall` (or workspace edits) and reinstall to re-enable. Doesn't
   support per-environment toggling — staging vs. local can't disagree
   on the active set.
2. **Allowlist (`plugins_enabled`).** Operator names every plugin they
   want loaded. Safer in spirit (default-deny) but inverts the current
   "ship a plugin, it loads" expectation and forces the operator to
   maintain a list every time a new plugin is added. Wrong default for
   a framework that wants plugins discoverable.
3. **Denylist (`plugins_disabled`).** Operator names plugins to skip.
   Cheap, additive, matches the local-sidecar mental model ("turn this
   one off for now"). The default is unchanged: every entry-point
   plugin still loads.
4. **Manifest-side flag.** Author marks the plugin disabled in
   `plugin.toml`. Wrong layer — the operator owns deployment config,
   not the plugin author.

## Decision

**Pick option (3) — env-driven denylist matched by manifest name.**

- New setting: `Settings.plugins_disabled: list[str] = []`, env var
  `LLMTRACK_PLUGINS_DISABLED`, comma-separated (a single string is
  split with whitespace trimmed; empty entries dropped).
- The host receives the resolved set as a constructor argument
  (`plugins_disabled: frozenset[str] = frozenset()`) so unit tests do
  not depend on environment variables.
- Match key: **`manifest.name`** (the value from `plugin.toml`), not
  the entry-point name. Two reasons:
  - The manifest name is what the user *sees* — audit logs, signing
    artifacts, future `llm-tracker plugins` output all key on it.
  - The entry-point name is in `pyproject.toml`, which the operator
    typically does not edit.
  Trade-off: the gate must run *after* `_find_manifest` parses the
  TOML. Cost is one extra TOML read per disabled plugin per startup,
  which is negligible.
- Position in `load_plugins`: immediately after `_find_manifest`
  succeeds, before signature verification. The signature still gets
  recorded as `manifest_rejected` if the operator un-disables a plugin
  whose `.sig` is broken — but a *currently-disabled* plugin never
  reaches the verifier, so a flapping `.sig` doesn't spam the audit
  log while the plugin is off.
- Audit row when a plugin is skipped:
  - `kind = "plugin_skipped"` (new audit kind)
  - `plugin = manifest.name`
  - `outcome = "denied"` (consistent with `manifest_rejected` and
    `capability_denied`)
  - `detail_json = {"reason": "disabled_by_config"}`

## Consequences

### What this enables

- Operators can flip a plugin off with `export
  LLMTRACK_PLUGINS_DISABLED=token_counter` and a proxy restart.
- Per-environment overrides ride for free on whatever
  pydantic-settings already supports (env, `.env` file, programmatic).
- The disable decision is visible in `audit_log` for forensics —
  matches every other load-time rejection.

### What this constrains / forecloses

- The match key is locked to `manifest.name`. Entry-point name vs.
  manifest name divergence is an operator-visible footgun if a plugin
  ships with a name in `plugin.toml` that doesn't match the marketing
  name; the bundled plugins in this repo currently keep them aligned.
- Restart required for changes to take effect. The proxy reads
  settings only during `lifespan` startup; a denylist edit while the
  proxy is up is a no-op until the next start. This is an explicit
  non-goal — adding live reload would mean reasoning about
  half-loaded state, which is out of scope.

### Reversibility

High. Removing the field, the constructor argument, and the
`plugin_skipped` audit kind is mechanical. No persistent state depends
on the denylist.

## Open questions

- **`plugins_enabled` allowlist.** Deferred. The denylist covers the
  immediate need; an allowlist can be layered on later if a security
  posture demands default-deny. If both ever ship, the rule will be
  "denylist wins" (an explicit `plugins_disabled` entry trumps an
  implicit allowlist match).
- **Per-mode disable.** Out of scope. Operators that need different
  plugin sets per mode currently set `LLMTRACK_PLUGINS_DISABLED`
  alongside `LLMTRACK_MODE` per environment.
