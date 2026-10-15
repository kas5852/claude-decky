import logging
import os

DECKY_USER = "deck"
DECKY_USER_HOME = "/home/deck"
DECKY_PLUGIN_SETTINGS_DIR = os.environ["HARNESS_SETTINGS"]
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("harness")
emitted = []


async def emit(event, *args):
    emitted.append((event, args))
