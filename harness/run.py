import asyncio
import json
import sys

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import decky
import main


async def wait_idle(plugin):
    while True:
        state = await plugin.get_state(plugin)
        if state["status"] != "working":
            return state
        await asyncio.sleep(0.5)


async def go():
    plugin = main.Plugin
    await plugin._main(plugin)
    print(await plugin.send(plugin, "reply with just: ok"))
    seen_partial = False
    while (await plugin.get_state(plugin))["status"] == "working":
        seen_partial |= bool((await plugin.get_state(plugin))["partial"])
        await asyncio.sleep(0.2)
    first = await wait_idle(plugin)
    print("FIRST", json.dumps(first), "partial_seen", seen_partial)
    print(await plugin.send(plugin, "What exact words did I ask you to reply with? Answer in under 10 words."))
    second = await wait_idle(plugin)
    print("SECOND", json.dumps(second))
    print(await plugin.send(plugin, "Run `cat /sys/class/power_supply/BAT*/capacity` and tell me the number."))
    await asyncio.sleep(3)
    print("CANCEL", await plugin.cancel(plugin))
    third = await wait_idle(plugin)
    print("THIRD", json.dumps(third["messages"][-2:]), third["status"])
    print("EMITTED", decky.emitted)
    print("FILE", open(main.CHAT_FILE).read()[:300])
    print("NEW", await plugin.new_chat(plugin))


asyncio.run(go())
