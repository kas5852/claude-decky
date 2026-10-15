import asyncio
import html
import os
import socket
from urllib.parse import parse_qs

import decky

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Decky sign-in</title>
<style>
body{{margin:0;font:17px/1.45 -apple-system,system-ui,sans-serif;background:#14161a;color:#e9e6df}}
main{{max-width:30rem;margin:0 auto;padding:1.5rem 1.1rem 3rem}}
h1{{font-size:1.35rem;margin:.2rem 0 1.2rem}}
.step{{background:#1f2228;border:1px solid #2c3038;border-radius:14px;padding:1rem;margin:0 0 1rem}}
.n{{display:inline-block;width:1.6rem;height:1.6rem;border-radius:50%;background:#d97757;color:#14161a;
text-align:center;font-weight:700;margin-right:.5rem}}
a.btn,button{{display:block;width:100%;box-sizing:border-box;margin-top:.8rem;padding:.85rem;border:0;border-radius:10px;
background:#d97757;color:#14161a;font:inherit;font-weight:700;text-align:center;text-decoration:none}}
textarea{{width:100%;box-sizing:border-box;margin-top:.8rem;min-height:5.5rem;padding:.7rem;border-radius:10px;
border:1px solid #3a3f49;background:#14161a;color:#e9e6df;font:15px ui-monospace,monospace}}
.note{{color:#a29d93;font-size:.9rem}}
.ok{{color:#8fd19e}}.bad{{color:#ff8a80}}
</style></head><body><main>
<h1>Sign in to {title} on your handheld</h1>
{body}
</main></body></html>"""

FORM = """<div class="step"><span class="n">1</span>{first}
<a class="btn" href="{go}" target="_blank" rel="noreferrer">{link}</a></div>
<div class="step"><span class="n">2</span>{second}
<form method="post" action="{post}"><textarea name="code" autocomplete="off" autocapitalize="off" spellcheck="false"
placeholder="{placeholder}"></textarea><button type="submit">Send to handheld</button></form></div>
<p class="note">{note}</p>"""
WORDING = {
    "code": {
        "first": "Sign in with your account. When it shows a code, copy it.",
        "link": "Open {title} sign-in",
        "second": "Paste the code here and send it to the handheld.",
        "placeholder": "Paste code",
    },
    "key": {
        "first": "Create an API key, then copy it.",
        "link": "Open the API key page",
        "second": "Paste the key here and send it to the handheld. It is only stored on the handheld.",
        "placeholder": "Paste API key",
    },
}


def lan_address():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class PhonePage:
    def __init__(self, submit):
        self.submit = submit
        self.server = None
        self.url = ""
        self.target = ""
        self.token = ""
        self.on_ready = None
        self.kind = "code"
        self.title = "Claude"

    def start(self, target, kind="code", title="Claude"):
        self.target = target
        self.kind = kind if kind in WORDING else "code"
        self.title = title
        asyncio.get_running_loop().create_task(self.open())

    async def open(self):
        if self.server:
            return
        address = lan_address()
        if not address or address.startswith("127."):
            return
        self.token = os.urandom(12).hex()
        try:
            self.server = await asyncio.start_server(self.handle, address, 0)
        except OSError as error:
            decky.logger.warning("phone page unavailable: %s", error)
            return
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://{address}:{port}/{self.token}"
        if self.on_ready:
            self.on_ready()

    def stop(self):
        if self.server:
            self.server.close()
        self.server = None
        self.url = ""
        self.token = ""

    async def handle(self, reader, writer):
        try:
            await asyncio.wait_for(self.respond(reader, writer), 15)
        except (asyncio.TimeoutError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    async def respond(self, reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        if len(request) > 16384:
            raise ValueError("request too large")
        lines = request.decode("latin-1").split("\r\n")
        method, path, _ = (lines[0].split(" ") + ["", "", ""])[:3]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        base = f"/{self.token}"
        if not self.token or not path.startswith(base):
            return self.reply(writer, 404, "<p>Not found</p>")
        if method == "GET" and path == base + "/go":
            return self.reply(writer, 302, "", {"Location": self.target})
        if method == "POST" and path == base:
            length = min(int(headers.get("content-length", "0") or 0), 8192)
            body = (await reader.readexactly(length)).decode(errors="replace") if length else ""
            code = (parse_qs(body).get("code") or [""])[0]
            result = self.submit(code)
            if result.get("ok"):
                return self.reply(writer, 200, '<div class="step ok">Sent. Look at your handheld, it should say you are signed in.</div>')
            note = html.escape(result.get("error", "Could not send the code"))
            return self.reply(writer, 200, f'<div class="step bad">{note}</div>' + self.form())
        if method == "GET" and path in (base, base + "/"):
            return self.reply(writer, 200, self.form())
        return self.reply(writer, 404, "<p>Not found</p>")

    def form(self):
        base = f"/{self.token}"
        title = html.escape(self.title)
        wording = {key: value.format(title=title) for key, value in WORDING[self.kind].items()}
        return FORM.format(go=base + "/go", post=base, note="This page only works while the handheld shows the sign-in screen.", **wording)

    def reply(self, writer, status, body, headers=None):
        text = PAGE.format(body=body, title=html.escape(self.title)).encode() if body else b""
        reason = {200: "OK", 302: "Found", 404: "Not Found"}[status]
        head = [f"HTTP/1.1 {status} {reason}", "Content-Type: text/html; charset=utf-8",
                f"Content-Length: {len(text)}", "Cache-Control: no-store", "Referrer-Policy: no-referrer",
                "Connection: close"]
        for key, value in (headers or {}).items():
            head.append(f"{key}: {value}")
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + text)
