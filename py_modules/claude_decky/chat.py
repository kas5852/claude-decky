import asyncio
import contextlib
import json
import os
import shutil
import signal
import time

import decky

from .env import SETTINGS_DIR, child_env, lowered, runtime_path

CHAT_FILE = os.path.join(SETTINGS_DIR, "chat.json")
KEPT_MESSAGES = 200
SENT_MESSAGES = 60
STREAM_LIMIT = 16 * 1024 * 1024
PARTIAL_INTERVAL = 0.25
WORKSPACE_NOTE = (
    "# Claude Decky workspace\n\n"
    "An AI assistant runs here from the Claude Decky plugin on a SteamOS handheld in game mode.\n"
    "The user asks from the Quick Access menu or by voice while playing, so keep answers short.\n"
)
WORKSPACE_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")


class Chat:
    def __init__(self, events, settings, providers):
        self.events = events
        self.settings = settings
        self.providers = providers
        self.messages = []
        self.sessions = {}
        self.status = "idle"
        self.error = ""
        self.auth_needed = False
        self.partial = ""
        self.started = 0.0
        self.process = None
        self.task = None
        self.cancelled = False
        self.replied = False
        self.attachment = None
        self.partial_handle = None
        self.partial_sent_at = 0.0
        self.on_reply = None
        self.running = None

    @property
    def provider(self):
        return self.providers[self.settings["provider"]]

    @property
    def session_id(self):
        return self.sessions.get(self.settings["provider"])

    @session_id.setter
    def session_id(self, value):
        if value:
            self.sessions[self.settings["provider"]] = value
        else:
            self.sessions.pop(self.settings["provider"], None)

    def load(self):
        try:
            with open(CHAT_FILE) as handle:
                saved = json.load(handle)
            self.messages = saved.get("messages", [])[-KEPT_MESSAGES:]
            self.sessions = dict(saved.get("sessions") or {})
            if saved.get("session_id") and "claude" not in self.sessions:
                self.sessions["claude"] = saved["session_id"]
        except (OSError, ValueError):
            self.messages = []
            self.sessions = {}

    def save(self):
        os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
        temporary = CHAT_FILE + ".tmp"
        with open(temporary, "w") as handle:
            json.dump({"sessions": self.sessions, "messages": self.messages}, handle)
        os.replace(temporary, CHAT_FILE)

    def add(self, role, text, **extra):
        message = {"role": role, "text": text, "time": time.time()}
        message.update(extra)
        self.messages.append(message)
        self.messages = self.messages[-KEPT_MESSAGES:]
        self.save()
        self.changed()

    def state(self):
        return {
            "messages": self.messages[-SENT_MESSAGES:],
            "status": self.status,
            "error": self.error,
            "authNeeded": self.auth_needed,
            "partial": self.partial,
            "started": self.started if self.status == "working" else 0,
            "resumable": self.session_id is not None,
            "attachment": {"thumb": self.attachment.thumb} if self.attachment else None,
        }

    def changed(self):
        if self.events.visible:
            self.events.emit("chat_state", self.state())

    def workdir(self):
        configured = os.path.expanduser(self.settings["workdir"]) if self.settings["workdir"] else ""
        if configured and os.path.isdir(configured):
            return configured
        folder = os.path.dirname(runtime_path("workspace", WORKSPACE_FILES[0]))
        for name in WORKSPACE_FILES:
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                with open(path, "w") as handle:
                    handle.write(WORKSPACE_NOTE)
        return folder

    def run_spec(self, prompt, shot):
        return self.provider.run_spec(prompt, shot, self.session_id, self.settings, self.workdir())

    def command(self):
        return lowered(self.run_spec("", None).args, self.settings["low_priority"])

    def attach(self, shot):
        self.attachment = shot
        self.changed()

    def detach(self):
        self.attachment = None
        self.changed()

    async def send(self, prompt, via="text", shot=None):
        prompt = (prompt or "").strip()
        provider = self.provider
        if not prompt:
            return {"ok": False, "error": "Type or say a question first"}
        if self.status == "working":
            return {"ok": False, "error": f"{self.running.short if self.running else provider.short} is still working on the last one"}
        if not provider.installed():
            return {"ok": False, "error": f"{provider.label} is not installed yet"}
        shot = shot or self.attachment
        self.attachment = None
        extra = {"agent": provider.id}
        if via != "text":
            extra["via"] = via
        if shot:
            extra["image"] = True
        self.status = "working"
        self.error = ""
        self.auth_needed = False
        self.partial = ""
        self.started = time.time()
        self.cancelled = False
        self.replied = False
        self.running = provider
        self.add("user", prompt, **extra)
        spec = provider.run_spec(prompt, shot, self.session_id, self.settings, self.workdir())
        self.task = asyncio.get_running_loop().create_task(self.run(provider, spec))
        return {"ok": True}

    async def run(self, provider, spec):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *lowered(spec.args, self.settings["low_priority"]),
                cwd=self.workdir(),
                env=child_env(spec.env),
                stdin=asyncio.subprocess.PIPE if spec.stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
                start_new_session=True,
            )
            if self.cancelled:
                self.kill()
            if spec.stdin:
                try:
                    self.process.stdin.write(spec.stdin)
                    await self.process.stdin.drain()
                    self.process.stdin.close()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            stderr = asyncio.get_running_loop().create_task(self.process.stderr.read())
            async for line in self.process.stdout:
                self.handle_line(provider, line)
            code = await self.process.wait()
            await self.finish(provider, code, (await stderr).decode(errors="replace").strip())
        except Exception as error:
            decky.logger.exception("%s run failed", provider.id)
            self.fail(provider, str(error) or type(error).__name__)
        finally:
            self.process = None
            self.running = None
            self.clear_partial()
            for path in spec.cleanup:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    with contextlib.suppress(OSError):
                        os.unlink(path)

    def handle_line(self, provider, line):
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        for step in provider.parse(event):
            self.apply(provider, step)

    def apply(self, provider, step):
        if step.kind == "session":
            if step.text:
                self.sessions[provider.id] = step.text
        elif step.kind == "partial_reset":
            self.clear_partial()
        elif step.kind == "delta":
            self.partial += step.text
            self.schedule_partial()
        elif step.kind == "text":
            self.clear_partial()
            self.replied = True
            self.add("assistant", step.text, agent=provider.id)
        elif step.kind == "flush":
            text = self.partial.strip()
            self.clear_partial()
            if text:
                self.replied = True
                self.add("assistant", text, agent=provider.id)
        elif step.kind == "tool":
            self.add("tool", step.text, agent=provider.id)
        elif step.kind == "final":
            if not self.replied:
                self.replied = True
                self.add("assistant", step.text, agent=provider.id)
        elif step.kind == "error":
            self.error = step.text

    def schedule_partial(self):
        if not self.events.visible or self.partial_handle is not None:
            return
        delay = max(0.0, self.partial_sent_at + PARTIAL_INTERVAL - time.monotonic())
        self.partial_handle = asyncio.get_running_loop().call_later(delay, self.flush_partial)

    def flush_partial(self):
        self.partial_handle = None
        self.partial_sent_at = time.monotonic()
        if self.events.visible:
            self.events.emit("chat_partial", self.partial)

    def clear_partial(self):
        if self.partial_handle is not None:
            self.partial_handle.cancel()
            self.partial_handle = None
        self.partial = ""

    async def finish(self, provider, code, stderr):
        if self.cancelled:
            self.status = "idle"
            self.add("error", "Stopped")
            return
        if provider.stale_session(stderr):
            self.sessions.pop(provider.id, None)
        if code != 0 or self.error:
            last_line = stderr.splitlines()[-1] if stderr else ""
            self.fail(provider, self.error or last_line or f"{provider.executable} exited with code {code}")
            return
        self.status = "idle"
        self.save()
        self.changed()
        if self.on_reply:
            self.on_reply(self.last_reply())

    def fail(self, provider, message):
        self.status = "error"
        self.error = message
        self.auth_needed = provider.looks_like_auth_error(message)
        self.add("error", message)

    def last_reply(self):
        for message in reversed(self.messages):
            if message["role"] == "assistant":
                return message["text"]
        return ""

    def kill(self):
        if self.process and self.process.returncode is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def cancel(self):
        if self.status != "working":
            return False
        self.cancelled = True
        self.kill()
        return True

    async def new_chat(self):
        if self.cancel() and self.task:
            await asyncio.wait([self.task], timeout=5)
        self.messages = []
        self.sessions = {}
        self.status = "idle"
        self.error = ""
        self.auth_needed = False
        self.attachment = None
        self.clear_partial()
        self.save()
        self.changed()
        return self.state()
