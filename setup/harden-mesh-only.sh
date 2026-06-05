#!/usr/bin/env bash
# Lock the VPS down to mesh-only inbound: reachable ONLY over the Tailscale tailnet.
# Idempotent — safe to re-run. Run as a user with sudo, ON the VPS.
#
# What it does (see docs/MESH-ONLY-LOCKDOWN.md for the full rationale):
#   1. Opens the mesh side in UFW (tailscale0 + udp/41641)   <- additive, can't lock out
#   2. Verifies the mesh path is live BEFORE closing anything
#   3. Retires Caddy if it's only serving the stock placeholder
#   4. Closes public inbound (22/80/443 + mosh range)        <- destructive, goes last
#
# Safety net regardless of what this does: the Hetzner Cloud Console (VNC) is
# out-of-band and can re-open a port even if everything is denied.
#
# Usage:  bash setup/harden-mesh-only.sh
#         bash setup/harden-mesh-only.sh --dry-run

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

run() {
  if [[ $DRY_RUN -eq 1 ]]; then echo "DRY-RUN> $*"; else echo "+ $*"; "$@"; fi
}

echo "==> Pre-flight: confirm Tailscale is up with a reachable peer"
if ! command -v tailscale >/dev/null; then
  echo "FATAL: tailscale not installed. Do TAILSCALE.md Step 3 first." >&2; exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "FATAL: tailscaled not running / not logged in. 'sudo tailscale up' first." >&2; exit 1
fi
# Require at least one ONLINE peer so we don't fence ourselves off a dead tailnet.
peers=$(tailscale status 2>/dev/null | awk 'NR>1 && $1 ~ /^100\./ {print $2}' | grep -v '^vps$' || true)
if [[ -z "$peers" ]]; then
  echo "FATAL: no tailnet peers visible. Bring another device online before locking down." >&2
  exit 1
fi
echo "    peers visible: $(echo "$peers" | tr '\n' ' ')"

if tailscale debug prefs 2>/dev/null | grep -q '"RunSSH": true'; then
  echo "    Tailscale SSH: ENABLED (keyless mesh SSH available)"
else
  echo "    WARNING: Tailscale SSH not enabled. You'll need an SSH key authorized for"
  echo "             the dev user to reach the box over the tailnet after lockdown."
  echo "             Re-run 'sudo tailscale up --ssh' or ensure your key works, then retry."
fi

echo
echo "==> Step 1/4: open the mesh side (additive — cannot lock you out)"
run sudo ufw allow in on tailscale0 comment 'mesh: all inbound over tailnet'
run sudo ufw allow 41641/udp comment 'tailscale direct path (NAT traversal)'

echo
echo "==> Step 2/4: verify the mesh path before closing anything"
if [[ $DRY_RUN -eq 0 ]]; then
  if timeout 4 bash -c 'cat < /dev/null > /dev/tcp/100.64.43.80/22' 2>/dev/null; then
    echo "    OK: tailnet SSH endpoint (100.64.43.80:22) accepts connections"
  else
    echo "    NOTE: could not self-connect to 100.64.43.80:22 (tailnet IP may differ on a"
    echo "          rebuild). Verify 'ssh dev@vps' from a peer before trusting the lockdown."
  fi
fi

echo
echo "==> Step 3/4: retire Caddy if it only serves the stock placeholder"
if systemctl is-active --quiet caddy 2>/dev/null; then
  if grep -qs 'root \* /usr/share/caddy' /etc/caddy/Caddyfile; then
    echo "    Caddy is serving the stock default site — disabling it."
    run sudo systemctl disable --now caddy
  else
    echo "    Caddy has a CUSTOM config — leaving it running. If it should be private,"
    echo "    move it behind 'tailscale serve' (see docs/MESH-ONLY-LOCKDOWN.md) and then"
    echo "    remove its public 80/443 rules yourself."
  fi
else
  echo "    Caddy not active — nothing to do."
fi

echo
echo "==> Step 4/4: close the public doors (idempotent — ignores already-absent rules)"
for rule in "22/tcp" "80/tcp" "443/tcp" "60000:61000/udp"; do
  run sudo ufw --force delete allow "$rule" || true
done

echo
echo "==> Result"
run sudo ufw status verbose

cat <<'EOF'

================================================================
Mesh-only lockdown applied.

Confirm from one of your OTHER devices (the authoritative check):
    ssh dev@vps

If anything is wrong, the Hetzner Cloud Console (VNC) can re-open a port:
    sudo ufw allow 22/tcp

Full notes: docs/MESH-ONLY-LOCKDOWN.md
================================================================
EOF
