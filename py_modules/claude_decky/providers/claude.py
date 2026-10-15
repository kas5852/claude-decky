import json
import os
import re

import decky

from ..env import HOME, read_json, run
from .base import SYSTEM_PROMPT, LoginPrompt, Provider, RunSpec, Step, backup_file, describe_tool, write_private_json

SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CREDENTIALS = os.path.join(HOME, ".claude", ".credentials.json")
TOKEN_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
LOGIN_URL = re.compile(r"https://\S*oauth/authorize\?\S+")


def stored_token_keys():
    env = (read_json(SETTINGS) or {}).get("env") or {}
    return [key for key in TOKEN_KEYS if env.get(key)]


class ClaudeProvider(Provider):
    id = "claude"
    label = "Claude Code"
    short = "Claude"
    executable = "claude"
    models = {"": "Default", "haiku": "Haiku (fastest)", "sonnet": "Sonnet", "opus": "Opus (smartest)"}
    login_flows = {"claudeai": "Sign in with Claude", "console": "Use an Anthropic Console account instead"}
    install_hint = "Installs to ~/.local/bin, no admin rights needed."
    tools_off_hint = "Off uses your Claude Code permission settings."
    auth_errors = ("invalid api key", "please run /login", "not logged in", "oauth token has expired",
                   "authentication_error", "api error: 401", "credit balance is too low", "invalid bearer token")

    def quick_status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        keys = stored_token_keys()
        if keys:
            return {"installed": True, "loggedIn": True, "method": keys[0], "guess": True}
        if os.path.exists(CREDENTIALS):
            return {"installed": True, "loggedIn": True, "method": "claude.ai", "guess": True}
        return {"installed": True, "loggedIn": False, "method": "none", "guess": True}

    async def status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        _, out, _ = await run([self.binary(), "auth", "status", "--json"], timeout=20)
        try:
            data = json.loads(out.decode())
        except ValueError:
            data = {"loggedIn": False, "authMethod": "unknown"}
        status = {"installed": True, "loggedIn": bool(data.get("loggedIn")), "method": data.get("authMethod") or "none"}
        for key in ("email", "orgName", "subscriptionType"):
            if data.get(key):
                status[key] = data[key]
        return status

    def login_args(self, flow):
        return [self.binary(), "auth", "login", "--console" if flow == "console" else "--claudeai"]

    def scan_login(self, output):
        found = LOGIN_URL.search(output)
        if found and ("\n" in output[found.end():] or "Paste" in output[found.end():]):
            return LoginPrompt(url=found.group(0), wants_code=True)
        return None

    async def logout(self):
        if self.installed():
            await run([self.binary(), "auth", "logout"], timeout=20)
        settings = read_json(SETTINGS)
        env = (settings or {}).get("env") or {}
        removed = [key for key in TOKEN_KEYS if key in env]
        if removed:
            backup = backup_file(SETTINGS)
            for key in removed:
                env.pop(key)
            write_private_json(SETTINGS, settings)
            decky.logger.info("Removed %s from %s, backup at %s", removed, SETTINGS, backup)

    def install_script(self):
        return "curl -fsSL https://claude.ai/install.sh | bash"

    def run_spec(self, prompt, shot, session_id, settings, workdir):
        args = [
            self.binary(), "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--append-system-prompt", SYSTEM_PROMPT,
        ]
        if settings["model"]:
            args += ["--model", settings["model"]]
        if settings["allow_tools"]:
            args += ["--permission-mode", "bypassPermissions"]
        if session_id:
            args += ["--resume", session_id]
        content = []
        if shot:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": shot.media_type, "data": shot.encoded()},
            })
        content.append({"type": "text", "text": prompt})
        message = {"type": "user", "message": {"role": "user", "content": content}}
        return RunSpec(args=args, stdin=(json.dumps(message) + "\n").encode(), env={"DISABLE_AUTOUPDATER": "1"})

    def parse(self, event):
        kind = event.get("type")
        steps = []
        if kind == "system" and event.get("session_id"):
            steps.append(Step("session", event["session_id"]))
        elif kind == "stream_event":
            inner = event.get("event") or {}
            if inner.get("type") == "message_start":
                steps.append(Step("partial_reset"))
            elif inner.get("type") == "content_block_delta":
                delta = inner.get("delta") or {}
                if delta.get("type") == "text_delta":
                    steps.append(Step("delta", delta.get("text", "")))
        elif kind == "assistant":
            steps.append(Step("partial_reset"))
            for block in (event.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    steps.append(Step("text", block["text"].strip()))
                elif block.get("type") == "tool_use":
                    steps.append(Step("tool", describe_tool(block.get("name", "tool"), block.get("input"))))
        elif kind == "result":
            if event.get("session_id"):
                steps.append(Step("session", event["session_id"]))
            text = (event.get("result") or "").strip()
            if event.get("is_error"):
                steps.append(Step("error", text or event.get("subtype", "error")))
            elif text:
                steps.append(Step("final", text))
        return steps

    def stale_session(self, stderr):
        return "No conversation found" in stderr
