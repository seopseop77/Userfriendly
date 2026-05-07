# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-07 (plugin disable config + `/admin/plugins` introspection — code complete, manual e2e pending)
**Updated by**: Claude Code

## Current phase

- **Phase**: Pre-Phase-1c side-quest #3 — operator UX for plugin lifecycle. Phase 1b sealed at 75ff46a; Phase 1c (`scope_guard`) still on deck.
- **Active task**: Config-based plugin disable + live introspection — `LLMTRACK_PLUGINS_DISABLED` skips a plugin at load time (matched on `manifest.name`); `llm-tracker plugins` reads `/admin/plugins` on the running proxy to confirm what's actually loaded.

## Active worklog

`docs/worklog/2026-05-07-plugin-disable-config.md`

## Recent commits

```
161505d   plugins: disable config + /admin/plugins
0a43502   docs: ADR-0013/0014 plugin disable + introspect
9aa8321   cli: async cleanup so claude-manage exits instantly
d2e33d5   cli: claude-manage wrapper auto-starts proxy
faa718d   chore: add .omc to .gitignore
```

## Where we paused

**Plugin disable + introspection code-complete.** Two paired ADRs and
one feature commit:

- ADR-0013 (`docs/decisions/0013-plugin-disable-config.md`): the
  operator names plugins to skip via `LLMTRACK_PLUGINS_DISABLED` (CSV).
  The host gate runs *after* manifest parse (so we have the
  canonical name) but *before* signature verify (so a flapping `.sig`
  on a disabled plugin doesn't spam audit). Skipped plugins write
  `kind=plugin_skipped, outcome=denied,
  detail_json={"reason":"disabled_by_config"}`.
- ADR-0014 (`docs/decisions/0014-plugins-introspection.md`):
  `GET /admin/plugins` reads `PluginHost._manifests` and returns
  `[{name,version,hooks,capabilities,allowed_modes}, …]`. The route
  is registered before the catch-all so FastAPI's in-order dispatch
  reaches it first. `llm-tracker plugins` HTTPs that endpoint and
  pretty-prints; exits 1 if the proxy is unreachable.
- Implementation lives in `config.py` (`Annotated[list[str],
  NoDecode]` + CSV validator), `plugin_host/host.py` (`__init__`
  takes `plugins_disabled`, new `_manifests` list, new
  `loaded_plugins()`), `proxy/app.py` (lifespan wiring + admin
  route), and `cli/main.py` (new `plugins` subcommand).

16 new unit tests across `test_config.py` (+5), `test_plugin_host.py`
(+4 disable + introspection), `tests/proxy/test_admin.py` (+3), and
`test_cli_plugins.py` (+4). Full suite **189 passed**, ruff clean on
every changed file (3 pre-existing ruff errors elsewhere noted in
worklog Suggestions, untouched per §2.3).

Restart-required behaviour explicitly accepted: a denylist edit
while the proxy is up is a no-op until `lifespan` re-runs.
`claude-manage --restart` deferred per user direction.

**Pre-Phase-1c verification (2026-05-06) still applies** — the
TEST-ONLY plugins (`token_counter`, `keyword_block`) remain loaded
and ready for the long-deferred manual e2e against real Anthropic
traffic, which now also exercises the disable knob.

Closed-checkpoint roll-up (cleanup pass A–G + stop gates +
side-quests):

- A (e2ee4f0): EgressGuard wired into proxy lifespan
- B (3010aae): signature verifier wired + signing CLI
- C (a2bc3d4): on_persisted ordering fix
- D (b1724fa): synthetic SSE block response
- E (2891e8f): audit_log append-only triggers
- F (6a08c9c): ADR-0008 housekeeping
- G (96305e1): session_factory property + ADR-0009
- 14 (654fbfb): ADR-0010 retroactive (Block/Abort.plugin)
- 15 (cfbbb8e): ADR-0011 Transform policy
- 16 (bbb33e7): Transform impl + 4 tests
- 17 (4606ed0): ADR-0012 hook payload routing
- 18 (75ff46a): HookContext impl + 14 tests
- pre-1c verification (2c28f68): TEST-ONLY token_counter + keyword_block
- side-quest #2 (d2e33d5, 9aa8321): `claude-manage` wrapper + async cleanup
- side-quest #3 (0a43502, 161505d): plugin disable config + `/admin/plugins`

### Phase 1b loose ends

Known-deferred; each would be its own checkpoint when picked up:

- `end_exchange` cleanup in the forwarder (Block/Abort early
  returns + `generate()` finally). Bounded leak only.
- Per-level shape refinement of `ctx.request_text()` (L1 hash,
  L2 scrubbed) — wired in Phase 1c alongside scrubbers.
- Manifest `min_content_level` field — Phase 1c when scope_guard
  needs it.
- Response-side ctx accessors — wait for Extractor / structured
  response data.

## Next single step

Two paths, pick one:

1. **Manual real-traffic e2e via `claude-manage`** — in a fresh
   working directory, run `.venv/bin/llm-tracker init`, then
   `.venv/bin/claude-manage --print "hello"` (or any quick claude
   command). Verify `var/proxy.log` shows clean uvicorn startup, the
   exchange lands in `var/llm_tracker.db`, the token-counter sidecar
   db (`var/plugin_token_counter.db`) records usage, and the proxy
   process is gone after `claude` exits. **New for this checkpoint**:
   in another shell run `.venv/bin/llm-tracker plugins` and confirm
   the loaded set matches expectations; then export
   `LLMTRACK_PLUGINS_DISABLED=token_counter`, restart the proxy, and
   confirm `token_counter` is gone from the listing and that
   `llm-tracker audit` shows a `plugin_skipped` row.
2. **Open Phase 1c — `scope_guard` plugin.** Create
   `docs/worklog/<YYYY-MM-DD>-phase1c-scope-guard.md`, point this
   STATUS.md at it, and schedule removal of the now-redundant
   `keyword_block` test plugin in that worklog.

Both `keyword_block` (Phase 1c overlap) and `token_counter` (Phase 2
Extractor overlap) are explicit throwaways — track their removal
when the proper replacement lands.

## Blocking / decisions needed

- None.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [x] `claude-manage` wrapper — auto-spawn proxy + lifecycle-coupled cleanup (2026-05-07, commits d2e33d5, 9aa8321)
- [x] Plugin disable config + `/admin/plugins` introspection (2026-05-07, commits 0a43502, 161505d)
- [ ] Phase 1c — `scope_guard` plugin
- [ ] Phase 2+ — Mode R sink, third-party plugins

---

## Update rules (for Claude Code)

At every checkpoint, do these three as one atomic unit (CLAUDE.md §5.3):

1. `git commit` the code change (CLAUDE.md §11).
2. Append the new commit hash to the active worklog's "What was done"
   section, and rewrite the "What's left / Handoff" section as of *now*.
3. Refresh this STATUS.md:
   - Last-updated timestamp (YYYY-MM-DD).
   - Active worklog path.
   - Last 3–5 commits.
   - "Where we paused".
   - "Next single step".

If you don't bundle these three, the next session won't know where to pick
up.
