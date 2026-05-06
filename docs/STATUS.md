# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 11 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass in progress)
- **Active task**: audit_log append-only triggers landed; ADR-0008 housekeeping next (Checkpoint F, docs only).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
2891e8f   storage: audit_log append-only DB triggers (ADR-0006)
b06623a   docs: Phase 1b checkpoint 10 — synthetic SSE block response
b1724fa   proxy: synthetic SSE block response per ADR-0002 §3
ebb581a   docs: Phase 1b checkpoint 9 — on_persisted ordering fix
a2bc3d4   proxy: fix on_persisted ordering relative to DB write
```

## Where we paused

Phase 1b cleanup-pass checkpoint E complete (2026-05-06, commit
2891e8f). The `audit_log` table is now DB-enforced append-only
via two SQLite triggers — `audit_log_no_update` and
`audit_log_no_delete` — each `RAISE(ABORT, 'audit_log is
append-only')`. The DDL constants live in `storage/models.py`
alongside the ORM model and are attached to
`AuditLog.__table__`'s `after_create` event so test fixtures
using `Base.metadata.create_all` install them automatically. The
new Alembic migration imports the same constants, keeping prod
and test paths in lockstep. ADR-0006's "audit-log integrity"
open question is closed.

112/112 tests pass; touched files lint clean.

Cleanup pass progress: A, B, C, D, E closed. Remaining: F
(ADR-0008 housekeeping, docs only), G (session_factory property
+ ADR-0009 for `allowed_modes` default tightening). Then Gates
1/2 with user input.

## Next single step

**Checkpoint F — ADR-0008 housekeeping.** Edit
`docs/decisions/0008-plugin-signing-trust-model.md` to mark four
"What is deferred" items RESOLVED with the values already shipped:

- Canonicalization → byte-exact contents of `plugin.toml`.
- Signature blob format → sibling TOML, `signer` + hex
  `signature`.
- Registry file format → TOML `[[key]]` array, `name` + hex
  `public_key`.
- Signing CLI → `llm-tracker generate-key` / `sign-plugin`
  (checkpoint 8) + reference-plugin signing flow (developer
  signs `hello_world` for now).

Leave deferred: boot-time verification cache, key rotation
policy, revocation mechanism.

Docs-only checkpoint; no code or tests change.

## Blocking / decisions needed

- None for Checkpoint F.
- Gates 1 (Transform handling) and 2 (hook payload routing)
  remain deferred.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [ ] Phase 1b — security boundary hardening (in progress)
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
