#!/usr/bin/env bash
# One-time setup of the S2iD export VM (Ubuntu 22.04/24.04, x86_64 or ARM, in a Brazilian region). Run as the
# default user after adding the VM's deploy key to GitHub (docs/s2id-vm.md, step 3):
#   bash setup.sh
set -euo pipefail
REPO_SSH="git@github.com:valkiriaandrade/rs-corridor-flood-watch.git"
REPO_DIR="$HOME/rs-corridor-flood-watch"

sudo apt-get update -q
sudo apt-get install -yq git python3-venv cron

# 1 GB VMs (free micro shapes) need swap for Chromium
if [ "$(free -m | awk '/^Mem:/{print $2}')" -lt 3000 ] && ! swapon --show | grep -q .; then
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null
[ -d "$REPO_DIR/.git" ] || git clone -q "$REPO_SSH" "$REPO_DIR"
cd "$REPO_DIR"
git config user.name 's2id-export-vm'
git config user.email 's2id-export-vm@users.noreply.github.com'

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "pandas==3.1.0" "playwright==1.64.1"   # same pins as requirements*.txt
sudo .venv/bin/python -m playwright install-deps chromium
.venv/bin/python -m playwright install chromium

# 06:00 and 18:00 UTC; the forecast workflow is scheduled at 20:00 UTC and accepts exports up to 36 h old
line="0 6,18 * * * REPO_DIR=$REPO_DIR bash $REPO_DIR/scripts/s2id_vm/export.sh >> $HOME/s2id_export.log 2>&1"
( crontab -l 2>/dev/null | grep -v 's2id_vm/export.sh' || true; echo "$line" ) | crontab -
echo "setup done; first export:"
REPO_DIR="$REPO_DIR" bash "$REPO_DIR/scripts/s2id_vm/export.sh"
