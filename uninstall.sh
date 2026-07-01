#!/usr/bin/env bash
# Uninstalls cron-auto-iterate-gh, reversing the steps in README.md.
#
# By default this only removes the parts that are pure "installation":
# the systemd timer/service and the deployed code under /opt. It leaves
# /var/lib/cron-iterate (repo clones, TODO.md history, state.json, the SSH
# deploy key, and the copied Claude credentials) and the cron-iterate
# system user in place, since those hold state/credentials you may still
# want to inspect or reuse.
#
# Flags:
#   --purge-data   also delete /var/lib/cron-iterate
#   --remove-user  also delete the cron-iterate system user (and, via
#                  `userdel -r`, its home dir /var/lib/cron-iterate - implies
#                  --purge-data, one prompt covers both)
#   -y, --yes      don't prompt for confirmation before destructive steps
set -euo pipefail

PURGE_DATA=false
REMOVE_USER=false
ASSUME_YES=false

for arg in "$@"; do
  case "$arg" in
    --purge-data) PURGE_DATA=true ;;
    --remove-user) REMOVE_USER=true; PURGE_DATA=true ;;
    -y|--yes) ASSUME_YES=true ;;
    -h|--help)
      sed -n '2,/^set -euo pipefail/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

confirm() {
  local prompt="$1"
  $ASSUME_YES && return 0
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

echo "== Stopping and disabling cron-iterate.timer =="
sudo systemctl disable --now cron-iterate.timer 2>/dev/null || true
sudo systemctl stop cron-iterate.service 2>/dev/null || true

echo "== Removing systemd unit files =="
sudo rm -f /etc/systemd/system/cron-iterate.service /etc/systemd/system/cron-iterate.timer
sudo systemctl daemon-reload

echo "== Removing deployed code (/opt/cron-auto-iterate-gh) =="
sudo rm -rf /opt/cron-auto-iterate-gh

CONFIG_FILE=/var/lib/cron-iterate/config.yaml
if [[ -f "$CONFIG_FILE" ]]; then
  echo
  echo "Reminder: this automation's SSH public key was added as a GitHub"
  echo "deploy key on the repos below. This script does NOT revoke those -"
  echo "remove them manually (repo -> Settings -> Deploy keys) if desired:"
  grep -E '^\s*remote:' "$CONFIG_FILE" | sed 's/^\s*remote:\s*/  - /' || true
fi

if $REMOVE_USER; then
  echo
  if confirm "Delete the cron-iterate user AND /var/lib/cron-iterate (repo clones, state, SSH key, Claude credentials)?"; then
    sudo userdel -r cron-iterate 2>/dev/null || true
    sudo rm -rf /var/lib/cron-iterate  # in case userdel left anything behind
    echo "removed cron-iterate user and its home directory"
  else
    echo "skipped removing the cron-iterate user and its data"
  fi
elif $PURGE_DATA; then
  echo
  if confirm "Delete /var/lib/cron-iterate (repo clones, state, SSH key, Claude credentials)?"; then
    sudo rm -rf /var/lib/cron-iterate
    echo "removed /var/lib/cron-iterate"
  else
    echo "skipped removing /var/lib/cron-iterate"
  fi
else
  echo
  echo "Left in place: /var/lib/cron-iterate (data) and the cron-iterate user."
  echo "Re-run with --purge-data and/or --remove-user to remove them too."
fi

echo
echo "Uninstall complete."
