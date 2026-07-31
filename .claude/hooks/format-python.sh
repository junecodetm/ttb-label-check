#!/usr/bin/env bash
# PostToolUse hook: run ruff on Python files after Claude edits them.
#
# Exits 0 on every path, including failure. A formatter that blocks the edit it was
# meant to tidy is worse than no formatter. The venv does not exist for the whole
# pre-code phase, so a silent no-op is the expected behaviour, not an error.
set -uo pipefail

repo_root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ruff="$repo_root/.venv/bin/ruff"

[ -x "$ruff" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

file_path="$(jq -r '.tool_input.file_path // empty' 2>/dev/null)"
[ -n "$file_path" ] || exit 0
[ -f "$file_path" ] || exit 0

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac

# Formatting only. `ruff check --fix` is deliberately NOT run here: it removes unused
# imports, which silently deletes an import added moments before its first use while a
# module is being written incrementally. Linting runs at the /build phase gates instead.
"$ruff" format --quiet -- "$file_path" >/dev/null 2>&1
exit 0
