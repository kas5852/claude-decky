# Claude Decky

A Decky Loader plugin that puts a Claude Code chat in the Steam Quick Access menu.

- Frontend: `src/index.tsx` (React, built with rollup into `dist/index.js`)
- Backend: `main.py` runs `claude -p --output-format stream-json` as the `deck` user, resumes the session by id, keeps the chat in `~/homebrew/settings/claude-decky/chat.json`
- Harness: `harness/` runs the backend headlessly against a stub `decky` module

## Build

```
pnpm install
pnpm run build
```

## Install

Copy `dist/`, `main.py`, `plugin.json`, `package.json` and `LICENSE` to `~/homebrew/plugins/claude-decky` on the device and restart `plugin_loader`.

Needs Claude Code installed at `~/.local/bin/claude`.
