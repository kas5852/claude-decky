import json
import os
from dataclasses import dataclass, field

from ..env import LOCAL_BIN


@dataclass
class RunSpec:
    args: list
    stdin: bytes = b""
    env: dict = field(default_factory=dict)
    cleanup: list = field(default_factory=list)


@dataclass
class LoginPrompt:
    url: str
    user_code: str = ""
    wants_code: bool = False


@dataclass
class Step:
    kind: str
    text: str = ""


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
TOOL_DETAIL_KEYS = ("description", "command", "file_path", "path", "pattern", "query", "url", "prompt")


def short_detail(value, limit=70):
    detail = " ".join(str(value).split())
    return detail if len(detail) <= limit else detail[: limit - 3] + "..."


def describe_tool(name, details):
    details = details if isinstance(details, dict) else {}
    for key in TOOL_DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        if isinstance(value, str) and value.strip():
            return f"{name}: {short_detail(value)}"
    return name


def write_private_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(data, handle, indent=2)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def backup_file(path):
    backup = path + ".claude-decky-backup"
    with open(path, "rb") as source, open(backup, "wb") as target:
        target.write(source.read())
    os.chmod(backup, 0o600)
    return backup


class Provider:
    id = ""
    label = ""
    short = ""
    executable = ""
    model_key = "model"
    models = {"": "Default"}
    login_flows = {}
    auth_errors = ()
    install_hint = ""
    tools_off_hint = ""
    api_key_url = ""
    login_exits = True
    live_status = False

    def binary(self):
        return os.path.join(LOCAL_BIN, self.executable)

    def installed(self):
        return os.access(self.binary(), os.X_OK)

    def quick_status(self):
        return {"installed": self.installed(), "loggedIn": False, "method": "none", "guess": True}

    async def status(self):
        raise NotImplementedError

    def login_args(self, flow):
        raise NotImplementedError

    def before_login(self, flow):
        pass

    def login_env(self, flow):
        return {}

    def login_verdict(self, output, started):
        return None

    def api_key_prompt(self):
        return LoginPrompt(url=self.api_key_url, wants_code=True)

    def after_install(self):
        pass

    def scan_login(self, output):
        return None

    def code_input(self, code):
        return code.encode() + b"\r"

    async def save_api_key(self, key):
        return {"ok": False, "error": "Not supported"}

    async def logout(self):
        raise NotImplementedError

    def install_script(self):
        raise NotImplementedError

    def run_spec(self, prompt, shot, session_id, settings, workdir):
        raise NotImplementedError

    def parse(self, event):
        return []

    def stale_session(self, stderr):
        return False

    def looks_like_auth_error(self, text):
        lowered_text = (text or "").lower()
        return any(marker in lowered_text for marker in self.auth_errors)

    def describe(self):
        return {
            "id": self.id,
            "label": self.label,
            "short": self.short,
            "models": self.models,
            "modelKey": self.model_key,
            "loginFlows": self.login_flows,
            "installHint": self.install_hint,
            "toolsOffHint": self.tools_off_hint,
        }
