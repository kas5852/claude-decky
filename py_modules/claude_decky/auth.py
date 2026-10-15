import asyncio
import contextlib
import fcntl
import os
import re
import signal
import struct
import termios
import time

from .env import HOME, child_env, find_program, run
from .phone import PhonePage

ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-Za-z]|\r")
LOGIN_TIMEOUT = 15 * 60
API_KEY_FLOW = "api_key"


def strip_terminal(text):
    return ESCAPES.sub("", text)


class Auth:
    def __init__(self, events, settings, providers):
        self.events = events
        self.settings = settings
        self.providers = providers
        self.phase = "idle"
        self.flow = ""
        self.prompt = None
        self.error = ""
        self.statuses = {}
        self.checked_at = 0.0
        self.process = None
        self.master = None
        self.output = ""
        self.timeout = None
        self.phone = PhonePage(self.submit_code)
        self.phone.on_ready = self.changed
        self.install_log = ""
        self.active = None
        self.login_started = 0.0

    @property
    def provider(self):
        return self.providers[self.settings["provider"]]

    def installed(self):
        return self.provider.installed()

    def quick_status(self):
        provider = self.provider
        if not provider.installed():
            return {"installed": False, "loggedIn": False, "method": "none"}
        if provider.live_status:
            return provider.quick_status()
        return self.statuses.get(provider.id) or provider.quick_status()

    async def refresh(self):
        provider = self.provider
        self.statuses[provider.id] = await provider.status()
        self.checked_at = time.time()
        return self.state()

    def forget(self):
        self.statuses.pop(self.provider.id, None)

    def state(self):
        prompt = self.prompt
        return {
            "provider": self.provider.id,
            "status": self.quick_status(),
            "phase": self.phase,
            "flow": self.flow,
            "url": prompt.url if prompt else "",
            "userCode": prompt.user_code if prompt else "",
            "wantsCode": bool(prompt and prompt.wants_code),
            "phoneUrl": self.phone.url if self.phase == "waiting" else "",
            "error": self.error,
            "installLog": self.install_log[-600:],
        }

    def changed(self):
        self.events.emit("auth_state", self.state())

    async def login(self, flow=""):
        provider = self.provider
        if not provider.installed():
            return self.fail(f"Install {provider.label} first")
        flow = flow if flow in provider.login_flows else next(iter(provider.login_flows))
        await self.cancel()
        self.active = provider
        self.flow = flow
        self.error = ""
        self.prompt = None
        self.output = ""
        if flow == API_KEY_FLOW:
            self.phase = "waiting"
            self.prompt = provider.api_key_prompt()
            self.phone.start(self.prompt.url, kind="key", title=provider.label)
            self.timeout = asyncio.get_running_loop().call_later(LOGIN_TIMEOUT, self.expire)
            self.changed()
            return self.state()
        self.phase = "starting"
        self.login_started = time.time()
        self.changed()
        provider.before_login(flow)
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 4000, 0, 0))
        env = {"TERM": "xterm-256color", "BROWSER": "/bin/false", "COLUMNS": "4000"}
        env.update(provider.login_env(flow))
        try:
            self.process = await asyncio.create_subprocess_exec(
                *provider.login_args(flow),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=child_env(env),
                cwd=HOME,
                start_new_session=True,
            )
        finally:
            os.close(slave)
        self.master = master
        os.set_blocking(master, False)
        loop = asyncio.get_running_loop()
        loop.add_reader(master, self.on_output)
        loop.create_task(self.watch(self.process))
        self.timeout = loop.call_later(LOGIN_TIMEOUT, self.expire)
        return self.state()

    def on_output(self):
        try:
            chunk = os.read(self.master, 65536)
        except BlockingIOError:
            return
        except OSError:
            chunk = b""
        if not chunk:
            self.close_master()
            return
        self.output = (self.output + strip_terminal(chunk.decode(errors="replace")))[-20000:]
        if self.check_verdict():
            return
        if self.prompt is None and self.active is not None:
            prompt = self.active.scan_login(self.output)
            if prompt:
                self.prompt = prompt
                self.phase = "waiting"
                if prompt.wants_code:
                    self.phone.start(prompt.url, kind="code", title=self.active.label)
                self.changed()

    async def watch(self, process):
        code = await process.wait()
        if process is not self.process:
            return
        await asyncio.sleep(0.1)
        if process is not self.process:
            return
        self.close_master()
        self.process = None
        self.stop_timer()
        self.phone.stop()
        self.prompt = None
        if code == 0:
            self.forget()
            await self.refresh()
            self.phase = "done"
        else:
            lines = [line.strip() for line in self.output.splitlines() if line.strip()]
            failure = next((line for line in reversed(lines) if "fail" in line.lower() or "error" in line.lower()), "")
            self.phase = "failed"
            self.error = failure or f"Sign-in exited with code {code}"
        self.changed()

    def submit_code(self, code):
        code = "".join((code or "").split())
        if not code:
            return {"ok": False, "error": "Enter the code or key first"}
        if self.phase != "waiting" or self.active is None:
            return {"ok": False, "error": "No sign-in is waiting"}
        if self.flow == API_KEY_FLOW:
            self.phase = "checking"
            self.changed()
            asyncio.get_running_loop().create_task(self.store_key(self.active, code))
            return {"ok": True}
        if self.master is None or not (self.prompt and self.prompt.wants_code):
            return {"ok": False, "error": "This sign-in doesn't take a code here"}
        self.output = ""
        self.error = ""
        os.write(self.master, self.active.code_input(code))
        self.phase = "checking"
        self.changed()
        if not self.active.login_exits:
            asyncio.get_running_loop().call_later(1, self.poll_verdict)
        return {"ok": True}

    def check_verdict(self):
        if self.phase != "checking" or self.active is None or self.active.login_exits:
            return False
        verdict = self.active.login_verdict(self.output, self.login_started)
        if verdict == "done":
            self.phase = "finishing"
            asyncio.get_running_loop().create_task(self.complete())
            return True
        if verdict:
            self.error = verdict
            self.prompt = None
            self.phase = "starting"
            self.changed()
        return False

    def poll_verdict(self):
        if self.phase == "checking" and self.master is not None:
            self.check_verdict()
            asyncio.get_running_loop().call_later(1, self.poll_verdict)

    async def complete(self):
        provider = self.active
        process = self.process
        self.process = None
        self.stop_timer()
        self.phone.stop()
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
        self.close_master()
        self.prompt = None
        self.active = None
        self.statuses.pop(provider.id, None)
        await self.refresh()
        self.phase = "done"
        self.error = ""
        self.changed()

    async def store_key(self, provider, key):
        result = await provider.save_api_key(key)
        self.stop_timer()
        self.phone.stop()
        self.prompt = None
        if result.get("ok"):
            self.statuses.pop(provider.id, None)
            await self.refresh()
            self.phase = "done"
        else:
            self.phase = "failed"
            self.error = result.get("error", "Could not save the key")
        self.changed()

    def close_master(self):
        if self.master is not None:
            try:
                asyncio.get_running_loop().remove_reader(self.master)
            except RuntimeError:
                pass
            os.close(self.master)
            self.master = None

    def stop_timer(self):
        if self.timeout is not None:
            self.timeout.cancel()
            self.timeout = None

    def expire(self):
        self.timeout = None
        asyncio.get_running_loop().create_task(self.cancel("Sign-in timed out, start again"))

    async def cancel(self, reason=""):
        process = self.process
        self.process = None
        self.phone.stop()
        self.stop_timer()
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
        self.close_master()
        self.prompt = None
        self.active = None
        self.phase = "failed" if reason else "idle"
        self.error = reason
        self.changed()
        return self.state()

    def fail(self, message):
        self.phase = "failed"
        self.error = message
        self.changed()
        return self.state()

    async def logout(self):
        await self.cancel()
        await self.provider.logout()
        self.forget()
        self.phase = "idle"
        self.error = ""
        await self.refresh()
        self.changed()
        return self.state()

    async def install(self):
        provider = self.provider
        curl = find_program("curl")
        bash = find_program("bash")
        if not curl or not bash:
            return self.fail(f"curl and bash are needed to install {provider.label}")
        self.phase = "installing"
        self.error = ""
        self.install_log = ""
        self.changed()
        code, out, err = await run(
            [bash, "-c", "set -o pipefail; " + provider.install_script()],
            timeout=900,
            cwd=HOME,
        )
        self.install_log = strip_terminal((out + err).decode(errors="replace"))
        self.forget()
        if code != 0 or not provider.installed():
            self.phase = "failed"
            self.error = "Install failed, see the log below"
        else:
            provider.after_install()
            self.phase = "idle"
        await self.refresh()
        self.changed()
        return self.state()

    async def switched(self):
        await self.cancel()
        self.install_log = ""
        if self.provider.id not in self.statuses:
            await self.refresh()
        self.changed()

    async def shutdown(self):
        await self.cancel()
