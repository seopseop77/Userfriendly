# Interactive slash-command probe (runbook)

The 2026-05-28 headless campaign proved that **`claude -p` headless mode
does not parse slash commands** — `/help`, `/clear`, `/compact` etc. pass
through as plain user text, so the classifier branches that strip
`<command-name>` / `<local-command-*>` wrappers and the post-`/compact`
resume marker are *unreachable* from the headless runner
(see `results/2026-05-28-r013-thru-r022-r026-slash-not-parsed.md`).

The only vector that exercises those branches is an **interactive Claude
Code session routed through the same proxy**, with the operator typing
the slash commands. This runbook is that vector.

> **Roles for this probe**: the *operator* (human) types the commands at
> the keyboard. *Claude Code* (the assistant) does **not** drive the REPL
> — it only runs the Supabase analysis afterward from the timestamp +
> tag the operator hands back.

---

## What we're trying to reach

The interactive client pre-processes slashes into wrapper-text blocks that
the proxy then sees. The classifier branches not yet observed live:

| target | produced by | classifier branch |
|---|---|---|
| `<command-name>/x</command-name>` + slash_commands extraction (regex `<command-name>/([A-Za-z0-9_\-]+)</command-name>`) | any local slash (`/help`, `/cost`, …) followed by a model turn | ADR-0038 slash_commands extraction |
| `<local-command-stdout>` / `<local-command-*>` / `<command-message>` wrappers | local slash output folded into the next API call's history | ADR-0038 wrapper-strip |
| post-`/compact` resume marker (`This session is being continued from a previous conversation…`) | `/compact`, observed on the *next* turn after it | ADR-0038 resume-marker strip |
| `<session>…</session>` single-element title-gen sidecar | client title generation (may fire on its own) | ADR-0038 single-element `<session>` regex (F-4 suspected effectively unreachable — confirm) |

Hypotheses to confirm per branch:
- The wrapper-bearing turn classifies correctly (`user_input` with wrappers
  stripped, **not** `sidecar`) and `turn_seq` stays gap-free.
- `slash_commands` is populated with the command name(s).
- The post-`/compact` turn is recognised as a continuation of the **same**
  `conversation_id`, not a new one.
- Whether the single-element `<session>` branch ever actually fires.

---

## 0. Prerequisites

Same as `README.md §0` (claude + claude-manage on PATH, Keychain OAuth,
`~/.llm-tracker/config.toml`, Supabase MCP available to the analysing
session). The proxy + Fly server must be live.

---

## 1. Launch

No wrapper script needed — just run `claude-manage` interactively from
your own terminal:

```bash
date +%s                      # ← record this; the §4 queries filter on it
claude-manage --model sonnet  # interactive REPL, routed through the proxy
```

That's it. `claude-manage` with no `-p` forwards straight to an
interactive `claude`, only setting `ANTHROPIC_BASE_URL` to the proxy
(`cli.py`).

Notes:
- **No `env -u ANTHROPIC_*` needed.** That prelude only matters when
  spawning from *inside* a Claude Code session (the parent injects
  `ANTHROPIC_API_KEY`). From your own shell those vars aren't set.
- `--model sonnet` keeps the prompt cache consistent across turns — not
  load-bearing for slash classification, but cheap and tidy. You can also
  pin it later with `/model`.
- Optionally `cd "$(mktemp -d)"` first for a clean workdir so the repo's
  `CLAUDE.md` doesn't enter the system prompt — irrelevant to slash
  classification, so skip it unless you want the isolation.
- **Record the `date +%s` value** — the Supabase queries in §4 filter on
  it (multiply by 1000 for `started_at`, which is epoch ms). Don't run
  other Claude traffic while this session is open, so the window stays
  clean.

---

## 2. Pick a session tag

Choose one tag for the whole interactive session, e.g. `s001`, and
remember today's date. The anchor message (step 1 below) carries it as a
`[PROBE 2026-05-29 s001]` prefix so the analysis can find the
`conversation_id`. Slash-driven turns won't carry the prefix — that's
expected; §4 recovers them via the conversation_id, not the prefix.

---

## 3. Conversation plan (type these in order)

Run sequentially in the one REPL. Wait for each reply before the next.
After a *local* slash command (e.g. `/help`), the wrapper blocks only
reach the proxy on the **following** model turn — so each slash is
followed by a normal message that forces an API round-trip.

| step | type this | what it exercises |
|---|---|---|
| 1 | `[PROBE 2026-05-29 s001] Reply with one short sentence so this turn anchors the conversation.` | anchor — `user_input`, establishes conversation_id + first row in the time window |
| 2 | `/help` | local slash — emits `<command-name>help</command-name>` + `<local-command-stdout>` into history |
| 3 | `In one line, what kind of output did the previous command show?` | forces the API call that carries step-2's wrappers |
| 4 | `/cost` | another local slash with stdout |
| 5 | `Reply with just: ok` | carries step-4's wrappers |
| 6 | `/compact` | triggers a summarisation API call; sets up the resume marker |
| 7 | `Reply with just: resumed` | first post-compact turn — should carry the `This session is being continued…` resume marker |
| 8 | `/clear` | clears local context |
| 9 | `[PROBE 2026-05-29 s001] Reply with one short sentence so this turn anchors the conversation.` | **identical** text to step 1 — tests whether the B-rule chain-lookup merges this into step-1's conversation_id after a `/clear` |
| 10 | `/exit` | end the session |

Notes:
- Steps 8–9 are the real version of the headless r020 hypothesis (which
  had to skip `/clear` because headless can't run it). Confirm whether
  `/clear` + identical re-type lands in the **same** conversation_id.
- If `/compact` reports "nothing to compact", send 1–2 more throwaway
  messages first to build history, then retry.
- Other slashes worth a pass on a second run if step 3/5 are clean:
  `/model`, `/agents`, `/memory`, `/config`, `/init` — each followed by a
  normal message. Add rows to the same table in the result doc.

---

## 4. Hand back to the analysing session

Give Claude Code these three things:

1. The `date +%s` you recorded at launch (call it `start_ms`; multiply
   by 1000 for the `started_at` epoch-ms filter).
2. The session tag + date (`[PROBE 2026-05-29 s001]`).
3. Roughly when you typed `/exit` (so the upper time bound is known).

Claude Code then runs (via `mcp__supabase__execute_sql`):

**Step A — find the conversation_id from the anchor row:**

```sql
SELECT conversation_id, turn_seq, role, created_at
FROM plugin_analytics
WHERE request_jsonb::text LIKE '%[PROBE 2026-05-29 s001]%'
ORDER BY created_at ASC;
```

**Step B — pull every row of that conversation (the slash turns have no
prefix, so filter by conversation_id, not the prefix):**

```sql
SELECT id, conversation_id, turn_seq, role,
       model_served, stop_reason,
       slash_commands,
       jsonb_array_length(request_jsonb) AS n_blocks,
       left(request_jsonb::text, 400)    AS req_head,
       created_at
FROM plugin_analytics
WHERE conversation_id IN (<ids from step A>)
ORDER BY created_at ASC, turn_seq ASC NULLS LAST;
```

**Step C — raw proxy traffic for the whole session window (catches any
row that did NOT land in plugin_analytics, the way Suggestion #2 was
found):**

```sql
SELECT id, started_at,
       to_timestamp(started_at/1000.0) AT TIME ZONE 'UTC' AS started_utc,
       endpoint, model_requested, model_served, status_code,
       latency_ms, stop_reason
FROM exchanges
WHERE started_at >= <start_ms>
ORDER BY started_at ASC;
```

**What the analysis checks:**
- Each slash-followed turn → `role = user_input` with wrappers stripped
  (not `sidecar`); `turn_seq` gap-free.
- `slash_commands` populated with the typed command name(s).
- Step-7 post-compact row → same `conversation_id` as steps 1–7, resume
  marker recognised (not re-classified).
- Steps 8–9 → does the re-typed identical message merge into step-1's
  conversation_id (B-rule) or open a new one?
- Whether any row carries the single-element `<session>…</session>` shape
  (F-4: confirm or falsify that branch fires at all).
- `exchanges` row count ≈ API round-trips sent (steps 1,3,5,6,7,9 ≈ 6+);
  any exchange with no matching plugin_analytics row is signal.

Findings get a result doc `results/2026-05-29-sNNN-interactive-slash.md`
following `README.md §6`, and anything genuinely new appends to the origin
worklog Suggestions.

---

## 5. Pitfalls (in addition to README §8)

- **Don't use `-p` and don't pass `--disallowedTools '*'`** — that's the
  headless path this runbook exists to avoid. Plain `claude-manage` (no
  `-p`) is interactive, which is what we want.
- **One session, no concurrent Claude traffic** — the analysis leans on
  the `start_ms` time window; other traffic in that window muddies it.
- **Local-only slashes need a following message.** `/help` alone may never
  hit the API; its wrappers ride the next model turn. The plan in §3
  already pairs each slash with a forcing message.
- **`/clear` does not end the process** — it clears context in-place. Use
  `/exit` to finish.
