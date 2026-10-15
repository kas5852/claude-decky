#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(node -p 'require("./package.json").version')"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
OUT="$ROOT/out/claude-decky-v$VERSION.zip"

pnpm run build >/dev/null
if [ ! -x bin/whisper-cli ]; then scripts/build-whisper.sh; fi

PLUGIN="$STAGE/claude-decky"
mkdir -p "$PLUGIN/bin" "$PLUGIN/assets"
cp -R dist main.py py_modules plugin.json package.json LICENSE README.md "$PLUGIN/"
cp bin/whisper-cli "$PLUGIN/bin/"
cp licenses/whisper.cpp.txt "$PLUGIN/bin/whisper-cli.LICENSE"
cp assets/logo.png "$PLUGIN/assets/"
find "$PLUGIN" \( -name __pycache__ -o -name .DS_Store -o -name "*.map" \) -prune -exec rm -rf {} +
find "$PLUGIN" -type d -empty -delete
chmod -R u=rwX,go=rX "$PLUGIN"
chmod 755 "$PLUGIN/bin/whisper-cli"

mkdir -p "$ROOT/out"
rm -f "$OUT"
(cd "$STAGE" && zip -qrX "$OUT" claude-decky)
echo "$OUT"
