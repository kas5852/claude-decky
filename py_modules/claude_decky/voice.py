import array
import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import signal
import struct
import time

import decky

from .env import PLUGIN_DIR, child_env, find_program, lowered, run, runtime_path

RATE = 16000
CHUNK = RATE // 10 * 2
MIN_SECONDS = 0.4
MAX_SECONDS = 60
TAP_SILENCE = 1.3
TAP_NO_SPEECH = 7.0
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODELS = {
    "tiny.en": ("ggml-tiny.en-q5_1.bin", "c77c5766f1cef09b6b7d47f21b546cbddd4157886b3b5d6d4f709e91e66c7c2b", 32166155),
    "base.en": ("ggml-base.en-q5_1.bin", "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f", 59721011),
    "small.en": ("ggml-small.en-q5_1.bin", "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30", 190098681),
    "base": ("ggml-base-q5_1.bin", "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898", 59707625),
}
NOISE_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")


def whisper_binary():
    bundled = os.path.join(PLUGIN_DIR, "bin", "whisper-cli")
    if os.access(bundled, os.X_OK):
        return bundled
    return find_program("whisper-cli")


def model_file(name):
    return runtime_path("models", MODELS[name][0])


def wav_bytes(pcm):
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1, RATE, RATE * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


def chunk_level(data):
    samples = array.array("h")
    samples.frombytes(data[: len(data) - len(data) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def clean_transcript(text):
    text = NOISE_TAGS.sub(" ", text)
    return " ".join(text.split()).strip()


def audio_context(seconds):
    frames = math.ceil((seconds + 1.0) / 30 * 1500 / 64) * 64
    return max(384, min(1500, frames))


async def pipewire_objects():
    tool = find_program("pw-dump")
    if not tool:
        return []
    code, out, _ = await run([tool], timeout=10)
    if code != 0:
        return []
    try:
        return json.loads(out.decode())
    except ValueError:
        return []


def pick_source(objects):
    default_name = None
    sources = []
    for item in objects:
        info = item.get("info") or {}
        props = info.get("props") or {}
        if item.get("type", "").endswith("Metadata") and props.get("metadata.name") == "default":
            for entry in item.get("metadata") or []:
                if entry.get("key") == "default.audio.source":
                    value = entry.get("value")
                    if isinstance(value, dict):
                        default_name = value.get("name")
        if props.get("media.class") == "Audio/Source":
            sources.append(props)
    for props in sources:
        if default_name and props.get("node.name") == default_name:
            return props
    sources.sort(key=lambda props: -int(props.get("priority.session") or 0))
    return sources[0] if sources else None


def capture_cards(objects):
    cards = set()
    for item in objects:
        props = (item.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Audio/Source":
            continue
        for key in ("api.alsa.pcm.card", "alsa.card", "api.alsa.card"):
            if props.get(key) is not None:
                cards.add(str(props[key]))
                break
    return sorted(cards)


async def capture_switches(cards):
    amixer = find_program("amixer")
    found = []
    if not amixer:
        return found
    for card in cards:
        code, out, _ = await run([amixer, "-c", card, "cget", "name=Capture Switch"], timeout=5)
        if code != 0:
            continue
        values = re.search(r": values=([a-z,]+)", out.decode())
        if values:
            found.append((card, values.group(1)))
    return found


async def set_capture_switch(card, values):
    amixer = find_program("amixer")
    if amixer:
        await run([amixer, "-c", card, "-q", "cset", "name=Capture Switch", values], timeout=5)


class Voice:
    def __init__(self, events, settings):
        self.events = events
        self.settings = settings
        self.phase = "idle"
        self.error = ""
        self.source = ""
        self.process = None
        self.reader = None
        self.pcm = bytearray()
        self.started = 0.0
        self.tap = False
        self.speech = False
        self.quiet_since = 0.0
        self.noise = None
        self.restore = []
        self.stop_requested = False
        self.download = None
        self.download_task = None
        self.fetcher = None
        self.on_ready_change = None
        self.on_text = None
        self.origin = "panel"

    def model_ready(self, name=None):
        return os.path.exists(model_file(name or self.settings["voice_model"]))

    def state(self):
        installed = [name for name in MODELS if self.model_ready(name)]
        return {
            "phase": self.phase,
            "error": self.error,
            "engine": bool(whisper_binary()),
            "installed": installed,
            "ready": bool(whisper_binary()) and self.model_ready(),
            "download": self.download,
            "started": self.started if self.phase == "recording" else 0,
            "origin": self.origin,
            "tap": self.tap,
            "sizes": {name: MODELS[name][2] for name in MODELS},
        }

    def changed(self):
        self.events.emit("voice_state", self.state())

    def set_phase(self, phase, error=""):
        self.phase = phase
        self.error = error
        self.changed()

    async def start(self, origin="panel", tap=False):
        if self.phase in ("recording", "transcribing"):
            return {"ok": False, "error": "Already listening"}
        if not whisper_binary():
            return self.refuse("Speech engine missing from the plugin")
        if not self.model_ready():
            return self.refuse("Download a voice model in Settings first")
        recorder = find_program("pw-record")
        if not recorder:
            return self.refuse("pw-record not found")
        objects = await pipewire_objects()
        source = pick_source(objects)
        if not source:
            return self.refuse("No microphone found")
        self.restore = []
        for card, values in await capture_switches(capture_cards(objects)):
            if "off" in values:
                self.restore.append((card, values))
                await set_capture_switch(card, ",".join("on" for _ in values.split(",")))
        self.origin = origin
        self.tap = tap
        self.speech = False
        self.noise = None
        self.quiet_since = 0.0
        self.stop_requested = False
        self.pcm = bytearray()
        self.process = await asyncio.create_subprocess_exec(
            recorder, "--target", source["node.name"], "--raw", "--rate", str(RATE), "--channels", "1",
            "--format", "s16", "--latency", "100ms", "-P", "{ node.name = claude-decky-mic }", "-",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_env(),
            start_new_session=True,
        )
        self.started = time.time()
        self.reader = asyncio.get_running_loop().create_task(self.read(self.process))
        self.set_phase("recording")
        return {"ok": True}

    def refuse(self, message):
        self.set_phase("error", message)
        return {"ok": False, "error": message}

    async def read(self, process):
        while True:
            data = await process.stdout.read(CHUNK)
            if not data:
                break
            self.pcm += data
            seconds = len(self.pcm) / (RATE * 2)
            if seconds >= MAX_SECONDS:
                self.request_stop()
                break
            if self.tap:
                self.watch_silence(data, seconds)

    def watch_silence(self, data, seconds):
        level = chunk_level(data)
        if self.noise is None or seconds < 0.4:
            self.noise = level if self.noise is None else min(self.noise, level)
            return
        threshold = max(self.noise * 3.0, 250.0)
        if level > threshold:
            self.speech = True
            self.quiet_since = 0.0
            return
        if not self.speech:
            if seconds > TAP_NO_SPEECH:
                self.request_stop(send=False, reason="Didn't hear anything")
            return
        if not self.quiet_since:
            self.quiet_since = seconds
        elif seconds - self.quiet_since >= TAP_SILENCE:
            self.request_stop()

    def request_stop(self, send=True, reason=""):
        if not self.stop_requested:
            self.stop_requested = True
            asyncio.get_running_loop().create_task(self.stop(send=send, reason=reason))

    async def halt_recorder(self):
        process = self.process
        self.process = None
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if self.reader:
            try:
                await asyncio.wait_for(self.reader, 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self.reader = None
        for card, values in self.restore:
            await set_capture_switch(card, values)
        self.restore = []

    async def stop(self, send=True, reason=""):
        if self.phase != "recording":
            return {"ok": False, "error": "Not listening"}
        self.phase = "stopping"
        await self.halt_recorder()
        pcm = bytes(self.pcm)
        self.pcm = bytearray()
        seconds = len(pcm) / (RATE * 2)
        if not send:
            self.set_phase("idle", reason)
            return {"ok": True, "text": ""}
        if seconds < MIN_SECONDS:
            self.set_phase("idle", "Too short, hold a little longer")
            return {"ok": False, "error": self.error}
        samples = array.array("h")
        samples.frombytes(pcm)
        if max(samples) == 0 and min(samples) == 0:
            self.set_phase("error", "The microphone is sending silence, check it is not muted")
            return {"ok": False, "error": self.error}
        self.set_phase("transcribing")
        try:
            text = await self.transcribe(pcm, seconds)
        except Exception as error:
            decky.logger.exception("transcription failed")
            self.set_phase("error", f"Transcription failed: {error}")
            return {"ok": False, "error": self.error}
        if not text:
            self.set_phase("idle", "Didn't catch that")
            return {"ok": False, "error": self.error}
        self.set_phase("idle")
        if self.on_text:
            await self.on_text(text, self.origin)
        return {"ok": True, "text": text}

    async def cancel(self):
        if self.phase == "recording":
            return await self.stop(send=False)
        return {"ok": True}

    async def transcribe(self, pcm, seconds):
        wav = runtime_path("voice", "clip.wav")
        with open(wav, "wb") as handle:
            handle.write(wav_bytes(pcm))
        name = self.settings["voice_model"]
        threads = str(max(1, min(4, (os.cpu_count() or 4) // 2)))
        args = [
            whisper_binary(), "-m", model_file(name), "-t", threads, "-ac", str(audio_context(seconds)),
            "-nt", "-np", "-l", "en" if name.endswith(".en") else "auto", wav,
        ]
        try:
            code, out, err = await run(lowered(args, self.settings["low_priority"]), timeout=120)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(wav)
        if code != 0:
            lines = err.decode(errors="replace").strip().splitlines()
            raise RuntimeError(lines[-1] if lines else f"exit {code}")
        return clean_transcript(out.decode(errors="replace"))

    async def fetch_model(self, name):
        if name not in MODELS:
            return {"ok": False, "error": "Unknown model"}
        if self.download_task and not self.download_task.done():
            return {"ok": False, "error": "A download is already running"}
        self.download_task = asyncio.get_running_loop().create_task(self.download_model(name))
        return {"ok": True}

    async def download_model(self, name):
        filename, digest, size = MODELS[name]
        target = model_file(name)
        partial = target + ".part"
        curl = find_program("curl")
        self.download = {"model": name, "done": 0, "total": size, "error": ""}
        self.changed()
        try:
            if not curl:
                raise RuntimeError("curl not found")
            process = self.fetcher = await asyncio.create_subprocess_exec(
                *lowered([curl, "-fsSL", "--retry", "3", "-o", partial, MODEL_URL + filename]),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=child_env(),
            )
            waiter = asyncio.get_running_loop().create_task(process.wait())
            while not waiter.done():
                await asyncio.wait([waiter], timeout=1.0)
                try:
                    self.download["done"] = os.path.getsize(partial)
                except OSError:
                    pass
                self.changed()
            if waiter.result() != 0:
                raise RuntimeError((await process.stderr.read()).decode(errors="replace").strip() or "download failed")
            hasher = hashlib.sha256()
            with open(partial, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    hasher.update(block)
            if hasher.hexdigest() != digest:
                raise RuntimeError("Downloaded model is corrupted, try again")
            os.replace(partial, target)
            self.download = None
            if self.on_ready_change:
                self.on_ready_change()
        except Exception as error:
            decky.logger.exception("model download failed")
            try:
                os.unlink(partial)
            except OSError:
                pass
            self.download = {"model": name, "done": 0, "total": size, "error": str(error)}
        self.changed()

    def delete_model(self, name):
        if name in MODELS:
            try:
                os.unlink(model_file(name))
            except OSError:
                pass
        self.changed()
        return self.state()

    async def shutdown(self):
        if self.phase == "recording":
            await self.halt_recorder()
        if self.fetcher and self.fetcher.returncode is None:
            self.fetcher.kill()
        if self.download_task and not self.download_task.done():
            self.download_task.cancel()
