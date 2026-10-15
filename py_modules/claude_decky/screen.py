import asyncio
import base64
import os
import time

from .env import child_env, find_program, lowered, run, runtime_path

KEEP_SHOTS = 12
PNG_END = b"IEND\xaeB`\x82"


def gamescope_env():
    env = child_env()
    runtime = env["XDG_RUNTIME_DIR"]
    try:
        sockets = sorted(name for name in os.listdir(runtime) if name.startswith("gamescope-") and name[10:].isdigit())
    except OSError:
        sockets = []
    display = sockets[0] if sockets else "gamescope-0"
    env["WAYLAND_DISPLAY"] = display
    env["GAMESCOPE_WAYLAND_DISPLAY"] = display
    return env


def prune(folder):
    shots = sorted(
        (entry for entry in os.scandir(folder) if entry.is_file()),
        key=lambda entry: entry.stat().st_mtime,
    )
    for entry in shots[:-KEEP_SHOTS * 2]:
        try:
            os.unlink(entry.path)
        except OSError:
            pass


async def wait_for_png(path, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path, "rb") as handle:
                handle.seek(-len(PNG_END), os.SEEK_END)
                if handle.read() == PNG_END:
                    return True
        except OSError:
            pass
        await asyncio.sleep(0.05)
    return False


class Shot:
    def __init__(self, path, media_type, thumb):
        self.path = path
        self.media_type = media_type
        self.thumb = thumb

    def encoded(self):
        with open(self.path, "rb") as handle:
            return base64.b64encode(handle.read()).decode()


async def capture():
    control = find_program("gamescopectl")
    if not control:
        raise RuntimeError("gamescopectl not found, screen capture needs SteamOS game mode")
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    png = runtime_path("shots", f"{stamp}.png")
    code, _, err = await run([control, "screenshot", png], timeout=5, env=gamescope_env())
    if code != 0 or not await wait_for_png(png):
        raise RuntimeError("Screen capture failed: " + (err.decode(errors="replace").strip() or "no image written"))
    ffmpeg = find_program("ffmpeg")
    path, media_type, thumb = png, "image/png", ""
    if ffmpeg:
        jpeg = png[:-4] + ".jpg"
        small = png[:-4] + ".thumb.jpg"
        code, _, _ = await run(
            lowered([ffmpeg, "-loglevel", "error", "-y", "-i", png,
                     "-vf", "scale='min(1280,iw)':-2", "-q:v", "4", jpeg,
                     "-vf", "scale=288:-2", "-q:v", "7", small]),
            timeout=15,
        )
        if code == 0 and os.path.exists(jpeg):
            os.unlink(png)
            path, media_type = jpeg, "image/jpeg"
            with open(small, "rb") as handle:
                thumb = "data:image/jpeg;base64," + base64.b64encode(handle.read()).decode()
    prune(os.path.dirname(png))
    return Shot(path, media_type, thumb)
