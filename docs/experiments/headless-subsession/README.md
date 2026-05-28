# Headless sub-session probe

Drive `claude-manage` from inside a Claude Code session to fan out
controlled conversation patterns through the proxy, then mine
`exchanges` + `plugin_analytics` in Supabase for manage-logic defects.

The "tester" is one Claude session running this runbook. The "subject"
is the sub-session it spawns via `claude-manage -p`, whose traffic
traverses the local proxy → Fly server → Anthropic. Anomalies are
found by **cross-checking what the sub-session reported with what manage
stored**.

> Origin probe: `docs/worklog/2026-05-28-headless-subsession-probe.md`
> (cache-hit verification + 3 anomalies already on file — see §7;
> don't re-file them).

---

## 0. Prerequisites

- `claude` on PATH (verify: `claude --version`).
- `claude-manage` on PATH — uv tool from `packages/llm_tracker_agent`.
- macOS Keychain has `Claude Code-credentials` (the tester's own login
  is reused by the sub-session; no separate auth step).
- Supabase MCP available to this session (used in §5).
- `~/.llm-tracker/config.toml` exists with server URL + token.

---

## 1. The invocation contract (load-bearing)

Every probe call is **one process, one turn, one prompt**, fully
isolated. Copy this shape exactly; each piece is load-bearing.

```bash
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BEARER_TOKEN \
  claude-manage -p --max-turns 1 --disallowedTools '*' --permission-mode plan \
  --model sonnet --output-format json \
  --session-id "$UUID" \
  "$PREFIX $PROMPT" \
  < /dev/null > /dev/null 2>&1
```

Why each piece matters:

| Piece | Why it's required |
|---|---|
| `mktemp -d` + `cd` | Empty working dir → parent `CLAUDE.md`, `.claude/`, plugin config don't leak into the sub-session's system prompt. |
| `env -u ANTHROPIC_*` | The tester's parent process has `ANTHROPIC_API_KEY` set (Claude Code injects it). `claude-manage` copies env verbatim, so the sub-session would try that key instead of Keychain OAuth → 401 with garbage body. Unset all three known token vars. |
| `claude-manage` (not bare `claude`) | The whole point — traffic must traverse the proxy. |
| `-p` | Headless print-and-exit. No interactive REPL. |
| `--max-turns 1` | Sub-session can't loop on its own. One LLM round-trip per call. |
| `--disallowedTools '*'` + `--permission-mode plan` | Sub-session can't invoke tools. No surprise file writes, shell, web fetches. |
| `--model sonnet` | **Pin the model.** Autoselect flips between `claude-opus-4-7[1m]` and `claude-opus-4-7` across turns of the same session, defeating the prompt cache. Pinning keeps `cache_read` healthy on `--resume`. |
| `--output-format json` | Machine-parseable usage counters in case you need to spot-check stdout (usually you don't — §3). |
| `--session-id "$UUID"` | Deterministic session identity for the first turn. Use `--resume "$UUID"` on follow-up turns. |
| `< /dev/null` | Without this, `claude -p` waits 3 s on stdin then proceeds with an empty prompt. |
| `> /dev/null 2>&1` | **Discard stdout/stderr.** Sub-session output otherwise streams into the tester's context window, burning tokens twice and bloating the conversation. All real data lives in Supabase (§5). |

**Do not deviate.** `--bare` looks attractive (kills hooks/LSP/plugins/
auto-memory) but it also disables Keychain reads → "Not logged in".

---

## 2. Multi-turn (`--resume`)

Multi-turn rounds drive more manage code paths (assistant-message echo,
`turn_seq` accumulation, cache management) than single calls. Prefer
them.

```bash
UUID=$(uuidgen | tr 'A-Z' 'a-z')
WORKDIR=$(mktemp -d)
cd "$WORKDIR"

# Turn 1 — opens the conversation
... --session-id "$UUID" ... "[PROBE 2026-05-28 r001 t01] First prompt."

# Turn 2..N — resumes the same conversation, same model, same WORKDIR
... --resume "$UUID" ... "[PROBE 2026-05-28 r001 t02] Second prompt."
... --resume "$UUID" ... "[PROBE 2026-05-28 r001 t03] Third prompt."
```

Constraints:

- **Stay in the same `WORKDIR`** across turns of one round — Claude Code
  resolves `--resume` against the working directory's conversation
  store. A fresh `mktemp` per turn will silently not find the
  conversation.
- **Keep `--model sonnet` on every turn.** Switching models mid-round
  resets the cache.
- Run turns **sequentially** within a round. Parallelize across rounds
  if needed, but never within a round.

---

## 3. Prefix convention (mandatory)

Every user message in a probe round starts with a structured prefix so
Supabase queries (§5) can pull the round out of unrelated traffic.

```
[PROBE YYYY-MM-DD rNNN tNN] <real prompt>
```

- `YYYY-MM-DD` — the date the campaign is run.
- `rNNN` — zero-padded round index within that day. One round = one
  multi-turn conversation = one hypothesis.
- `tNN` — zero-padded turn index within the round, starting at `t01`.

Example: `[PROBE 2026-05-28 r004 t02] Reply with exactly one emoji.`

Supabase sees the prefix verbatim inside `request_jsonb.messages[*]
.content[*].text`. **The prefix is the only reliable way to filter your
traffic** — `conversation_id` in `plugin_analytics` is a server-side
ULID, not the client UUID you passed as `--session-id`, so you cannot
join on it directly.

---

## 4. Designing a round

A round = one hypothesis = one multi-turn conversation. Name the
hypothesis explicitly in the round's result doc (§6) before writing
prompts. Hypotheses worth testing fall in these families:

- **Payload shapes**: short text, long text (force ~16k output),
  markdown-heavy, code blocks, structured JSON, large system prompt.
- **Encoding**: Korean, emoji, mixed-script, control characters, RTL.
- **Streaming boundaries**: prompts that force long SSE chunks; prompts
  that trigger `stop_sequence` vs `end_turn` vs `max_tokens`.
- **Error paths**: invalid model name, requests that trigger 4xx
  upstream, prompts that hit content policy.
- **Tool-use shape**: ask the model to emit a structured tool call
  (tools are disallowed, but the response still contains `tool_use`
  blocks worth recording).
- **Scrubbers**: bait strings like `sk-test`, `Bearer xxx`,
  `password=foo`, fake emails — confirm `audit_log` / `exchanges`
  scrubbed them.
- **Cache mechanics**: 2-turn round with identical system-prompt
  surface; expect `cache_read ≈ T1.cache_write` on T2.
- **Concurrency**: 3 parallel rounds (different UUIDs) firing within
  ~5 s. Confirm `exchanges.id` ordering is sane and no rows cross-
  contaminate.

Keep each round narrow — one hypothesis, 2–5 turns.

---

## 5. Post-run analysis (Supabase)

After each round, query both tables. Use Supabase MCP
(`mcp__supabase__execute_sql`).

**Plugin analytics** — post-processed, per-turn, prefix-filterable:

```sql
SELECT id, conversation_id, turn_seq, role,
       model_requested, model_served,
       input_tokens, output_tokens,
       cache_read_tokens, cache_write_tokens,
       stop_reason, created_at
FROM plugin_analytics
WHERE request_jsonb::text LIKE '%[PROBE 2026-05-28 r001 %'
ORDER BY created_at ASC, turn_seq ASC NULLS LAST;
```

Replace `2026-05-28 r001` with the round prefix.

**Exchanges** — raw proxy traffic, all models, all status codes.
`exchanges` does not store the request body, so filter by time window:

```sql
SELECT id, started_at,
       to_timestamp(started_at/1000.0) AT TIME ZONE 'UTC' AS started_utc,
       endpoint, model_requested, model_served, status_code,
       latency_ms, stop_reason, content_level, blocked_by
FROM exchanges
WHERE started_at > (extract(epoch from now()) - 1800) * 1000
ORDER BY started_at ASC;
```

Cross-check the row count against turns sent. Rows in `exchanges` but
absent from `plugin_analytics` for the same time window are signal —
that's exactly how anomaly #2 was found.

**Audit log** — scrubber / capability events:

```sql
SELECT id, ts, kind, plugin, hook, capability, outcome, detail_json
FROM audit_log
WHERE ts > (extract(epoch from now()) - 1800) * 1000
ORDER BY ts ASC;
```

What to look for, per round:

- Every turn sent appears exactly once in `exchanges` with
  `status_code = 200` (unless the hypothesis is an error path).
- Every turn appears in `plugin_analytics` with the right `turn_seq`
  and `conversation_id` stable across turns of one round.
- `cache_read_tokens ≈ previous_turn.cache_write_tokens` on turn ≥ 2
  (only true if the model is pinned).
- `model_served` is non-null on 200 rows.
- No row from another round appears within your window.

---

## 6. Writing the result doc

One file per round: `results/YYYY-MM-DD-rNNN-<topic-slug>.md`.

Suggested structure (≤ 1 page):

```markdown
# YYYY-MM-DD r001 · <topic>

**Hypothesis**: ...

**Prompts sent** (with prefix):
- t01: `[PROBE ...] ...`
- t02: `[PROBE ...] ...`

**Observed in supabase**:

| turn | model_served | in | out | cache_w | cache_r | stop | sink_row? |
|---|---|---|---|---|---|---|---|

**Findings**:
- ... (link to anomaly catalog if existing)
- ... (new — promote to worklog Suggestions if confirmed)

**Cost**: $X.XX
```

If a round confirms a *new* anomaly, append a numbered entry to the
Suggestions section of the origin worklog
(`docs/worklog/2026-05-28-headless-subsession-probe.md`), or start a
follow-up worklog if the round is itself a work-unit. Don't bury
findings only in `results/`.

---

## 7. Known anomalies (already on file)

These were found during the origin probe. **Do not re-file as new
findings** unless your round adds specifics (different model, different
endpoint, different conditions). Reference them by number.

1. `model_served` context-window suffix (`[1m]`) lost / 404'd. See
   origin worklog Suggestion #1.
2. `plugin_analytics` sink omits Haiku traffic. See Suggestion #2.
3. Some 200 rows have NULL `stop_reason` / `model_served`. See
   Suggestion #3.

---

## 8. Pitfalls (failure modes already observed)

- **"Not logged in · Please run /login"** in the sub-session result →
  you used `--bare`. Remove it. `--bare` disables Keychain reads.
- **401 with binary garbage in `result`** → `ANTHROPIC_API_KEY` leaked
  from parent env. Re-check the `env -u` clause.
- **Sub-session hangs 3 s then proceeds with an empty prompt** →
  missing `< /dev/null`.
- **`cache_read_tokens = 0` on a `--resume` turn** → model autoselect
  flipped (1M ↔ 200k). Confirm `--model sonnet` is on every turn.
- **`[claude-manage] preferred port 18080 in use; this instance is on
  NNNNN.`** in stderr → **normal, not an error**. The tester's own
  Claude Code already owns 18080; the sub-instance correctly falls
  back to an ephemeral port.
- **Result doc filed but no `plugin_analytics` row in window** →
  cross-check `exchanges` first. If raw traffic is present but
  `plugin_analytics` is empty for that turn, you've reproduced
  Suggestion #2 in another shape — add specifics.

---

## 9. Helper

`runner.sh` in this directory wraps §1 + §2 into one command. See its
header for usage. Prefer it over hand-typing the env + flag combo on
every call.
