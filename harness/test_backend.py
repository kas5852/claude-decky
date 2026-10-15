import asyncio
import base64
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse

MODE = sys.argv[1] if len(sys.argv) > 1 else "fake"
ONLY = set(sys.argv[2:])
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORK = tempfile.mkdtemp(prefix="claude-decky-test-")

if MODE == "fake":
    HOME = os.path.join(WORK, "home")
    os.makedirs(os.path.join(HOME, ".local", "bin"))
    os.makedirs(os.path.join(HOME, ".claude"))
    os.symlink(os.path.join(HERE, "fake_claude.py"), os.path.join(HOME, ".local", "bin", "claude"))
else:
    HOME = os.path.expanduser("~")
os.environ.update({
    "HARNESS_HOME": HOME,
    "HARNESS_PLUGIN_DIR": os.environ.get("HARNESS_PLUGIN_DIR", ROOT),
    "HARNESS_SETTINGS": os.path.join(WORK, "settings"),
    "HARNESS_RUNTIME": os.path.join(WORK, "runtime"),
})
if MODE == "live" and os.environ.get("HARNESS_MODELS"):
    models = os.path.join(WORK, "runtime", "models")
    os.makedirs(models)
    for name in os.listdir(os.environ["HARNESS_MODELS"]):
        if name.endswith(".bin"):
            os.symlink(os.path.join(os.environ["HARNESS_MODELS"], name), os.path.join(models, name))
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "py_modules")]

import decky
import main
from claude_decky.pad import Pad
from claude_decky.screen import Shot

app = main.app
plugin = main.Plugin()
TESTS = []


def test(mode):
    def register(function):
        TESTS.append((mode, function))
        return function
    return register


async def until(condition, timeout=10.0, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(step)
    raise AssertionError(f"timed out waiting for {condition.__doc__ or condition}")


def emitted(name):
    return [args for event, args in decky.emitted if event == name]


def calls():
    with open(os.path.join(HOME, "calls.jsonl")) as handle:
        return [json.loads(line) for line in handle]


def roles():
    return [(message["role"], message["text"]) for message in app.chat.messages]


async def idle():
    await until(lambda: app.chat.status != "working", timeout=120)


@test("fake")
async def chat_streams_and_resumes():
    app.events.visible = True
    decky.emitted.clear()
    result = await plugin.send("hi")
    assert result == {"ok": True}, result
    assert app.chat.status == "working"
    await idle()
    assert app.chat.status == "idle", app.chat.error
    assert roles() == [("user", "hi"), ("assistant", "Hello there, **friend**")], roles()
    partials = emitted("chat_partial")
    assert 1 <= len(partials) <= 4, partials
    assert partials[-1][0] in ("Hello there, ", "Hello there, **friend**"), partials
    assert emitted("reply") == [("Hello there, **friend**",)]
    assert emitted("chat_state")[-1][0]["status"] == "idle"
    assert "--resume" not in calls()[-1]["args"]
    await plugin.send("again")
    await idle()
    args = calls()[-1]["args"]
    assert args[args.index("--resume") + 1] == "sess-1", args
    assert app.chat.command()[0].endswith("nice"), app.chat.command()
    saved = json.load(open(os.path.join(os.environ["HARNESS_SETTINGS"], "chat.json")))
    assert saved["session_id"] == "sess-1" and len(saved["messages"]) == 4


@test("fake")
async def tool_steps_are_listed():
    await plugin.send("use a tool")
    await idle()
    assert ("tool", "Bash: cat /sys/class/power_supply/BAT0/capacity") in roles(), roles()


@test("fake")
async def hidden_panel_gets_no_stream_events():
    app.events.visible = False
    decky.emitted.clear()
    await plugin.send("quiet")
    await idle()
    names = {event for event, _ in decky.emitted}
    assert names == {"reply"}, names
    app.events.visible = True


@test("fake")
async def screenshot_goes_as_image_block():
    image = os.path.join(WORK, "shot.jpg")
    with open(image, "wb") as handle:
        handle.write(b"\xff\xd8fakejpeg\xff\xd9")
    app.chat.attach(Shot(image, "image/jpeg", "data:image/jpeg;base64,AAAA"))
    assert app.chat.state()["attachment"] == {"thumb": "data:image/jpeg;base64,AAAA"}
    await plugin.send("what is this")
    await idle()
    content = json.loads(calls()[-1]["stdin"])["message"]["content"]
    assert content[0]["type"] == "image"
    assert base64.b64decode(content[0]["source"]["data"]) == b"\xff\xd8fakejpeg\xff\xd9"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "what is this"}
    assert app.chat.state()["attachment"] is None
    user = [message for message in app.chat.messages if message["role"] == "user"][-1]
    assert user.get("image") is True


@test("fake")
async def stop_kills_the_run():
    await plugin.send("please sleep")
    await until(lambda: app.chat.process is not None)
    await asyncio.sleep(0.5)
    pid = app.chat.process.pid
    assert await plugin.cancel() is True
    await idle()
    assert roles()[-1] == ("error", "Stopped"), roles()[-1]
    await asyncio.sleep(0.2)
    try:
        os.kill(pid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive


@test("fake")
async def auth_errors_flag_sign_in():
    await plugin.send("fail now")
    await idle()
    state = app.chat.state()
    assert state["status"] == "error" and state["authNeeded"] is True, state


@test("fake")
async def new_chat_clears_everything():
    state = await plugin.new_chat()
    assert state["messages"] == [] and state["resumable"] is False
    saved = json.load(open(os.path.join(os.environ["HARNESS_SETTINGS"], "chat.json")))
    assert saved == {"session_id": None, "messages": []}


@test("fake")
async def settings_validate_and_persist():
    state = await plugin.update_settings({"model": "opus", "shortcut": "bogus", "low_priority": "yes", "nope": 1})
    assert state["settings"]["model"] == "opus"
    assert state["settings"]["shortcut"] == "l3_r3"
    assert state["settings"]["low_priority"] is True
    saved = json.load(open(os.path.join(os.environ["HARNESS_SETTINGS"], "settings.json")))
    assert saved["model"] == "opus" and "nope" not in saved
    await plugin.update_settings({"model": ""})


def fetch(url, method="GET", body=None):
    parsed = urllib.parse.urlparse(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
    connection.request(method, parsed.path, body=body, headers=headers)
    response = connection.getresponse()
    return response.status, dict(response.getheaders()), response.read().decode()


@test("fake")
async def sign_in_with_code_typed_on_device():
    status = app.auth.quick_status()
    assert status["installed"] and not status["loggedIn"], status
    await plugin.auth_login(False)
    await until(lambda: app.auth.phase == "waiting")
    assert app.auth.url == "https://claude.com/cai/oauth/authorize?code=true&client_id=x&state=abc", app.auth.url
    result = await plugin.auth_submit("  wrong code ")
    assert result == {"ok": True}
    await until(lambda: app.auth.phase == "failed")
    assert app.auth.error == "Login failed: Request failed with status code 400", app.auth.error
    assert not app.auth.quick_status()["loggedIn"]


@test("fake")
async def sign_in_through_phone_page():
    await plugin.auth_login(False)
    await until(lambda: app.auth.state()["phoneUrl"] != "")
    url = app.auth.state()["phoneUrl"]
    code, _, page = await asyncio.to_thread(fetch, url)
    assert code == 200 and "Send to handheld" in page
    code, headers, _ = await asyncio.to_thread(fetch, url + "/go")
    assert code == 302 and headers["Location"] == app.auth.url, headers
    code, _, _ = await asyncio.to_thread(fetch, url.rsplit("/", 1)[0] + "/wrongtoken")
    assert code == 404
    code, _, page = await asyncio.to_thread(fetch, url, "POST", "code=good%23state")
    assert code == 200 and "Sent." in page, page
    await until(lambda: app.auth.phase == "done")
    status = app.auth.state()["status"]
    assert status["loggedIn"] and status["email"] == "fake@example.com", status
    assert app.auth.state()["phoneUrl"] == ""
    try:
        await asyncio.to_thread(fetch, url)
        closed = False
    except OSError:
        closed = True
    assert closed


@test("fake")
async def cancel_sign_in_stops_everything():
    await plugin.auth_login(False)
    await until(lambda: app.auth.phase == "waiting" and app.auth.state()["phoneUrl"])
    process = app.auth.process
    await plugin.auth_cancel()
    assert app.auth.phase == "idle" and app.auth.process is None and app.auth.master is None
    assert process.returncode is not None


@test("fake")
async def logout_removes_stored_tokens():
    settings_file = os.path.join(HOME, ".claude", "settings.json")
    original = {"permissions": {"defaultMode": "x"}, "env": {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "OTHER": "1"}}
    with open(settings_file, "w") as handle:
        json.dump(original, handle)
    app.auth.forget()
    assert app.auth.quick_status()["method"] == "CLAUDE_CODE_OAUTH_TOKEN"
    state = await plugin.auth_logout()
    assert not state["status"]["loggedIn"], state
    assert json.load(open(settings_file)) == {"permissions": {"defaultMode": "x"}, "env": {"OTHER": "1"}}
    assert json.load(open(settings_file + ".claude-decky-backup")) == original
    assert oct(os.stat(settings_file).st_mode & 0o777) == "0o600"


@test("live")
async def live_chat_round_trip():
    await plugin.new_chat()
    await plugin.send("Reply with exactly the word: pong")
    await idle()
    assert app.chat.status == "idle", app.chat.error
    assert "pong" in app.chat.last_reply().lower(), roles()


@test("live")
async def live_screen_capture_and_question():
    result = await plugin.capture_screen()
    assert result["ok"], result
    assert result["thumb"].startswith("data:image/jpeg;base64,")
    path = app.chat.attachment.path
    assert path.endswith(".jpg") and os.path.getsize(path) > 10000
    await plugin.send("In six words or fewer, what screen or app is shown in the image?")
    await idle()
    assert app.chat.status == "idle" and app.chat.last_reply(), roles()
    print("   screen answer:", app.chat.last_reply())


def pcm_of(path):
    with open(path, "rb") as handle:
        data = handle.read()
    return data[data.index(b"data") + 8:]


@test("live")
async def live_transcription():
    heard = []

    async def collect(text, origin):
        heard.append((text, origin))

    app.voice.on_text = collect
    assert app.voice.state()["ready"], app.voice.state()
    app.voice.pcm = bytearray(pcm_of(os.environ["HARNESS_WAV"]))
    app.voice.phase = "recording"
    app.voice.origin = "pad"
    started = time.monotonic()
    result = await app.voice.stop()
    print(f"   transcribed in {time.monotonic() - started:.2f}s: {result.get('text')}")
    assert result["ok"] and "stuttering" in result["text"].lower(), result
    assert heard == [(result["text"], "pad")]
    assert app.voice.phase == "idle"
    app.voice.on_text = app.heard


def capture_switch():
    output = subprocess.run(["amixer", "-c", "0", "cget", "name=Capture Switch"], capture_output=True, text=True).stdout
    return output.strip().splitlines()[-1]


@test("live")
async def live_microphone_recording_restores_mute():
    before = capture_switch()
    heard = []

    async def collect(text, origin):
        heard.append(text)

    app.voice.on_text = collect
    result = await plugin.voice_start()
    assert result == {"ok": True}, result
    await asyncio.sleep(0.5)
    during = capture_switch()
    await asyncio.sleep(1.5)
    samples = len(app.voice.pcm) // 2
    peak = max(abs(value) for value in memoryview(bytes(app.voice.pcm)).cast("h")) if samples else 0
    await plugin.voice_cancel()
    after = capture_switch()
    app.voice.on_text = app.heard
    print(f"   switch before={before} during={during} after={after} samples={samples} peak={peak}")
    assert "on" in during and after == before
    assert samples > 16000 * 1.2 and peak > 0
    assert app.voice.phase == "idle" and app.voice.process is None


@test("live")
async def live_shortcut_wakes_only_on_chord():
    downs, ups = [], []
    pad = Pad(lambda: downs.append(time.monotonic()), lambda held: ups.append(held))
    reads = []
    original = pad.read

    def counting(fd):
        reads.append(fd)
        original(fd)

    pad.read = counting
    helper = subprocess.Popen(["sudo", "-n", sys.executable, os.path.join(HERE, "virtual_pad.py")],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def ask(command):
        helper.stdin.write(command + "\n")
        helper.stdin.flush()
        return helper.stdout.readline().strip()

    try:
        assert helper.stdout.readline().strip() == "ready"
        pad.configure("l3_r3")
        await until(lambda: "Claude Decky Test Pad" in pad.describe(), timeout=8)
        await asyncio.sleep(2.5)
        print("   listening on:", pad.describe())
        reads.clear()
        await asyncio.to_thread(ask, "axes 3000")
        await asyncio.to_thread(ask, "press 130 131")
        await asyncio.to_thread(ask, "release 130 131")
        await asyncio.sleep(0.3)
        assert reads == [], f"woke {len(reads)} times for sticks and other buttons"
        await asyncio.to_thread(ask, "press 13d")
        await asyncio.sleep(0.1)
        assert downs == []
        await asyncio.to_thread(ask, "press 13e")
        await until(lambda: len(downs) == 1)
        await asyncio.sleep(0.6)
        await asyncio.to_thread(ask, "release 13d 13e")
        await until(lambda: ups == [True])
        await asyncio.to_thread(ask, "press 13d 13e")
        await until(lambda: len(downs) == 2)
        await asyncio.to_thread(ask, "release 13d 13e")
        await until(lambda: ups == [True, False])
        print(f"   wakeups for 3000 stick events + 2 chords: {len(reads)}")
        assert len(reads) <= 6
        helper.stdin.write("quit\n")
        helper.stdin.flush()
        helper.wait(5)
        await until(lambda: "Claude Decky Test Pad" not in pad.describe(), timeout=5)
    finally:
        pad.stop()
        if helper.poll() is None:
            helper.kill()


async def run_all():
    app.start()
    failures = 0
    for mode, function in TESTS:
        if mode != MODE or (ONLY and function.__name__ not in ONLY):
            continue
        started = time.monotonic()
        try:
            await function()
            print(f"PASS {function.__name__} ({time.monotonic() - started:.1f}s)")
        except Exception:
            failures += 1
            print(f"FAIL {function.__name__}")
            traceback.print_exc()
    await plugin._unload()
    print("ALL PASSED" if not failures else f"{failures} FAILED")
    return failures


sys.exit(1 if asyncio.run(run_all()) else 0)
