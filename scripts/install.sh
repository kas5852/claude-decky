#!/usr/bin/env bash
set -euo pipefail

HOST="${1:?usage: scripts/install.sh <ssh-host> [git-ref]}"
REF="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE=/tmp/claude-decky-stage
TARGET=/home/deck/homebrew/plugins/claude-decky
SWAP=/home/deck/homebrew/.claude-decky
SOURCE="$ROOT"

if [ -n "$REF" ]; then
  SOURCE="$(mktemp -d)/claude-decky"
  git -C "$ROOT" worktree add -q --detach "$SOURCE" "$REF"
  trap 'git -C "$ROOT" worktree remove --force "$SOURCE"' EXIT
  ln -s "$ROOT/node_modules" "$SOURCE/node_modules"
  if [ -d "$SOURCE/py_modules" ]; then cp -a "$ROOT/bin" "$SOURCE/bin"; fi
fi

cd "$SOURCE"
pnpm run build >/dev/null
if [ -d py_modules ] && [ ! -x bin/whisper-cli ]; then scripts/build-whisper.sh; fi

PAYLOAD=()
for item in dist main.py py_modules bin plugin.json package.json LICENSE README.md; do
  if [ -e "$item" ]; then PAYLOAD+=("$item"); fi
done

ssh "$HOST" "rm -rf $STAGE && mkdir -p $STAGE"
rsync -a "${PAYLOAD[@]}" "$HOST:$STAGE/"
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
