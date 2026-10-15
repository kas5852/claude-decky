import os
import re
import shutil
import time

import decky

from ..env import HOME, read_json, runtime_path
from .base import SYSTEM_PROMPT, LoginPrompt, Provider, RunSpec, Step, backup_file, describe_tool, write_private_json

GEMINI_DIR = os.path.join(HOME, ".gemini")
SETTINGS = os.path.join(GEMINI_DIR, "settings.json")
ENV_FILE = os.path.join(GEMINI_DIR, ".env")
CREDENTIALS = os.path.join(GEMINI_DIR, "oauth_creds.json")
ACCOUNTS = os.path.join(GEMINI_DIR, "google_accounts.json")
INSTALL_DIR = os.path.join(HOME, ".local", "share", "gemini-cli")
LOGIN_URL = re.compile(r"https://accounts\.google\.com/\S+")
INNER_MESSAGE = re.compile(r'message\\*"\s*:\s*\\*"([^"\\]{3,})')
KEY_LINE = re.compile(r"^\s*(?:export\s+)?GEMINI_API_KEY\s*=")
FAILED = "Failed to authenticate"
TRUST = {"GEMINI_CLI_TRUST_WORKSPACE": "true"}
INSTALL = f"""
dir="{INSTALL_DIR}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp" "$dir.new"' EXIT
base=https://nodejs.org/dist/latest-v24.x
line=$(curl -fsSL "$base/SHASUMS256.txt" | grep ' node-v[0-9.]*-linux-x64.tar.xz$')
file=${{line##* }}
curl -fL --retry 3 -o "$tmp/$file" "$base/$file"
(cd "$tmp" && echo "$line" | sha256sum -c -)
rm -rf "$dir.new"
mkdir -p "$dir.new/node"
tar -xJf "$tmp/$file" -C "$dir.new/node" --strip-components=1
PATH="$dir.new/node/bin:$PATH" "$dir.new/node/bin/npm" install -g --prefix "$dir.new/cli" --no-fund --no-audit @google/gemini-cli
rm -rf "$dir"
mv "$dir.new" "$dir"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/gemini" <<'WRAPPER'
#!/bin/sh
dir="$HOME/.local/share/gemini-cli"
PATH="$dir/node/bin:$PATH" exec "$dir/node/bin/node" "$dir/cli/lib/node_modules/@google/gemini-cli/bundle/gemini.js" "$@"
WRAPPER
chmod 755 "$HOME/.local/bin/gemini"
"$HOME/.local/bin/gemini" --version
"""


def read_env_key():
    try:
        with open(ENV_FILE) as handle:
            lines = handle.read().splitlines()
    except OSError:
        return ""
    for line in lines:
        if KEY_LINE.match(line):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def update_settings(change):
    settings = read_json(SETTINGS)
    if settings is None:
        settings = {}
    elif os.path.exists(SETTINGS):
        backup_file(SETTINGS)
    change(settings)
    write_private_json(SETTINGS, settings)


def set_auth_type(value):
    def change(settings):
        auth = settings.setdefault("security", {}).setdefault("auth", {})
        if value:
            auth["selectedType"] = value
        else:
            auth.pop("selectedType", None)
    update_settings(change)


def auth_type():
    return (((read_json(SETTINGS) or {}).get("security") or {}).get("auth") or {}).get("selectedType")


def clean_error(message):
    found = INNER_MESSAGE.findall(message or "")
    text = found[-1] if found else (message or "")
    return text.strip()[:300] or "Gemini failed"


class GeminiProvider(Provider):
    id = "gemini"
    label = "Gemini CLI"
    short = "Gemini"
    executable = "gemini"
    model_key = "gemini_model"
    models = {"": "Auto", "pro": "Pro (smartest)", "flash": "Flash", "flash-lite": "Flash-Lite (fastest)"}
    login_flows = {"google": "Sign in with Google", "api_key": "Use a Gemini API key instead"}
    api_key_url = "https://aistudio.google.com/apikey"
    install_hint = "Downloads Node.js and Gemini CLI (about 150 MB) to ~/.local/share, no admin rights needed."
    tools_off_hint = "Off limits Gemini to tools that need no approval."
    login_exits = False
    live_status = True
    auth_errors = ("api key not valid", "please set an auth method", "unauthenticated", "invalid_grant",
                   "manual authorization is required", "invalid authentication", "login required")

    def quick_status(self):
        if not self.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        selected = auth_type()
        if selected == "oauth-personal" and os.path.exists(CREDENTIALS):
            status = {"installed": True, "loggedIn": True, "method": "google"}
            email = (read_json(ACCOUNTS) or {}).get("active")
            if email:
                status["email"] = email
            return status
        if selected in (None, "gemini-api-key") and read_env_key():
            return {"installed": True, "loggedIn": True, "method": "GEMINI_API_KEY"}
        return {"installed": True, "loggedIn": False, "method": "none"}

    async def status(self):
        return self.quick_status()

    def before_login(self, flow):
        if flow == "google":
            set_auth_type("oauth-personal")

    def login_args(self, flow):
        return [self.binary()]

    def login_env(self, flow):
        return {"NO_BROWSER": "true", **TRUST}

    def scan_login(self, output):
        found = LOGIN_URL.search(output)
        if found and "authorization code" in output[found.end():]:
            return LoginPrompt(url=found.group(0), wants_code=True)
        return None

    def login_verdict(self, output, started):
        if FAILED in output:
            line = next(line for line in output.splitlines() if FAILED in line)
            return "Google didn't accept that code: " + line.split(":", 1)[-1].strip()
        try:
            if os.path.getmtime(CREDENTIALS) >= started:
                return "done"
        except OSError:
            pass
        return None

    async def save_api_key(self, key):
        try:
            lines = []
            if os.path.exists(ENV_FILE):
                backup_file(ENV_FILE)
                with open(ENV_FILE) as handle:
                    lines = [line for line in handle.read().splitlines() if not KEY_LINE.match(line)]
            os.makedirs(GEMINI_DIR, exist_ok=True)
            temporary = ENV_FILE + ".tmp"
            with open(temporary, "w") as handle:
                handle.write("\n".join([*lines, f"GEMINI_API_KEY={key}"]) + "\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, ENV_FILE)
            set_auth_type("gemini-api-key")
        except OSError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True}

    async def logout(self):
        for path in (CREDENTIALS, ACCOUNTS):
            if os.path.exists(path):
                os.unlink(path)
        if read_env_key():
            backup = backup_file(ENV_FILE)
            with open(ENV_FILE) as handle:
                kept = [line for line in handle.read().splitlines() if not KEY_LINE.match(line)]
            with open(ENV_FILE, "w") as handle:
                handle.write("\n".join(kept) + ("\n" if kept else ""))
            decky.logger.info("Removed GEMINI_API_KEY from %s, backup at %s", ENV_FILE, backup)
        if auth_type():
            set_auth_type(None)

    def install_script(self):
        return INSTALL

    def after_install(self):
        def change(settings):
            general = settings.setdefault("general", {})
            general["enableAutoUpdate"] = False
            general["enableAutoUpdateNotification"] = False
        update_settings(change)

    def run_spec(self, prompt, shot, session_id, settings, workdir):
        args = [self.binary(), "-o", "stream-json", "--approval-mode", "yolo" if settings["allow_tools"] else "default"]
        if settings[self.model_key]:
            args += ["-m", settings[self.model_key]]
        if session_id:
            args += ["--resume", session_id]
        else:
            prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"
        cleanup = []
        if shot:
            image = runtime_path("gemini-shots", str(time.time_ns()), "screen" + os.path.splitext(shot.path)[1])
            folder = os.path.dirname(image)
            shutil.copyfile(shot.path, image)
            cleanup.append(folder)
            args += ["--include-directories", folder]
            prompt = f"@{image} {prompt}"
        args.append("--prompt=" + prompt)
        return RunSpec(args=args, env=dict(TRUST), cleanup=cleanup)

    def parse(self, event):
        kind = event.get("type")
        if kind == "init" and event.get("session_id"):
            return [Step("session", event["session_id"])]
        if kind == "message" and event.get("role") == "assistant":
            return [Step("delta", event.get("content") or "")]
        if kind == "tool_use":
            return [Step("flush"), Step("tool", describe_tool(event.get("tool_name", "tool"), event.get("parameters")))]
        if kind == "error" and event.get("severity") == "error":
            return [Step("error", clean_error(event.get("message")))]
        if kind == "result":
            steps = [Step("flush")]
            if event.get("status") != "success":
                steps.append(Step("error", clean_error((event.get("error") or {}).get("message"))))
            return steps
        return []

    def stale_session(self, stderr):
        return "Error resuming session" in stderr
