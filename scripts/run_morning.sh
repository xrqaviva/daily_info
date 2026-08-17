#!/bin/bash
set -u

PROJECT_ROOT="/Users/aviva/Projects/daily_info"
PYTHON_BIN="/usr/bin/python3"
ATTEMPT=1
MAX_ATTEMPTS=3

cd "$PROJECT_ROOT" || exit 1
export PYTHONUNBUFFERED=1
export YINGMI_KEY_FILE="${YINGMI_KEY_FILE:-/Users/aviva/Projects/stock/.yingmi_api_key}"
export PATH="/Users/aviva/.nvm/versions/node/v24.16.0/bin:/usr/bin:/bin:/usr/sbin:/sbin"

while [ "$ATTEMPT" -le "$MAX_ATTEMPTS" ]; do
  "$PYTHON_BIN" -m morning_brief.cli run --root "$PROJECT_ROOT"
  STATUS=$?
  if [ "$STATUS" -eq 0 ]; then
    exit 0
  fi
  if [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; then
    sleep 60
  fi
  ATTEMPT=$((ATTEMPT + 1))
done

exit "$STATUS"
