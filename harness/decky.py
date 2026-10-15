import logging
import os

DECKY_USER = os.environ.get("HARNESS_USER", "deck")
DECKY_USER_HOME = os.environ["HARNESS_HOME"]
DECKY_PLUGIN_DIR = os.environ["HARNESS_PLUGIN_DIR"]
DECKY_PLUGIN_SETTINGS_DIR = os.environ["HARNESS_SETTINGS"]
DECKY_PLUGIN_RUNTIME_DIR = os.environ["HARNESS_RUNTIME"]
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("harness")
emitted = []


async def emit(event, *args):
    emitted.append((event, args))
