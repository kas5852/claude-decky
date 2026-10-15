import asyncio
import fcntl
import json
import os
import re
import signal
import struct
import termios
import time

import decky

from .env import CLAUDE, HOME, child_env, find_program, run
from .phone import PhonePage

CLAUDE_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CREDENTIALS = os.path.join(HOME, ".claude", ".credentials.json")
TOKEN_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\r")
LOGIN_URL = re.compile(r"https://\S*oauth/authorize\?\S+")
LOGIN_TIMEOUT = 15 * 60
INSTALL_SCRIPT = "https://claude.ai/install.sh"


def strip_terminal(text):
    return ESCAPES.sub("", text)


def read_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def stored_token_keys():
    env = (read_json(CLAUDE_SETTINGS) or {}).get("env") or {}
    return [key for key in TOKEN_KEYS if env.get(key)]


class Auth:
    def __init__(self, events):
        self.events = events
        self.phase = "idle"
        self.url = ""
        self.error = ""
        self.status = None
        self.checked_at = 0.0
        self.process = None
        self.master = None
        self.output = ""
        self.timeout = None
        self.phone = PhonePage(self.submit_code)
        self.phone.on_ready = self.changed
        self.install_log = ""

    def installed(self):
        return os.access(CLAUDE, os.X_OK)

    def quick_status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        if self.status is not None:
            return self.status
        keys = stored_token_keys()
        if keys:
            return {"installed": True, "loggedIn": True, "method": keys[0], "guess": True}
        if os.path.exists(CREDENTIALS):
            return {"installed": True, "loggedIn": True, "method": "claude.ai", "guess": True}
        return {"installed": True, "loggedIn": False, "method": "none", "guess": True}

    async def refresh(self):
        if not self.installed():
            self.status = {"installed": False, "loggedIn": False, "method": "none"}
            return self.state()
        code, out, _ = await run([CLAUDE, "auth", "status", "--json"], timeout=20)
        try:
            data = json.loads(out.decode())
        except ValueError:
            data = {"loggedIn": False, "authMethod": "unknown"}
        status = {
            "installed": True,
            "loggedIn": bool(data.get("loggedIn")),
            "method": data.get("authMethod") or "none",
        }
        for key in ("email", "orgName", "subscriptionType"):
            if data.get(key):
                status[key] = data[key]
        self.status = status
        self.checked_at = time.time()
        return self.state()

    def forget(self):
        self.status = None

    def state(self):
        return {
            "status": self.quick_status(),
            "phase": self.phase,
            "url": self.url,
            "phoneUrl": self.phone.url if self.phase == "waiting" else "",
            "error": self.error,
            "installLog": self.install_log[-600:],
        }

    def changed(self):
        self.events.emit("auth_state", self.state())

    async def login(self, console=False):
        if not self.installed():
            return self.fail("Install Claude Code first")
        await self.cancel()
        self.phase = "starting"
        self.error = ""
        self.url = ""
        self.output = ""
        self.changed()
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 4000, 0, 0))
        args = [CLAUDE, "auth", "login", "--console" if console else "--claudeai"]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=child_env({"TERM": "xterm-256color", "BROWSER": "/bin/false", "COLUMNS": "4000"}),
                start_new_session=True,
            )
        finally:
            os.close(slave)
        self.master = master
        os.set_blocking(master, False)
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self.on_output)
        loop.create_task(self.watch(self.process))
        self.timeout = loop.call_later(LOGIN_TIMEOUT, self.expire)
        return self.state()

    def on_output(self):
        try:
            chunk = os.read(self.master, 65536)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.close_master()
            return
        self.output = (self.output + strip_terminal(chunk.decode(errors="replace")))[-20000:]
        if not self.url:
            found = LOGIN_URL.search(self.output)
            if found and ("\n" in self.output[found.end():] or "Paste" in self.output[found.end():]):
                self.url = found.group(0)
                self.phase = "waiting"
                self.phone.start(self.url)
                self.changed()

    async def watch(self, process):
        code = await process.wait()
        if process is not self.process:
            return
        await asyncio.sleep(0.1)
        if process is not self.process:
            return
        self.close_master()
        self.process = None
        self.stop_timer()
        self.phone.stop()
        if code == 0:
            self.url = ""
            self.forget()
            await self.refresh()
            self.phase = "done"
        else:
            lines = [line.strip() for line in self.output.splitlines() if line.strip()]
            failure = next((line for line in reversed(lines) if "fail" in line.lower() or "error" in line.lower()), "")
            self.phase = "failed"
            self.error = failure or f"Login exited with code {code}"
            self.url = ""
        self.changed()

    def submit_code(self, code):
        code = "".join((code or "").split())
        if not code:
            return {"ok": False, "error": "Enter the code from the sign-in page"}
        if self.phase != "waiting" or self.master is None:
            return {"ok": False, "error": "No sign-in is waiting for a code"}
        os.write(self.master, code.encode() + b"\r")
        self.phase = "checking"
        self.changed()
        return {"ok": True}

    def close_master(self):
        if self.master is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.master)
            except RuntimeError:
                pass
            os.close(self.master)
            self.master = None

    def stop_timer(self):
        if self.timeout is not None:
            self.timeout.cancel()
            self.timeout = None

    def expire(self):
        self.timeout = None
        asyncio.get_running_loop().create_task(self.cancel("Sign-in timed out, start again"))

    async def cancel(self, reason=""):
        process = self.process
        self.process = None
        self.phone.stop()
        self.stop_timer()
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
        self.close_master()
        self.url = ""
        self.phase = "failed" if reason else "idle"
        self.error = reason
        self.changed()
        return self.state()

    def fail(self, message):
        self.phase = "failed"
        self.error = message
        self.changed()
        return self.state()

    async def logout(self):
        await self.cancel()
        if self.installed():
            await run([CLAUDE, "auth", "logout"], timeout=20)
        settings = read_json(CLAUDE_SETTINGS)
        env = (settings or {}).get("env") or {}
        removed = [key for key in TOKEN_KEYS if key in env]
        if removed:
            backup = CLAUDE_SETTINGS + ".claude-decky-backup"
            with open(CLAUDE_SETTINGS) as source, open(backup, "w") as target:
                target.write(source.read())
            os.chmod(backup, 0o600)
            for key in removed:
                env.pop(key)
            temporary = CLAUDE_SETTINGS + ".tmp"
            with open(temporary, "w") as handle:
                json.dump(settings, handle, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, CLAUDE_SETTINGS)
            decky.logger.info("Removed %s from %s, backup at %s", removed, CLAUDE_SETTINGS, backup)
        self.forget()
        self.phase = "idle"
        self.error = ""
        await self.refresh()
        self.changed()
        return self.state()

    async def install(self):
        curl = find_program("curl")
        bash = find_program("bash")
        if not curl or not bash:
            return self.fail("curl and bash are needed to install Claude Code")
        self.phase = "installing"
        self.error = ""
        self.install_log = ""
        self.changed()
        code, out, err = await run(
            [bash, "-c", f"set -o pipefail; {curl} -fsSL {INSTALL_SCRIPT} | {bash}"],
            timeout=600,
            cwd=HOME,
        )
        self.install_log = strip_terminal((out + err).decode(errors="replace"))
        self.forget()
        if code != 0 or not self.installed():
            self.phase = "failed"
            self.error = "Install failed, see the log below"
        else:
            self.phase = "idle"
        await self.refresh()
        self.changed()
        return self.state()

    async def shutdown(self):
        await self.cancel()
