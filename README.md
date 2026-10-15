<p align="center"><img src="assets/logo.png" width="128" alt=""></p>

# Claude Decky

Claude Code in the Steam Quick Access menu. Ask why a game stutters, how to get more FPS, or to fix a broken setting, without leaving game mode.

## Install

1. Install [Decky Loader](https://decky.xyz).
2. Download `claude-decky-*.zip` from [Releases](../../releases).
3. Decky → Settings → General → turn on **Developer mode**.
4. Decky → Settings → Developer → **Install plugin from ZIP**.

## Use

- Open the menu (**…**) → Claude. It sets up Claude Code and signs you in with a QR code.
- **Talk:** get a voice model in Settings once. Then hold **L3 + R3** in game, speak, let go. It sends a screenshot too.
- **Type:** in the panel. Hold **X** to talk there.
- Settings: model, shortcut, voice model, full access.

> Full access is on: Claude can run any command on your device without asking. Turn it off in Settings if you don't want that.

## Build

```
pnpm install && pnpm build
scripts/build-whisper.sh
scripts/release.sh
```
