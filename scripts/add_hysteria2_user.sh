#!/usr/bin/env bash
set -euo pipefail

CONFIG="${CONFIG:-/etc/hysteria/config.yaml}"
SERVICE="${SERVICE:-hysteria-server}"
NAME=""
PASSWORD=""
EXPIRY=""
RESTART_SERVICE=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="$2"
      shift 2
      ;;
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --expiry)
      EXPIRY="$2"
      shift 2
      ;;
    --no-restart)
      RESTART_SERVICE=0
      shift
      ;;
    --restart)
      RESTART_SERVICE=1
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$NAME" || -z "$PASSWORD" ]]; then
  echo "Usage: add_hysteria2_user.sh --name <username> --password <password> [--expiry <iso>] [--no-restart]"
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "Config not found: $CONFIG"
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "yq is required (https://github.com/mikefarah/yq)"
  exit 1
fi

# Backward compatibility with shared scripts interface.
if [[ -n "$EXPIRY" ]]; then
  :
fi

before_password="$(NAME="$NAME" yq eval '(.auth.userpass // {})[strenv(NAME)] // ""' "$CONFIG" 2>/dev/null || true)"
if [[ "$before_password" == "$PASSWORD" ]]; then
  echo "OK: $NAME already exists"
  exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

NAME="$NAME" PASSWORD="$PASSWORD" yq eval '
  .auth.type = "userpass" |
  .auth.userpass = (.auth.userpass // {}) |
  .auth.userpass[strenv(NAME)] = strenv(PASSWORD)
' "$CONFIG" > "$TMP"

mv "$TMP" "$CONFIG"
chown root:root "$CONFIG"
chmod 640 "$CONFIG"

if [[ "$RESTART_SERVICE" == "1" ]]; then
  systemctl restart "$SERVICE"
  echo "OK: $NAME added, service restarted"
else
  echo "OK: $NAME added, restart skipped"
fi
