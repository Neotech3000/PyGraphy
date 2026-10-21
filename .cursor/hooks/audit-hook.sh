#!/usr/bin/env bash
# Cursor worker audit hook — logs every agent event to a local append-only file.
# Usage: audit-hook.sh <hook_event_name>
# Reads hook JSON from stdin, appends one line to the audit log, and emits the
# minimal JSON response each hook type expects. Always exits 0 (fail-open) so a
# logging problem can never break an agent run.
set -u

EVENT="${1:-unknown}"
LOG_DIR="${PYGRAPHY_AUDIT_DIR:-$HOME/.local/share/cursor-agent}"
LOG_FILE="$LOG_DIR/audit.log"

payload="$(cat)"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$LOG_DIR" 2>/dev/null || exit 0
chmod 700 "$LOG_DIR" 2>/dev/null

# Extract the fields worth having at a glance; tolerate missing jq by falling
# back to the raw payload.
if command -v jq >/dev/null 2>&1; then
  line="$(jq -c --arg event "$EVENT" --arg ts "$now" \
    '{ts:$ts, event:$event, conversation:.conversation_id, tool:.tool_name,
      input:.tool_input, command:.command, cwd:.cwd, status:.status,
      error:.error_message, email:.user_email} | with_entries(select(.value != null))' \
    <<<"$payload" 2>/dev/null)"
  [ -z "$line" ] && line="{\"ts\":\"$now\",\"event\":\"$EVENT\",\"raw\":$(printf '%s' "$payload" | jq -Rs . 2>/dev/null || echo '""')}"
else
  line="{\"ts\":\"$now\",\"event\":\"$EVENT\",\"raw\":$(printf '%s' "$payload" | jq -Rs . 2>/dev/null || echo '""')}"
fi

printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null || true
chmod 600 "$LOG_FILE" 2>/dev/null

case "$EVENT" in
  preToolUse)      printf '{"continue":true,"permission":"allow"}\n' ;;
  beforeShellExecution) printf '{"continue":true,"permission":"allow"}\n' ;;
  *)               printf '{}\n' ;;
esac
exit 0
