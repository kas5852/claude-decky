import asyncio
import json
import os
import signal
import time

import decky

from .env import CLAUDE, SETTINGS_DIR, child_env, lowered, runtime_path

CHAT_FILE = os.path.join(SETTINGS_DIR, "chat.json")
KEPT_MESSAGES = 200
SENT_MESSAGES = 60
STREAM_LIMIT = 16 * 1024 * 1024
PARTIAL_INTERVAL = 0.25
SYSTEM_PROMPT = (
    "You are answering inside the small Steam Quick Access panel of a SteamOS handheld, "
    "often while the owner is in a game. Keep replies short and plain: a few sentences "
    "or a short list. No tables, no headings, no code blocks unless asked. "
    "Questions may come from speech recognition, so read past small transcription mistakes. "
    "An attached image is a screenshot of what is on the handheld's screen right now. "
    "You have a shell on the device. Use it to find the cause of problems and to improve "
    "performance: frame rate, stutter, temperatures, power limits, game and Proton settings, logs. "
    "Check before changing anything, and say what you changed and how to undo it. "
    "Never close or launch games."
)
WORKSPACE_NOTE = (
    "# Claude Decky workspace\n\n"
    "Claude runs here from the Claude Decky plugin on a SteamOS handheld in game mode.\n"
    "The user asks from the Quick Access menu or by voice while playing, so keep answers short.\n"
)
TOOL_DETAIL_KEYS = ("description", "command", "file_path", "path", "pattern", "query", "url", "prompt")
AUTH_ERRORS = ("invalid api key", "please run /login", "not logged in", "oauth token has expired",
               "authentication_error", "api error: 401", "credit balance is too low", "invalid bearer token")


def describe_tool(block):
    name = block.get("name", "tool")
    details = block.get("input") or {}
    for key in TOOL_DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            detail = " ".join(value.split())
            if len(detail) > 70:
                detail = detail[:67] + "..."
            return f"{name}: {detail}"
    return name


def looks_like_auth_error(text):
    lowered_text = (text or "").lower()
    return any(marker in lowered_text for marker in AUTH_ERRORS)


class Chat:
    def __init__(self, events, settings):
        self.events = events
        self.settings = settings
        self.messages = []
        self.session_id = None
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

    def load(self):
        try:
            with open(CHAT_FILE) as handle:
                saved = json.load(handle)
            self.messages = saved.get("messages", [])[-KEPT_MESSAGES:]
            self.session_id = saved.get("session_id")
        except (OSError, ValueError):
            self.messages = []
            self.session_id = None

    def save(self):
        os.makedirs(os.path.dirname(CHAT_FILE), exist_ok=True)
        temporary = CHAT_FILE + ".tmp"
        with open(temporary, "w") as handle:
            json.dump({"session_id": self.session_id, "messages": self.messages}, handle)
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
        folder = runtime_path("workspace", "CLAUDE.md")
        if not os.path.exists(folder):
            with open(folder, "w") as handle:
                handle.write(WORKSPACE_NOTE)
        return os.path.dirname(folder)

    def command(self):
        args = [
            CLAUDE,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt", SYSTEM_PROMPT,
        ]
        if self.settings["model"]:
            args += ["--model", self.settings["model"]]
        if self.settings["allow_tools"]:
            args += ["--permission-mode", "bypassPermissions"]
        if self.session_id:
            args += ["--resume", self.session_id]
        return lowered(args, self.settings["low_priority"])

    def payload(self, prompt, shot):
        content = []
        if shot:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": shot.media_type, "data": shot.encoded()},
            })
        content.append({"type": "text", "text": prompt})
        message = {"type": "user", "message": {"role": "user", "content": content}}
        return (json.dumps(message) + "\n").encode()

    def attach(self, shot):
        self.attachment = shot
        self.changed()

    def detach(self):
        self.attachment = None
        self.changed()

    async def send(self, prompt, via="text", shot=None):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Type or say a question first"}
        if self.status == "working":
            return {"ok": False, "error": "Claude is still working on the last one"}
        if not os.access(CLAUDE, os.X_OK):
            return {"ok": False, "error": "Claude Code is not installed yet"}
        shot = shot or self.attachment
        self.attachment = None
        extra = {}
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
        self.add("user", prompt, **extra)
        self.task = asyncio.get_running_loop().create_task(self.run(self.payload(prompt, shot)))
        return {"ok": True}

    async def run(self, payload):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command(),
                cwd=self.workdir(),
                env=child_env({"DISABLE_AUTOUPDATER": "1"}),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
                start_new_session=True,
            )
            if self.cancelled:
                self.kill()
            try:
                self.process.stdin.write(payload)
                await self.process.stdin.drain()
                self.process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
            stderr = asyncio.get_running_loop().create_task(self.process.stderr.read())
            async for line in self.process.stdout:
                self.handle_line(line)
            code = await self.process.wait()
            await self.finish(code, (await stderr).decode(errors="replace").strip())
        except Exception as error:
            decky.logger.exception("claude run failed")
            self.fail(str(error) or type(error).__name__)
        finally:
            self.process = None
            self.clear_partial()

    def handle_line(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            return
        kind = event.get("type")
        if kind == "system" and event.get("session_id"):
            self.session_id = event["session_id"]
        elif kind == "stream_event":
            self.handle_stream(event.get("event") or {})
        elif kind == "assistant":
            self.handle_assistant(event.get("message") or {})
        elif kind == "result":
            self.handle_result(event)

    def handle_stream(self, event):
        if event.get("type") == "message_start":
            self.partial = ""
        elif event.get("type") == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                self.partial += delta.get("text", "")
                self.schedule_partial()

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

    def handle_assistant(self, message):
        self.clear_partial()
        for block in message.get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                self.replied = True
                self.add("assistant", block["text"].strip())
            elif block.get("type") == "tool_use":
                self.add("tool", describe_tool(block))

    def handle_result(self, event):
        if event.get("session_id"):
            self.session_id = event["session_id"]
        text = (event.get("result") or "").strip()
        if event.get("is_error"):
            self.error = text or event.get("subtype", "error")
        elif text and not self.replied:
            self.replied = True
            self.add("assistant", text)

    async def finish(self, code, stderr):
        if self.cancelled:
            self.status = "idle"
            self.add("error", "Stopped")
            return
        if "No conversation found" in stderr:
            self.session_id = None
        if code != 0 or self.error:
            last_line = stderr.splitlines()[-1] if stderr else ""
            self.fail(self.error or last_line or f"claude exited with code {code}")
            return
        self.status = "idle"
        self.save()
        self.changed()
        if self.on_reply:
            self.on_reply(self.last_reply())

    def fail(self, message):
        self.status = "error"
        self.error = message
        self.auth_needed = looks_like_auth_error(message)
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
        self.session_id = None
        self.status = "idle"
        self.error = ""
        self.auth_needed = False
        self.attachment = None
        self.clear_partial()
        self.save()
        self.changed()
        return self.state()
