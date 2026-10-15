import asyncio
import json
import os
import signal
import time

import decky

USER_HOME = decky.DECKY_USER_HOME
CLAUDE = os.path.join(USER_HOME, ".local", "bin", "claude")
WORKDIR = os.path.join(USER_HOME, "claude-workdir")
CHAT_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "chat.json")
KEPT_MESSAGES = 200
SENT_MESSAGES = 80
STREAM_LIMIT = 16 * 1024 * 1024
SYSTEM_PROMPT = (
    "You are answering inside the small Steam Quick Access panel of this handheld, "
    "often while the owner is in a game. Keep replies short and plain: a few sentences "
    "or a short list. No tables, no headings, no code blocks unless asked."
)
TOOL_DETAIL_KEYS = ("description", "command", "file_path", "path", "pattern", "query", "url", "prompt")


def child_env():
    uid = os.getuid()
    return {
        "HOME": USER_HOME,
        "USER": decky.DECKY_USER,
        "LOGNAME": decky.DECKY_USER,
        "SHELL": "/bin/bash",
        "PATH": f"{USER_HOME}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
    }


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


class Chat:
    def __init__(self):
        self.messages = []
        self.session_id = None
        self.status = "idle"
        self.error = ""
        self.partial = ""
        self.started = 0.0
        self.process = None
        self.task = None
        self.cancelled = False
        self.replied = False

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

    def add(self, role, text):
        self.messages.append({"role": role, "text": text, "time": time.time()})
        self.messages = self.messages[-KEPT_MESSAGES:]
        self.save()

    def state(self):
        return {
            "messages": self.messages[-SENT_MESSAGES:],
            "status": self.status,
            "error": self.error,
            "partial": self.partial,
            "elapsed": int(time.time() - self.started) if self.status == "working" else 0,
            "resumable": self.session_id is not None,
        }

    def command(self):
        args = [
            CLAUDE,
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt", SYSTEM_PROMPT,
        ]
        if self.session_id:
            args += ["--resume", self.session_id]
        return args

    async def send(self, prompt):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Type a question first"}
        if self.status == "working":
            return {"ok": False, "error": "Claude is still working on the last one"}
        self.add("user", prompt)
        self.status = "working"
        self.error = ""
        self.partial = ""
        self.started = time.time()
        self.cancelled = False
        self.replied = False
        self.task = asyncio.get_event_loop().create_task(self.run(prompt))
        return {"ok": True}

    async def run(self, prompt):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command(),
                cwd=WORKDIR,
                env=child_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
                start_new_session=True,
            )
            if self.cancelled:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.stdin.write(prompt.encode())
                await self.process.stdin.drain()
                self.process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
            stderr = asyncio.get_event_loop().create_task(self.process.stderr.read())
            async for line in self.process.stdout:
                self.handle_line(line)
            code = await self.process.wait()
            await self.finish(code, (await stderr).decode(errors="replace").strip())
        except Exception as error:
            decky.logger.exception("claude run failed")
            self.fail(str(error) or type(error).__name__)
        finally:
            self.process = None
            self.partial = ""

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

    def handle_assistant(self, message):
        for block in message.get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                self.add("assistant", block["text"].strip())
                self.replied = True
            elif block.get("type") == "tool_use":
                self.add("tool", describe_tool(block))
        self.partial = ""

    def handle_result(self, event):
        if event.get("session_id"):
            self.session_id = event["session_id"]
        text = (event.get("result") or "").strip()
        if event.get("is_error"):
            self.error = text or event.get("subtype", "error")
        elif text and not self.replied:
            self.add("assistant", text)
            self.replied = True

    async def finish(self, code, stderr):
        if self.cancelled:
            self.add("error", "Stopped")
            self.status = "idle"
            self.save()
            return
        if "No conversation found" in stderr:
            self.session_id = None
        if code != 0 or self.error:
            last_line = stderr.splitlines()[-1] if stderr else ""
            self.fail(self.error or last_line or f"claude exited with code {code}")
            return
        self.status = "idle"
        self.save()
        await decky.emit("claude_done", self.last_reply())

    def fail(self, message):
        self.status = "error"
        self.error = message
        self.add("error", message)

    def last_reply(self):
        for message in reversed(self.messages):
            if message["role"] == "assistant":
                return message["text"]
        return ""

    def cancel(self):
        if self.status != "working":
            return False
        self.cancelled = True
        if self.process and self.process.returncode is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return True

    async def new_chat(self):
        if self.cancel() and self.task:
            await asyncio.wait([self.task], timeout=5)
        self.messages = []
        self.session_id = None
        self.status = "idle"
        self.error = ""
        self.partial = ""
        self.save()
        return self.state()


chat = Chat()


class Plugin:
    async def send(self, prompt: str) -> dict:
        return await chat.send(prompt)

    async def get_state(self) -> dict:
        return chat.state()

    async def new_chat(self) -> dict:
        return await chat.new_chat()

    async def cancel(self) -> bool:
        return chat.cancel()

    async def _main(self):
        chat.load()
        decky.logger.info("Claude plugin ready, %d saved messages", len(chat.messages))

    async def _unload(self):
        chat.cancel()

    async def _uninstall(self):
        chat.cancel()
