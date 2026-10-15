# Claude Decky

A Decky Loader plugin that puts Claude Code in the Steam Quick Access menu, with sign-in, push-to-talk and screen sharing.

- **Chat**: runs `claude -p` with stream-json as the `deck` user and resumes the session. Replies render as light markdown.
- **Sign in**: runs `claude auth login` in a pty. The panel shows a QR code for a one-time page on the handheld's LAN address, so the code can be pasted from a phone. You can also scan the direct link and type the code. Sign out removes stored tokens and keeps a backup.
- **Voice**: hold the in-game shortcut (default L3 + R3), talk, release. Tap it once for hands-free, which stops when you pause. In the panel, hold X or the Talk button. Recording uses `pw-record`. Speech to text runs on the device with a bundled `whisper.cpp` (`bin/whisper-cli`), and models download from Settings.
- **Screen**: the shortcut, or the Screen button, captures the game-mode screen with `gamescopectl` and sends it with the question.
- **Idle cost**: no timers or polling. The shortcut listener sleeps on evdev with a kernel event mask, so only the chord buttons wake it. Events go to the panel only while it is open.

Layout: `src/` frontend, `main.py` + `py_modules/claude_decky/` backend, `harness/` headless tests, `tools/` measurement and CDP helpers, `scripts/` build and install.

## Build

```
pnpm install
pnpm run build
scripts/build-whisper.sh
```

`build-whisper.sh` builds a static x86-64 `whisper-cli` in Docker.

## Install

```
scripts/install.sh <ssh-host>
```

This builds, copies to `~/homebrew/plugins/claude-decky` with the ownership Decky expects, and restarts `plugin_loader`. Pass a git ref to install another version, for example `scripts/install.sh <ssh-host> 65cd4d5` for v0.1.0.

## Test

```
rsync -a --exclude node_modules --exclude .git ./ <ssh-host>:/tmp/cdtools/plugin/
ssh <ssh-host> 'cd /tmp/cdtools/plugin && python3 harness/test_backend.py fake'
```

`live` mode uses the real CLI, microphone, screen and a virtual uinput pad.
