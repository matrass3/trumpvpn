#!/usr/bin/env bash
set -euo pipefail

CONFIG="${CONFIG:-/usr/local/etc/xray/config.json}"
UUID=""
EMAIL=""
EXPIRY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uuid)
      UUID="$2"
      shift 2
      ;;
    --email)
      EMAIL="$2"
      shift 2
      ;;
    --expiry)
      EXPIRY="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$UUID" || -z "$EMAIL" ]]; then
  echo "Usage: add_vless_user.sh --uuid <uuid> --email <tag> [--expiry <iso>]"
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

vless_inbounds_count="$(jq '[.inbounds[]? | select((.protocol? // "") == "vless")] | length' "$CONFIG")"
if [[ "$vless_inbounds_count" == "0" ]]; then
  echo "No vless inbounds found in $CONFIG"
  exit 1
fi

before_count="$(jq --arg uuid "$UUID" '[.inbounds[]?.settings?.clients[]? | select((.id // "") == $uuid)] | length' "$CONFIG")"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
jq --arg uuid "$UUID" --arg email "$EMAIL" --arg expiry "$EXPIRY" '
  .inbounds |= (
    if type == "array" then
      map(
        if (.protocol? // "") == "vless" then
          (
            if (.settings? | type) != "object" then .settings = {} else . end
            | if (.settings.clients? | type) != "array" then .settings.clients = [] else . end
            | if (.settings.clients | map(.id // "") | index($uuid)) then
                .
              else
                .settings.clients += [
                  {
                    "id": $uuid,
                    "email": $email,
                    "flow": "xtls-rprx-vision",
                    "level": 0
                  }
                ]
              end
          )
        else
          .
        end
      )
    else .
    end
  )
' "$CONFIG" > "$TMP"

after_count="$(jq --arg uuid "$UUID" '[.inbounds[]?.settings?.clients[]? | select((.id // "") == $uuid)] | length' "$TMP")"
if [[ "$after_count" -le "$before_count" ]]; then
  echo "OK: $UUID already exists"
  exit 0
fi

mv "$TMP" "$CONFIG"
chown root:root "$CONFIG"
chmod 644 "$CONFIG"
systemctl restart xray
echo "OK: $UUID added"
