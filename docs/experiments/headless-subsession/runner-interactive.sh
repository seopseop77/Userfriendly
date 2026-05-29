#!/usr/bin/env bash
# runner-interactive.sh — launch an *interactive* Claude Code session
# routed through claude-manage's proxy, so client-side slash-command
# pre-processing (the `<command-name>` / `<local-command-*>` wrappers and
# the post-`/compact` resume marker) actually traverses the proxy.
#
# WHY this exists: `claude -p` headless mode does NOT parse slash commands
# — they pass through as plain user text (see results/2026-05-28-r013-thru
# -r022-r026-slash-not-parsed.md). The classifier branches that strip those
# wrappers are only reachable from an interactive session. This launcher is
# that session. See INTERACTIVE-SLASH.md for the full runbook.
#
# Usage:
#   ./runner-interactive.sh
#
# This is INTERACTIVE: it attaches to your terminal. Type the slash
# commands and prompts from INTERACTIVE-SLASH.md by hand, then /exit.
# Unlike runner.sh, stdout/stderr is NOT discarded (you need the REPL).
#
# It prints the proxy start time (epoch ms) and an empty isolated workdir
# before launching — record both; the Supabase queries in the runbook
# filter on the start time.

set -euo pipefail

WORKDIR=$(mktemp -d)
START_MS=$(( $(date +%s) * 1000 ))

echo "[runner-interactive] workdir : $WORKDIR"
echo "[runner-interactive] start_ms: $START_MS  (use in the Supabase time filter)"
echo "[runner-interactive] launching interactive Claude Code through the proxy..."
echo

cd "$WORKDIR"

# Same env-unset prelude and model pin as runner.sh (both load-bearing —
# see README.md §1). No `-p`, no `--disallowedTools`: this is interactive
# and we want slash commands to be pre-processed normally.
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BEARER_TOKEN \
  claude-manage --model sonnet
