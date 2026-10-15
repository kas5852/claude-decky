#!/usr/bin/env python3
import json
import os
import sys
import time

HOME = os.environ["HOME"]
GEMINI = os.path.join(HOME, ".gemini")
SESSIONS = os.path.join(HOME, "gemini_sessions")
args = sys.argv[1:]


def out(event):
    print(json.dumps({**event, "timestamp": "2026-10-15T00:00:00.000Z"}), flush=True)


def log(entry):
    with open(os.path.join(HOME, "calls.jsonl"), "a") as handle:
        handle.write(json.dumps({"agent": "gemini", **entry}) + "\n")


def read_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def selected_type():
    return ((read_json(os.path.join(GEMINI, "settings.json")).get("security") or {}).get("auth") or {}).get("selectedType")


def env_key():
    try:
        lines = open(os.path.join(GEMINI, ".env")).read().splitlines()
    except OSError:
        return ""
    return next((line.split("=", 1)[1] for line in lines if line.startswith("GEMINI_API_KEY=")), "")


def interactive_login():
    if selected_type() != "oauth-personal" or os.environ.get("NO_BROWSER") != "true":
        sys.stdout.write("How would you like to authenticate for this project?\r\n")
        sys.stdout.flush()
        time.sleep(60)
        sys.exit(1)
    attempt = 1
    while True:
        sys.stdout.write(
            "\x1b[?25lPlease visit the following URL to authorize the application:\r\n\r\n"
            f"https://accounts.google.com/o/oauth2/v2/auth?redirect_uri=x&state=s{attempt}&response_type=code\r\n\r\n"
            "Enter the authorization code: "
        )
        sys.stdout.flush()
        code = sys.stdin.readline().strip()
        if code == "good-code":
            time.sleep(0.5)
            with open(os.path.join(GEMINI, "google_accounts.json"), "w") as handle:
                json.dump({"active": "g@example.com", "old": []}, handle)
            with open(os.path.join(GEMINI, "oauth_creds.json"), "w") as handle:
                json.dump({"refresh_token": "r"}, handle)
            while True:
                time.sleep(60)
        sys.stdout.write(
            f"{code}\r\nFailed to authenticate with authorization code:invalid_grant\r\n\r\n"
            "Failed to authenticate with user code. Retrying...\r\n"
        )
        attempt += 1


if not args:
    interactive_login()

prompt = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--prompt="))
includes = [args[index + 1] for index, arg in enumerate(args) if arg == "--include-directories"]
entry = {"args": args, "cwd": os.getcwd(), "prompt": prompt, "trust": os.environ.get("GEMINI_CLI_TRUST_WORKSPACE")}
if prompt.startswith("@"):
    image = prompt[1:].split(" ", 1)[0]
    folder = os.path.dirname(image)
    entry["image_bytes"] = len(open(image, "rb").read()) if folder in includes else 0
    entry["include_listing"] = sorted(os.listdir(folder))
log(entry)
selected = selected_type()
if not (selected == "oauth-personal" and os.path.exists(os.path.join(GEMINI, "oauth_creds.json"))) and not env_key():
    print("Please set an Auth method in your settings.json or specify one of the following environment variables "
          "before running: GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA", file=sys.stderr)
    sys.exit(41)
known = open(SESSIONS).read().split() if os.path.exists(SESSIONS) else []
session = f"gem-{len(known) + 1}"
if "--resume" in args:
    session = args[args.index("--resume") + 1]
    if session not in known:
        print("Error resuming session: No previous sessions found for this project.", file=sys.stderr)
        sys.exit(42)
else:
    with open(SESSIONS, "a") as handle:
        handle.write(session + "\n")
print("Ripgrep is not available. Falling back to GrepTool.", file=sys.stderr)
out({"type": "init", "session_id": session, "model": "auto"})
out({"type": "message", "role": "user", "content": prompt})
if "fail" in prompt:
    inner = json.dumps({"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}, indent=2)
    message = "[API Error: " + json.dumps({"error": {"message": inner, "code": 400, "status": ""}}) + "]"
    out({"type": "result", "status": "error", "error": {"type": "unknown", "message": message}, "stats": {}})
    sys.exit(1)
if "sleep" in prompt:
    time.sleep(60)
for word in ["Gemini ", "says ", "hi"]:
    out({"type": "message", "role": "assistant", "content": word, "delta": True})
    time.sleep(0.15)
if "tool" in prompt:
    out({"type": "tool_use", "tool_name": "run_shell_command", "tool_id": "t1", "parameters": {"command": "ls /home"}})
    out({"type": "tool_result", "tool_id": "t1", "status": "success", "output": "deck"})
    out({"type": "message", "role": "assistant", "content": "Done.", "delta": True})
out({"type": "result", "status": "success", "stats": {"total_tokens": 5}})
