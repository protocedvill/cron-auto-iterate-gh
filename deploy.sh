#!/usr/bin/env bash
# Deploys this tool's code to /opt/cron-auto-iterate-gh, read-only for the
# cron-iterate service user. Does NOT touch config.yaml, state.json, repo
# clones, or credentials under /var/lib/cron-iterate - those are runtime
# state owned by cron-iterate itself, not part of this deployment.
#
# See plan.md "Isolation & sandboxing" section for the full rationale.
set -euo pipefail

DEST=/opt/cron-auto-iterate-gh
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! id -u cron-iterate >/dev/null 2>&1; then
  echo "error: system user 'cron-iterate' does not exist yet." >&2
  echo "See plan.md 'Isolation & sandboxing' for the useradd command." >&2
  exit 1
fi

sudo mkdir -p "$DEST"
sudo cp "$SRC/iterate.py" "$DEST/iterate.py"
sudo rsync -a --delete "$SRC/lib/" "$DEST/lib/"
sudo rsync -a --delete "$SRC/prompts/" "$DEST/prompts/"
sudo chown -R root:cron-iterate "$DEST"
sudo chmod -R 750 "$DEST"

echo "deployed $SRC -> $DEST (root:cron-iterate, 750)"
