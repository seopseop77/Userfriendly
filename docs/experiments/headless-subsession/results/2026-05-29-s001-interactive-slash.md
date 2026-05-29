# 2026-05-29 s001 · Interactive slash-command probe

**Vector**: live interactive `claude-manage --model sonnet` (no `-p`),
operator typing the slashes at the keyboard, routed through the proxy.
First run to reach the slash-classifier branches that `claude -p`
headless mode cannot (see `2026-05-28-r013-thru-r022-r026-slash-not-parsed.md`).

**Window**: 2026-05-29 15:01:51 → 15:08:58 UTC. Tag `[PROBE 2026-05-29 s001]`.
Operator ran the §3 plan **plus** extra slashes (`/model`, `/usage`,
`/agents`, `/memory`, `/config`, `/init`).

## Conversation reconstruction

Two real conversation_ids plus the orphan bucket:

- `01KST434TQDCG554RSFWZFGPE7` — main conversation, turn_seq 1–15 gap-free.
- `01KST433XB0E6X7WJP5AKJNY4G` — title-generation sidecar (the `<session>` shape).
- `01KSJC5354RT1XSGBFPZBQT4BB` — **orphan/empty-hash bucket** (Suggestion #4);
  the post-`/compact` turn was absorbed here.

| seq | typed (paraphrase) | role | slash_commands | conv | stop |
|---|---|---|---|---|---|
| 1 | `[PROBE … s001] … anchor` (model pinned first) | user_input | `["model","model"]` | 434 | end_turn |
| 2 | "what kind of output did /help show?" | user_input | `["help"]` | 434 | end_turn |
| 3 | "Reply with just: ok" | user_input | `["usage"]` | 434 | end_turn |
| 4 | short msg | user_input | `["usage"]` | 434 | end_turn |
| 1 | **"Reply with just: resumed"** (post-`/compact`) | user_input | `["compact"]` | **JC53** | end_turn |
| 5 | `[PROBE … s001] … anchor` (identical re-type after `/clear`) | user_input | `["clear"]` | 434 | end_turn |
| 6 | short msg | user_input | `["agents","memory"]` | 434 | end_turn |
| 7 | short msg | user_input | `["config"]` | 434 | end_turn |
| 8 | `/init` driver | user_input | `["init"]` | 434 | tool_use |
| 9–13 | `/init` agent tool loop | tool_result | – | 434 | tool_use→end_turn |
| 14–15 | follow-up + tool loop | user_input/tool_result | – | 434 | … |

Plus title-gen `<session>` sidecars (15:01:54, 15:04:27) and several
`SUGGESTION MODE` auto-suggest sidecars (`request_jsonb` stored as a bare
string). All sidecars classified `role=sidecar` correctly.

`exchanges` ↔ `plugin_analytics` = **22 ↔ 22, 1:1** in the window — no
missing-sink rows (no repeat of Suggestion #2). One out-of-window stray:
`claude-opus-4-8[1m]` **404** at 14:57:23 (pre-session, the analysing
session — not part of s001).

## Hypotheses — results

| target | result |
|---|---|
| `<command-name>` → `slash_commands` extraction (ADR-0038) | ✅ **confirmed** — populated on every slash turn: model×2, help, usage×2, compact, clear, agents+memory, config, init |
| `<local-command-*>` / `<command-message>` wrapper-strip | ✅ **confirmed** — `has_cmd_name` / `has_local_cmd` false on all 22 rows; stored bodies are clean user text only |
| post-`/compact` resume-marker → **same** conversation_id | ❌ **FALSIFIED** — see finding below; absorbed into the orphan bucket, not the live conversation |
| single-element `<session>` branch (F-4, "suspected unreachable") | ✅ **REACHABLE** (contradicts the runbook) — fired twice as title-gen sidecars: `[{"text":"<session>\n[PROBE …]\n</session>"}]`, both `role=sidecar` |
| B-rule on `/clear` + identical re-type (steps 8–9) | ✅ **same conversation_id** — t5 merged back into 434 (turn_seq 5); `/clear` did not open a new conv |
| turn_seq gap-free | ✅ within each conv (434: 1–15 contiguous; JC53: 1) |

## Finding (NEW — reopens Suggestion #4)

**The first post-`/compact` turn is orphaned into the empty-hash bucket
`01KSJC5354RT1XSGBFPZBQT4BB`, via the ordinary interactive `/compact`
path — not a contrived bait string.**

- **Observed**: turn "Reply with just: resumed" (carrying
  `slash_commands=["compact"]`) → `conversation_id=01KSJC53…`,
  `role=user_input`, `turn_seq=1`. It is the **first `user_input` row
  ever** to land in that bucket (previously only WebSearch/WebFetch/
  title sidecars from 2026-05-26 → 05-28).
- **Root cause (code-confirmed)**: after `/compact`, `messages[0]` is the
  resume-marker block `"This session is being continued…"`, which is a
  registered `_SYNTHETIC_WRAPPER_PREFIXES` entry (`classifier.py:98`).
  `_canonical_user_text` (`classifier.py:296`) skips wrapper-only blocks
  and returns `""`; `_hash_first_message` then computes
  `first_msg_hash = SHA256("")` — the **same fixed hash for every
  compacted conversation**. The (B) chain-lookup absorbs them all into
  the one empty-hash bucket. The row stays `user_input` (its *last*
  message is real text) but its **conversation_id is wrong**.
- **Why t5 survived**: the post-`/clear` re-anchor used byte-identical
  text to turn 1, so its canonical text was non-empty and the B-rule
  matched turn 1's hash → 434. The post-`/compact` "resumed" text was
  unique → empty canonical (marker-only `messages[0]`) → orphan bucket.
  So a *genuinely new* message after `/compact` always orphans; only the
  runbook's artificial identical-text trick avoided it for `/clear`.
- **Relation to Suggestion #4**: identical mechanism (empty
  `_canonical_user_text` → shared `first_msg_hash` → B-rule absorption
  into `01KSJC53…`). #4 was triaged 2026-05-29 as "no fix — real-world
  likelihood too low" on the grounds that the colliding openers were
  rare/contrived. **This run shows the same collision is triggered by a
  bare `/compact`, a routine interactive action** → the likelihood
  premise behind that triage no longer holds. Recommend reopening.

## Suggested fix directions (for #4 reopen)

- Make `_hash_first_message` (or the B-rule) refuse to chain on an
  **empty** canonical text — treat empty-canonical openers as
  "unknown / start a fresh conversation_id" rather than collapsing them
  all onto `SHA256("")`.
- Or: when `messages[0]` is resume-marker-only, derive continuity from
  the *resumed* conversation instead of the opener hash (the marker
  prose / first post-marker turn identifies the prior session).

## Cost

Negligible — 22 short sonnet turns + sidecars; no large outputs except
the `/init` tool loop.
