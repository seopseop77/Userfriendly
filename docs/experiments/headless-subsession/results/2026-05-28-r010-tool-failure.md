# 2026-05-28 r010 · Tool failure / is_error semantics

**UUID**: `f5d15e6a-…` · 2 turns, 4 rows, turn_seq 1→4 gap-free.

## Observed

| seq | tool       | content (tool_result.content)                              | is_error |
|---|---|---|---|
| 2 | Bash       | `ls: …: No such file or directory\nExit code: 1`           | **false** |
| 4 | Read       | `File does not exist. Note: your current working directory…` | **true**  |

## Findings

1. **`is_error` is set by the tool wrapper, not by the underlying
   command's exit code.** Bash with a failing command (`ls /no/such`,
   exit 1) returns `is_error: false` because the Bash tool *itself*
   executed successfully and is faithfully reporting the failure.
   Read on a missing file returns `is_error: true` because the Read
   tool *cannot* produce a file body — there is no content to return.
   Two different "failure" shapes by tool. For analytics queries that
   want to find "all failed commands": Bash failures require content
   inspection; Read/Edit/Write failures can be filtered with
   `is_error = true`.
2. **`role = 'tool_result'` on both rows.** ADR-0038's classifier
   doesn't care about `is_error`; it routes both to `tool_result`. As
   intended.
3. **`turn_seq` increments normally on `is_error: true` rows.** The
   gap-free invariant holds across failed and successful tool_result
   rows alike.
4. **Read's failure message includes a workdir hint** ("your current
   working directory is /Users/minseop/Desktop/MyProjects/Userfriendly_test").
   That's a Claude Code convention, not an Anthropic API thing —
   probably worth not relying on for downstream parsers (it has
   drifted before).
