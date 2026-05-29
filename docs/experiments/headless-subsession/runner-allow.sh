#!/usr/bin/env bash
# runner-allow.sh — tool-allow variant of runner.sh for the 2026-05-28
# tool/slash matrix campaign.
#
# Differences from runner.sh (the load-bearing baseline in README.md §1):
#   - Workdir defaults to ~/Desktop/MyProjects/Userfriendly_test (fixture
#     repo with calculator.py / hello.py / today.py, no .claude/, no
#     CLAUDE.md). Override with the [workdir] arg if needed.
#   - --disallowedTools '*' removed → all tools allowed.
#   - --permission-mode plan → bypassPermissions (headless can't prompt).
#   - --max-turns 1 → --max-turns 10 (sub-session needs room to run
#     tool sequences inside one user message).
#
# Other load-bearing pieces unchanged: env -u ANTHROPIC_*, < /dev/null,
# > /dev/null 2>&1, --model sonnet, --output-format json, --session-id /
# --resume, fixed-workdir-across-turns rule.
#
# Usage:
#   ./runner-allow.sh new    <uuid> <prefix> <prompt> [workdir]
#   ./runner-allow.sh resume <uuid> <prefix> <prompt>  <workdir>
#
# Exit code is the sub-session's claude exit code. The workdir is
# echoed on stdout so multi-turn rounds can pin it.

set -euo pipefail

DEFAULT_WORKDIR="${HOME}/Desktop/MyProjects/Userfriendly_test"

mode=${1:?usage: runner-allow.sh new|resume <uuid> <prefix> <prompt> [workdir]}
uuid=${2:?missing uuid}
prefix=${3:?missing prefix}
prompt=${4:?missing prompt}
workdir=${5:-}

case "$mode" in
  new)
    session_flag=(--session-id "$uuid")
    workdir=${workdir:-$DEFAULT_WORKDIR}
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
  claude-manage -p --max-turns 10 --permission-mode bypassPermissions \
  --model sonnet --output-format json \
  "${session_flag[@]}" \
  "$prefix $prompt" \
  < /dev/null > /dev/null 2>&1

echo "$workdir"
