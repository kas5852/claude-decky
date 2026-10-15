import asyncio

import decky

from claude_decky.auth import Auth
from claude_decky.chat import Chat
from claude_decky.env import Events
from claude_decky.pad import Pad
from claude_decky import screen
from claude_decky.settings import Settings
from claude_decky.voice import Voice


class App:
    def __init__(self):
        self.events = Events()
        self.settings = Settings()
        self.chat = Chat(self.events, self.settings)
        self.auth = Auth(self.events)
        self.voice = Voice(self.events, self.settings)
        self.pad = Pad(self.pad_down, self.pad_up)
        self.pad_shot = None
        self.pad_stopping = False
        self.chat.on_reply = self.replied
        self.voice.on_text = self.heard
        self.voice.on_ready_change = self.configure_pad

    def start(self):
        self.settings.load()
        self.chat.load()
        self.configure_pad()

    def configure_pad(self):
        if self.voice.state()["ready"]:
            self.pad.configure(self.settings["shortcut"])
        else:
            self.pad.configure("off")

    def notify(self, kind, title, body=""):
        self.events.emit("notify", {"kind": kind, "title": title, "body": body})

    def replied(self, text):
        self.events.emit("reply", text)

    def pad_down(self):
        if self.voice.phase == "recording":
            self.pad_stopping = True
            asyncio.get_running_loop().create_task(self.voice.stop())
            return
        if self.voice.phase in ("transcribing", "stopping") or self.chat.status == "working":
            self.notify("busy", "Claude is busy", "Wait for the current answer or press Stop")
            self.pad_stopping = True
            return
        self.pad_stopping = False
        loop = asyncio.get_running_loop()
        self.pad_shot = loop.create_task(screen.capture()) if self.settings["shortcut_screen"] else None
        loop.create_task(self.voice.start(origin="pad"))

    def pad_up(self, held):
        if self.pad_stopping:
            self.pad_stopping = False
            return
        if held:
            asyncio.get_running_loop().create_task(self.voice.stop())
        elif self.voice.phase == "recording":
            self.voice.tap = True
            self.voice.changed()

    async def heard(self, text, origin):
        shot = None
        if origin == "pad" and self.pad_shot is not None:
            try:
                shot = await self.pad_shot
            except Exception as error:
                decky.logger.warning("shortcut screenshot failed: %s", error)
            self.pad_shot = None
        result = await self.chat.send(text, via="voice", shot=shot)
        if result.get("ok"):
            self.notify("heard", "Asked Claude", text)
        else:
            self.notify("error", "Couldn't ask Claude", result.get("error", ""))

    def state(self):
        return {
            "chat": self.chat.state(),
            "voice": self.voice.state(),
            "auth": self.auth.state(),
            "settings": dict(self.settings.values),
            "padDevices": self.pad.describe(),
        }


app = App()


class Plugin:
    async def get_state(self) -> dict:
        return app.state()

    async def set_visible(self, visible: bool) -> dict:
        app.events.visible = bool(visible)
        return app.state() if visible else {}

    async def send(self, prompt: str) -> dict:
        return await app.chat.send(prompt)

    async def cancel(self) -> bool:
        return app.chat.cancel()

    async def new_chat(self) -> dict:
        return await app.chat.new_chat()

    async def capture_screen(self) -> dict:
        try:
            shot = await screen.capture()
        except Exception as error:
            return {"ok": False, "error": str(error)}
        app.chat.attach(shot)
        return {"ok": True, "thumb": shot.thumb}

    async def clear_attachment(self) -> bool:
        app.chat.detach()
        return True

    async def voice_start(self) -> dict:
        return await app.voice.start(origin="panel")

    async def voice_stop(self) -> dict:
        return await app.voice.stop()

    async def voice_tap(self) -> dict:
        if app.voice.phase != "recording":
            return {"ok": False, "error": "Not listening"}
        app.voice.tap = True
        app.voice.changed()
        return {"ok": True}

    async def voice_cancel(self) -> dict:
        return await app.voice.cancel()

    async def voice_download(self, name: str) -> dict:
        return await app.voice.fetch_model(name)

    async def voice_delete(self, name: str) -> dict:
        state = app.voice.delete_model(name)
        app.configure_pad()
        return state

    async def update_settings(self, patch: dict) -> dict:
        changed = app.settings.update(patch)
        if "shortcut" in changed or "voice_model" in changed:
            app.configure_pad()
        return app.state()

    async def auth_refresh(self) -> dict:
        return await app.auth.refresh()

    async def auth_login(self, console: bool) -> dict:
        return await app.auth.login(console=bool(console))

    async def auth_submit(self, code: str) -> dict:
        return app.auth.submit_code(code)

    async def auth_cancel(self) -> dict:
        return await app.auth.cancel()

    async def auth_logout(self) -> dict:
        return await app.auth.logout()

    async def install_claude(self) -> dict:
        return await app.auth.install()

    async def _main(self):
        app.start()
        decky.logger.info("Claude plugin ready, %d saved messages", len(app.chat.messages))

    async def _unload(self):
        app.pad.stop()
        app.chat.cancel()
        await app.voice.shutdown()
        await app.auth.shutdown()

    async def _uninstall(self):
        await Plugin._unload(self)
