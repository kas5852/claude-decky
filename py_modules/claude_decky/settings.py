import json
import os

from .env import SETTINGS_DIR
from .providers import PROVIDERS

SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
SHORTCUTS = ("off", "l3_r3", "view_menu", "lb_rb_y")
VOICE_MODELS = ("tiny.en", "base.en", "small.en", "base")
DEFAULTS = {
    "provider": "claude",
    "model": "",
    "codex_model": "",
    "gemini_model": "",
    "workdir": "",
    "voice_model": "base.en",
    "shortcut": "l3_r3",
    "shortcut_screen": True,
    "allow_tools": True,
    "low_priority": True,
}
CHOICES = {
    "provider": tuple(PROVIDERS),
    **{provider.model_key: tuple(provider.models) for provider in PROVIDERS.values()},
    "voice_model": VOICE_MODELS,
    "shortcut": SHORTCUTS,
}


class Settings:
    def __init__(self):
        self.values = dict(DEFAULTS)

    def load(self):
        try:
            with open(SETTINGS_FILE) as handle:
                saved = json.load(handle)
        except (OSError, ValueError):
            saved = {}
        self.values = dict(DEFAULTS)
        self.apply(saved)

    def apply(self, patch):
        changed = []
        for key, value in (patch or {}).items():
            if key not in DEFAULTS or type(value) is not type(DEFAULTS[key]):
                continue
            if key in CHOICES and value not in CHOICES[key]:
                continue
            if self.values[key] != value:
                self.values[key] = value
                changed.append(key)
        return changed

    def update(self, patch):
        changed = self.apply(patch)
        if changed:
            self.save()
        return changed

    def save(self):
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        temporary = SETTINGS_FILE + ".tmp"
        with open(temporary, "w") as handle:
            json.dump(self.values, handle, indent=1)
        os.replace(temporary, SETTINGS_FILE)

    def __getitem__(self, key):
        return self.values[key]
