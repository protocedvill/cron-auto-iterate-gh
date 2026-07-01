#!/usr/bin/env bash
# Generates a per-repo SSH deploy key for cron-auto-iterate-gh and wires up
# an SSH config Host alias for it.
#
# Why this exists: GitHub deploy keys are unique account-wide, not just
# per-repo - the same public key cannot be added as a deploy key to a
# second repository at all (GitHub rejects it with "key is already in
# use"). So each target repo needs its own keypair, and git needs an SSH
# config alias per repo to know which key to present for which remote
# (since they're all still hostname `github.com`).
#
# Usage: ./add-repo-key.sh <repo-name>
#   <repo-name> should match the `name:` field you use for this repo in
#   config.yaml.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <repo-name>" >&2
  exit 1
fi

NAME="$1"
SSH_DIR=/var/lib/cron-iterate/.ssh
KEY_FILE="$SSH_DIR/id_ed25519_${NAME}"
CONFIG_FILE="$SSH_DIR/config"
KNOWN_HOSTS="$SSH_DIR/known_hosts"
ALIAS="github.com-${NAME}"

if ! id -u cron-iterate >/dev/null 2>&1; then
  echo "error: system user 'cron-iterate' does not exist yet. See README.md step 1." >&2
  exit 1
fi

if sudo test -f "$KEY_FILE"; then
  echo "error: $KEY_FILE already exists - refusing to overwrite." >&2
  echo "Remove it first (and its SSH config block) if you want to regenerate." >&2
  exit 1
fi

if sudo test -f "$CONFIG_FILE" && sudo grep -qx "Host ${ALIAS}" "$CONFIG_FILE"; then
  echo "error: an SSH config entry for '${ALIAS}' already exists in $CONFIG_FILE." >&2
  exit 1
fi

sudo -u cron-iterate mkdir -p "$SSH_DIR"
sudo chmod 700 "$SSH_DIR"
sudo -u cron-iterate ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "cron-iterate-${NAME}" -q

sudo -u cron-iterate tee -a "$CONFIG_FILE" > /dev/null <<EOF

Host ${ALIAS}
  HostName github.com
  User git
  IdentityFile ${KEY_FILE}
  IdentitiesOnly yes
EOF
sudo chmod 600 "$CONFIG_FILE"

if ! sudo test -f "$KNOWN_HOSTS" || ! sudo grep -q "^github.com " "$KNOWN_HOSTS"; then
  sudo -u cron-iterate bash -c "ssh-keyscan github.com >> '$KNOWN_HOSTS'"
fi

echo
echo "=== keypair generated for '${NAME}' ==="
echo
echo "1. Add this public key as a WRITE-access deploy key on the '${NAME}' repo"
echo "   (GitHub: repo -> Settings -> Deploy keys -> Add deploy key):"
echo
sudo cat "${KEY_FILE}.pub"
echo
echo "2. In config.yaml, set this repo's remote to use the SSH alias instead"
echo "   of the plain github.com hostname, e.g.:"
echo "     remote: git@${ALIAS}:your-org/${NAME}.git"
echo
echo "3. Re-sync config.yaml to the live location if you haven't already:"
echo "     sudo cp config.yaml /var/lib/cron-iterate/config.yaml"
echo "     sudo chown cron-iterate:cron-iterate /var/lib/cron-iterate/config.yaml"
