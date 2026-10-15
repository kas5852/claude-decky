import json
import os
import re

from ..env import HOME, run
from .base import SYSTEM_PROMPT, LoginPrompt, Provider, RunSpec, Step, describe_tool, short_detail

AUTH_FILE = os.path.join(HOME, ".codex", "auth.json")
DEVICE_URL = re.compile(r"https://auth\.openai\.com/\S*device\S*")
USER_CODE = re.compile(r"one-time code[^\n]*\n\s*([A-Z0-9]{3,}(?:-[A-Z0-9]{3,})+)")
RELEASE = "https://github.com/openai/codex/releases/latest/download/codex-x86_64-unknown-linux-musl.tar.gz"
INSTALL = f"""
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fL --retry 3 -o "$tmp/codex.tar.gz" {RELEASE}
tar -xzf "$tmp/codex.tar.gz" -C "$tmp"
mkdir -p "$HOME/.local/bin"
install -m 755 "$tmp/codex-x86_64-unknown-linux-musl" "$HOME/.local/bin/codex"
"$HOME/.local/bin/codex" --version
"""


class CodexProvider(Provider):
    id = "codex"
    label = "Codex"
    short = "Codex"
    executable = "codex"
    model_key = "codex_model"
    models = {"": "Default", "gpt-6-sol": "GPT-6 Sol", "gpt-6-luna": "GPT-6 Luna", "gpt-5.5": "GPT-5.5"}
    login_flows = {"device": "Sign in with ChatGPT", "api_key": "Use an OpenAI API key instead"}
    api_key_url = "https://platform.openai.com/api-keys"
    install_hint = "Downloads the official Codex release (about 110 MB) to ~/.local/bin, no admin rights needed."
    tools_off_hint = "Off keeps Codex read-only."
    auth_errors = ("401 unauthorized", "not logged in", "missing bearer", "invalid api key",
                   "incorrect api key", "refresh token", "please log in", "codex login")

    def quick_status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        logged = os.path.exists(AUTH_FILE)
        return {"installed": True, "loggedIn": logged, "method": "chatgpt" if logged else "none", "guess": True}

    async def status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        code, out, err = await run([self.binary(), "login", "status"], timeout=20)
        text = (out + err).decode(errors="replace")
        if code != 0 or "Logged in" not in text:
            return {"installed": True, "loggedIn": False, "method": "none"}
        return {"installed": True, "loggedIn": True, "method": "api_key" if "API key" in text else "chatgpt"}

    def login_args(self, flow):
        return [self.binary(), "login", "--device-auth"]

    def scan_login(self, output):
        url = DEVICE_URL.search(output)
        code = USER_CODE.search(output)
        if url and code:
            return LoginPrompt(url=url.group(0), user_code=code.group(1))
        return None

    async def save_api_key(self, key):
        code, out, err = await run([self.binary(), "login", "--with-api-key"], timeout=30, stdin=key.encode())
        if code == 0:
            return {"ok": True}
        lines = (out + err).decode(errors="replace").strip().splitlines()
        return {"ok": False, "error": lines[-1] if lines else "Codex didn't accept the key"}

    async def logout(self):
        if self.installed():
            await run([self.binary(), "logout"], timeout=20)

    def install_script(self):
        return INSTALL

    def run_spec(self, prompt, shot, session_id, settings, workdir):
        args = [
            self.binary(), "exec",
            "--json",
            "--skip-git-repo-check",
            "-C", workdir,
            "-c", "developer_instructions=" + json.dumps(SYSTEM_PROMPT),
            "-c", "check_for_update_on_startup=false",
        ]
        if settings["allow_tools"]:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            args += ["-s", "read-only"]
        if settings[self.model_key]:
            args += ["-m", settings[self.model_key]]
        if session_id:
            args += ["resume", session_id]
        if shot:
            args += ["--image", shot.path]
        return RunSpec(args=args, stdin=prompt.encode() + b"\n", env={"RUST_LOG": "off"})

    def parse(self, event):
        kind = event.get("type")
        item = event.get("item") or {}
        item_type = item.get("type")
        if kind == "thread.started" and event.get("thread_id"):
            return [Step("session", event["thread_id"])]
        if kind == "turn.failed":
            return [Step("error", (event.get("error") or {}).get("message") or "Codex failed")]
        if kind == "error":
            message = event.get("message") or ""
            return [] if message.startswith("Reconnecting") else [Step("error", message)]
        if kind == "item.started":
            if item_type == "command_execution":
                return [Step("tool", "Run: " + short_detail(item.get("command", "")))]
            if item_type == "mcp_tool_call":
                return [Step("tool", describe_tool(f"{item.get('server')}.{item.get('tool')}", item.get("arguments")))]
            return []
        if kind != "item.completed":
            return []
        if item_type == "agent_message" and (item.get("text") or "").strip():
            return [Step("text", item["text"].strip())]
        if item_type == "file_change":
            paths = ", ".join(change.get("path", "") for change in item.get("changes") or [])
            return [Step("tool", "Edit: " + short_detail(paths))]
        if item_type == "web_search":
            return [Step("tool", "Search: " + short_detail(item.get("query", "")))]
        return []

    def stale_session(self, stderr):
        return "no rollout found" in stderr
