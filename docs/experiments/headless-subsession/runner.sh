#!/usr/bin/env bash
# runner.sh — one isolated headless sub-session call through claude-manage.
#
# Discards stdout/stderr from the sub-session (probe results live in
# supabase; see ../README.md §5). Every prompt must follow the prefix
# convention in §3 of the README.
#
# Usage:
#   ./runner.sh new    <uuid> <prefix> <prompt> [workdir]
#   ./runner.sh resume <uuid> <prefix> <prompt>  <workdir>
#
# For multi-turn rounds: capture the workdir printed on stdout by the
# `new` call and pass it verbatim to every subsequent `resume` call —
# Claude Code resolves --resume against the working directory's
# conversation store, so resuming from a fresh mktemp will silently
# not find the conversation.
#
# Example (two-turn round):
#   uuid=$(uuidgen | tr 'A-Z' 'a-z')
#   workdir=$(./runner.sh new    "$uuid" "[PROBE 2026-05-28 r001 t01]" "Q1") || exit
#   ./runner.sh resume "$uuid" "[PROBE 2026-05-28 r001 t02]" "Q2" "$workdir"
#
# Exit code is the sub-session's claude exit code.

set -euo pipefail

mode=${1:?usage: runner.sh new|resume <uuid> <prefix> <prompt> [workdir]}
uuid=${2:?missing uuid}
prefix=${3:?missing prefix}
prompt=${4:?missing prompt}
workdir=${5:-}

case "$mode" in
  new)
    session_flag=(--session-id "$uuid")
    workdir=${workdir:-$(mktemp -d)}
    ;;
  resume)
    session_flag=(--resume "$uuid")
    : "${workdir:?resume requires the workdir from the original 'new' call}"
    ;;
  *)
    echo "mode must be 'new' or 'resume'" >&2
    exit 2
    ;;
esac

cd "$workdir"

env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_BEARER_TOKEN \
  claude-manage -p --max-turns 1 --disallowedTools '*' --permission-mode plan \
  --model sonnet --output-format json \
  "${session_flag[@]}" \
  "$prefix $prompt" \
  < /dev/null > /dev/null 2>&1

echo "$workdir"
