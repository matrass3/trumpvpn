#!/usr/bin/env bash
set -euo pipefail

CONFIG="${CONFIG:-/usr/local/etc/xray/config.json}"
UUID=""
RESTART_XRAY=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uuid)
      UUID="$2"
      shift 2
      ;;
    --no-restart)
      RESTART_XRAY=0
      shift
      ;;
    --restart)
      RESTART_XRAY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$UUID" ]]; then
  echo "Usage: remove_vless_user.sh --uuid <uuid>"
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required"
  exit 1
fi

before_count="$(jq --arg uuid "$UUID" '[.inbounds[]?.settings?.clients[]? | select((.id // "") == $uuid)] | length' "$CONFIG")"
if [[ "$before_count" == "0" ]]; then
  echo "OK: $UUID not found"
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
jq --arg uuid "$UUID" '
  .inbounds |= (
    if type == "array" then
      map(
        if (.settings? | type) == "object" and (.settings.clients? | type) == "array"
        then .settings.clients |= map(select((.id // "") != $uuid))
        else .
        end
      )
    else .
    end
  )
' "$CONFIG" > "$TMP"

after_count="$(jq --arg uuid "$UUID" '[.inbounds[]?.settings?.clients[]? | select((.id // "") == $uuid)] | length' "$TMP")"
if [[ "$after_count" != "0" ]]; then
  echo "Failed to remove uuid from config"
  exit 1
fi

mv "$TMP" "$CONFIG"
chown root:root "$CONFIG"
chmod 644 "$CONFIG"
if [[ "$RESTART_XRAY" == "1" ]]; then
  systemctl restart xray
  echo "OK: $UUID removed ($before_count client entries), xray restarted"
else
  echo "OK: $UUID removed ($before_count client entries), restart skipped"
fi
