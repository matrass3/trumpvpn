#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-443}"
SNI="${SNI:-www.cloudflare.com}"
DEST="${DEST:-www.cloudflare.com:443}"
XRAY_CONFIG="/usr/local/etc/xray/config.json"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

apt-get update
apt-get install -y curl unzip jq openssl

bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

XRAY_BIN="$(command -v xray || true)"
if [[ -z "$XRAY_BIN" && -x "/usr/local/bin/xray" ]]; then
  XRAY_BIN="/usr/local/bin/xray"
fi
if [[ -z "$XRAY_BIN" ]]; then
  echo "xray binary not found after install"
  exit 1
fi

KEYS="$("$XRAY_BIN" x25519 2>&1)"
PRIVATE_KEY="$(printf '%s\n' "$KEYS" | sed -nE 's/.*[Pp]rivate key:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n 1)"
if [[ -z "$PRIVATE_KEY" ]]; then
  PRIVATE_KEY="$(printf '%s\n' "$KEYS" | sed -nE 's/.*PrivateKey:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n 1)"
fi

# Newer Xray may output "Password" instead of "PublicKey/Public key" for Reality client key.
PUBLIC_KEY="$(printf '%s\n' "$KEYS" | sed -nE 's/.*[Pp]ublic key:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n 1)"
if [[ -z "$PUBLIC_KEY" ]]; then
  PUBLIC_KEY="$(printf '%s\n' "$KEYS" | sed -nE 's/.*PublicKey:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n 1)"
fi
if [[ -z "$PUBLIC_KEY" ]]; then
  PUBLIC_KEY="$(printf '%s\n' "$KEYS" | sed -nE 's/.*Password:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n 1)"
fi
if [[ -z "$PRIVATE_KEY" || -z "$PUBLIC_KEY" ]]; then
  echo "Failed to parse x25519 keys from xray output (PrivateKey + PublicKey/Password):"
  echo "$KEYS"
  exit 1
fi
SHORT_ID="$(openssl rand -hex 8)"

mkdir -p /usr/local/etc/xray
cat > "$XRAY_CONFIG" <<EOF
{
  "log": {
    "loglevel": "warning"
  },
  "inbounds": [
    {
      "listen": "0.0.0.0",
      "port": ${PORT},
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "${DEST}",
          "xver": 0,
          "serverNames": ["${SNI}"],
          "privateKey": "${PRIVATE_KEY}",
          "shortIds": ["${SHORT_ID}"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "direct"
    }
  ]
}
EOF
chown root:root "$XRAY_CONFIG"
chmod 644 "$XRAY_CONFIG"

mkdir -p /opt/vpn
if [[ -f ./add_vless_user.sh ]]; then
  cp ./add_vless_user.sh /opt/vpn/add_vless_user.sh
  chmod +x /opt/vpn/add_vless_user.sh
fi
if [[ -f ./remove_vless_user.sh ]]; then
  cp ./remove_vless_user.sh /opt/vpn/remove_vless_user.sh
  chmod +x /opt/vpn/remove_vless_user.sh
fi

if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" || true
fi

systemctl daemon-reload
systemctl enable xray
systemctl restart xray
systemctl --no-pager --full status xray | head -n 20

echo ""
echo "=== SAVE THESE VALUES ==="
echo "PUBLIC_KEY=${PUBLIC_KEY}"
echo "SHORT_ID=${SHORT_ID}"
echo "SNI=${SNI}"
echo "PORT=${PORT}"
