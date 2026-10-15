#!/usr/bin/env python3
import json
import os
import sys
import time

HOME = os.environ["HOME"]
AUTH = os.path.join(HOME, ".codex", "auth.json")
APPROVED = os.path.join(HOME, ".codex_device_approved")
args = sys.argv[1:]


def out(event):
    print(json.dumps(event), flush=True)


def log(entry):
    with open(os.path.join(HOME, "calls.jsonl"), "a") as handle:
        handle.write(json.dumps({"agent": "codex", **entry}) + "\n")


def save_auth(mode):
    os.makedirs(os.path.dirname(AUTH), exist_ok=True)
    with open(AUTH, "w") as handle:
        json.dump({"mode": mode}, handle)


if args[:2] == ["login", "status"]:
    if not os.path.exists(AUTH):
        print("Not logged in", file=sys.stderr)
        sys.exit(1)
    mode = json.load(open(AUTH))["mode"]
    print("Logged in using an API key - ***" if mode == "api_key" else "Logged in using ChatGPT", file=sys.stderr)
    sys.exit(0)
if args[:2] == ["login", "--with-api-key"]:
    print("Reading API key from stdin...", file=sys.stderr)
    key = sys.stdin.read()
    log({"args": args, "stdin": key})
    if not key.startswith("sk-"):
        print("Error: invalid API key", file=sys.stderr)
        sys.exit(1)
    save_auth("api_key")
    print("Successfully logged in", file=sys.stderr)
    sys.exit(0)
if args[:2] == ["login", "--device-auth"]:
    sys.stdout.write(
        "\r\nWelcome to Codex [v\x1b[90m0.160.0\x1b[0m]\r\n\x1b[90mOpenAI's command-line coding agent\x1b[0m\r\n\r\n"
        "Follow these steps to sign in with ChatGPT using device code authorization:\r\n\r\n"
        "1. Open this link in your browser and sign in to your account\r\n"
        "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\r\n\r\n"
        "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\r\n"
        "   \x1b[94mXFP3-ZY5C0\x1b[0m\r\n\r\n"
        "\x1b[90mContinue only if you started this login in Codex.\x1b[0m\r\n\r\n"
    )
    sys.stdout.flush()
    deadline = time.time() + 30
    while time.time() < deadline:
        if os.path.exists(APPROVED):
            os.unlink(APPROVED)
            save_auth("chatgpt")
            print("Successfully logged in", file=sys.stderr)
            sys.exit(0)
        time.sleep(0.1)
    print("Error logging in with device code: device auth timed out", file=sys.stderr)
    sys.exit(1)
if args[:1] == ["logout"]:
    if os.path.exists(AUTH):
        os.unlink(AUTH)
    print("Successfully logged out")
    sys.exit(0)

prompt = sys.stdin.read()
entry = {"args": args, "cwd": os.getcwd(), "stdin": prompt, "env_rust_log": os.environ.get("RUST_LOG")}
if "--image" in args:
    with open(args[args.index("--image") + 1], "rb") as handle:
        entry["image_bytes"] = len(handle.read())
log(entry)
thread = "thr-1"
if "resume" in args:
    thread = args[args.index("resume") + 1]
    if thread != "thr-1":
        print("Reading prompt from stdin...", file=sys.stderr)
        print(f"Error: thread/resume: thread/resume failed: no rollout found for thread id {thread} (code -32600)", file=sys.stderr)
        sys.exit(1)
out({"type": "thread.started", "thread_id": thread})
out({"type": "turn.started"})
if "fail" in prompt:
    for attempt in range(1, 3):
        out({"type": "error", "message": f"Reconnecting... {attempt}/5 (unexpected status 401 Unauthorized: Missing bearer)"})
    message = "unexpected status 401 Unauthorized: Missing bearer or basic authentication in header"
    out({"type": "error", "message": message})
    out({"type": "turn.failed", "error": {"message": message}})
    sys.exit(1)
if "flaky" in prompt:
    out({"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion)"})
if "sleep" in prompt:
    time.sleep(60)
out({"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "thinking"}})
if "tool" in prompt:
    command = "bash -lc 'cat /sys/class/power_supply/BAT0/capacity'"
    out({"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": command, "status": "in_progress"}})
    out({"type": "item.completed", "item": {"id": "item_1", "type": "command_execution", "command": command,
                                            "aggregated_output": "80", "exit_code": 0, "status": "completed"}})
out({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "Codex says hi"}})
out({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}})
