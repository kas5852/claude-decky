import asyncio
import os

import decky

HOME = decky.DECKY_USER_HOME
USER = decky.DECKY_USER
PLUGIN_DIR = decky.DECKY_PLUGIN_DIR
SETTINGS_DIR = decky.DECKY_PLUGIN_SETTINGS_DIR
RUNTIME_DIR = decky.DECKY_PLUGIN_RUNTIME_DIR
LOCAL_BIN = os.path.join(HOME, ".local", "bin")
CLAUDE = os.path.join(LOCAL_BIN, "claude")
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin"


def runtime_path(*parts):
    path = os.path.join(RUNTIME_DIR, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def child_env(extra=None):
    uid = os.getuid()
    env = {
        "HOME": HOME,
        "USER": USER,
        "LOGNAME": USER,
        "SHELL": "/bin/bash",
        "PATH": f"{LOCAL_BIN}:{SYSTEM_PATH}",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
    }
    if extra:
        env.update(extra)
    return env


def find_program(name):
    for folder in (LOCAL_BIN, *SYSTEM_PATH.split(":")):
        candidate = os.path.join(folder, name)
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def lowered(args, enabled=True):
    nice = find_program("nice")
    if enabled and nice:
        return [nice, "-n", "10", *args]
    return list(args)


async def run(args, timeout=30, stdin=None, env=None, cwd=None):
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env or child_env(),
        cwd=cwd,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return 124, b"", b"timed out"
    return process.returncode, out, err


class Events:
    def __init__(self):
        self.visible = False
        self.tasks = set()

    def emit(self, name, *args):
        task = asyncio.get_running_loop().create_task(decky.emit(name, *args))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
