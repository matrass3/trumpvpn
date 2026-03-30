#!/usr/bin/env bash
set -euo pipefail

CONFIG="${CONFIG:-/etc/hysteria/config.yaml}"
SERVICE="${SERVICE:-hysteria-server}"
NAME=""
PASSWORD=""
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

if [[ -z "$NAME" && -z "$PASSWORD" ]]; then
  echo "Usage: remove_hysteria2_user.sh --name <username> [--password <password>] [--no-restart]"
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

existing=""
if [[ -n "$NAME" ]]; then
  existing="$(NAME="$NAME" yq eval '(.auth.userpass // {})[strenv(NAME)] // ""' "$CONFIG" 2>/dev/null || true)"
  if [[ -z "$existing" ]]; then
    echo "OK: $NAME not found"
    exit 0
  fi
  if [[ -n "$PASSWORD" && "$existing" != "$PASSWORD" ]]; then
    echo "User exists but password mismatch for: $NAME"
    exit 1
  fi
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

if [[ -n "$NAME" ]]; then
  NAME="$NAME" yq eval '.auth.userpass = (.auth.userpass // {}) | del(.auth.userpass[strenv(NAME)])' "$CONFIG" > "$TMP"
else
  PASSWORD="$PASSWORD" yq eval '
    .auth.userpass = (.auth.userpass // {}) |
    .auth.userpass |= with_entries(select(.value != strenv(PASSWORD)))
  ' "$CONFIG" > "$TMP"
fi

mv "$TMP" "$CONFIG"
chown root:root "$CONFIG"
chmod 640 "$CONFIG"

if [[ "$RESTART_SERVICE" == "1" ]]; then
  systemctl restart "$SERVICE"
  echo "OK: user removed, service restarted"
else
  echo "OK: user removed, restart skipped"
fi
