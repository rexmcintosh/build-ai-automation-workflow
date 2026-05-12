#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 VPS for Claude-Code-on-VPS development.
# Run as root. Idempotent-ish: re-running is safe but won't undo manual changes.
#
# Usage: bash bootstrap-vps.sh <username>
#   <username>  the non-root user to create (e.g. "dev")
#
# Expects: your SSH public key is already in /root/.ssh/authorized_keys
#          (Hetzner does this for you when you add the key at create time).

set -euo pipefail

USER_NAME="${1:?usage: $0 <username>}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

echo "==> Updating apt and installing base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
  curl ca-certificates gnupg lsb-release \
  git build-essential \
  tmux mosh \
  ufw fail2ban unattended-upgrades \
  jq python3-venv pipx \
  htop ncdu

echo "==> Installing Node.js 20 LTS (for Claude Code)"
if ! command -v node >/dev/null || [[ "$(node -v)" != v20.* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Installing GitHub CLI"
if ! command -v gh >/dev/null; then
  install -dm 755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update -y
  apt-get install -y gh
fi

echo "==> Installing Caddy (reverse proxy + auto-TLS)"
if ! command -v caddy >/dev/null; then
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

echo "==> Creating user $USER_NAME"
if ! id "$USER_NAME" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$USER_NAME"
  usermod -aG sudo "$USER_NAME"
  echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$USER_NAME"
  chmod 440 "/etc/sudoers.d/90-$USER_NAME"
fi

echo "==> Copying SSH keys from root to $USER_NAME"
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  install -m 600 -o "$USER_NAME" -g "$USER_NAME" \
    /root/.ssh/authorized_keys "/home/$USER_NAME/.ssh/authorized_keys"
fi

echo "==> Hardening SSH (key-only, no root login)"
sshd_cfg=/etc/ssh/sshd_config.d/99-hardening.conf
cat > "$sshd_cfg" <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
EOF
systemctl reload ssh || systemctl reload sshd

echo "==> Configuring UFW firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 60000:61000/udp comment 'mosh'
ufw --force enable

echo "==> Enabling fail2ban and unattended-upgrades"
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Adding 4G swap if RAM < 16G and no swap exists"
mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
if (( mem_gb < 16 )) && ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> Setting timezone to UTC"
timedatectl set-timezone UTC

echo "==> Projects directory"
install -d -m 755 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/projects"

cat <<EOF

================================================================
Bootstrap complete.

Next:
  ssh $USER_NAME@$(hostname -I | awk '{print $1}')
  npm install -g @anthropic-ai/claude-code
  claude login

Root login is now disabled. Use $USER_NAME from here on.
================================================================
EOF
