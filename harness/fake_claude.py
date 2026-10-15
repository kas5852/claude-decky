#!/usr/bin/env python3
import json
import os
import sys
import time

HOME = os.environ["HOME"]
MARK = os.path.join(HOME, ".fake_logged_in")
args = sys.argv[1:]


def out(event):
    print(json.dumps(event), flush=True)


if args[:2] == ["auth", "status"]:
    logged = os.path.exists(MARK)
    print(json.dumps({"loggedIn": logged, "authMethod": "claude.ai" if logged else "none", "email": "fake@example.com" if logged else None}))
    sys.exit(0 if logged else 1)
if args[:2] == ["auth", "logout"]:
    if os.path.exists(MARK):
        os.unlink(MARK)
    print("Successfully logged out")
    sys.exit(0)
if args[:2] == ["auth", "login"]:
    print("Opening browser to sign in…\r")
    url = "https://claude.com/cai/oauth/authorize?code=true&client_id=x&state=abc"
    print(f"If the browser didn't open, visit: \x1b]8;;{url}\x07\x1b[94m{url}\x1b[39m\x1b]8;;\x07\r")
    sys.stdout.write("Paste code here if prompted > ")
    sys.stdout.flush()
    code = sys.stdin.readline().strip()
    if code == "good#state":
        open(MARK, "w").close()
        print("\r\nLogin successful.\r")
        sys.exit(0)
    print("\r\nLogin failed: Request failed with status code 400\r")
    sys.exit(1)

with open(os.path.join(HOME, "calls.jsonl"), "a") as log:
    log.write(json.dumps({"args": args, "cwd": os.getcwd(), "stdin": sys.stdin.readline()}) + "\n")
with open(os.path.join(HOME, "calls.jsonl")) as log:
    last = json.loads(log.read().splitlines()[-1])
message = json.loads(last["stdin"])
text = [block for block in message["message"]["content"] if block["type"] == "text"][0]["text"]
session = "sess-1"
if "--resume" in args:
    session = args[args.index("--resume") + 1]
out({"type": "system", "subtype": "init", "session_id": session})
if "fail" in text:
    out({"type": "result", "is_error": True, "result": "API Error: 401 Invalid bearer token", "session_id": session})
    sys.exit(1)
if "sleep" in text:
    time.sleep(60)
out({"type": "stream_event", "event": {"type": "message_start"}})
for word in ["Hello", " there", ", ", "**friend**"]:
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": word}}})
    time.sleep(0.15)
if "tool" in text:
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "cat /sys/class/power_supply/BAT0/capacity"}}]}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello there, **friend**"}]}})
out({"type": "result", "is_error": False, "result": "Hello there, **friend**", "session_id": session})
