#!/usr/bin/env bash
set -euo pipefail

HOST="${1:?usage: scripts/install.sh <ssh-host> [git-ref]}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE=/tmp/claude-decky-stage
TARGET=/home/deck/homebrew/plugins/claude-decky
SWAP=/home/deck/homebrew/.claude-decky

cd "$ROOT"
pnpm run build >/dev/null
test -x bin/whisper-cli || scripts/build-whisper.sh

ssh "$HOST" "rm -rf $STAGE && mkdir -p $STAGE"
rsync -a dist main.py py_modules bin plugin.json package.json LICENSE README.md "$HOST:$STAGE/"
ssh "$HOST" "set -e
sudo rm -rf $SWAP.new
sudo mkdir -p $SWAP.new
sudo cp -a $STAGE/. $SWAP.new/
sudo find $SWAP.new -name __pycache__ -prune -exec rm -rf {} +
sudo chown -R deck:deck $SWAP.new
sudo chown root:root $SWAP.new $SWAP.new/plugin.json
sudo chmod -R 755 $SWAP.new
sudo rm -rf $SWAP.old
if [ -d $TARGET ]; then sudo mv $TARGET $SWAP.old; fi
sudo mv $SWAP.new $TARGET
sudo rm -rf $SWAP.old $STAGE
sudo systemctl restart plugin_loader"
