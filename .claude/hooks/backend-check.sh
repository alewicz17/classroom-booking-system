#!/usr/bin/env bash
# Runs after every file edit: formatting, lint and unit tests only.
# Docker-based layers are too slow for every edit; CI runs them.
command -v uv > /dev/null || exit 0
cd "$CLAUDE_PROJECT_DIR/backend" || exit 0

output=$(
  uv run ruff format . &&
  uv run ruff check . &&
  uv run pytest -m unit -q -p no:cacheprovider
) 2>&1
status=$?

# pytest exits with 5 when no unit tests exist yet; that is not a failure.
if [ $status -ne 0 ] && [ $status -ne 5 ]; then
  echo "$output" >&2
  exit 2
fi
