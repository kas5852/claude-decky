import asyncio
import ctypes
import fcntl
import os
import struct
import time

import decky

EV_SYN = 0
EV_KEY = 1
KEY_CNT = 0x300
BTN_SOUTH = 0x130
BTN_TL = 0x136
BTN_TR = 0x137
BTN_NORTH = 0x134
BTN_SELECT = 0x13A
BTN_START = 0x13B
BTN_THUMBL = 0x13D
BTN_THUMBR = 0x13E
SHORTCUTS = {
    "l3_r3": (BTN_THUMBL, BTN_THUMBR),
    "view_menu": (BTN_SELECT, BTN_START),
    "lb_rb_y": (BTN_TL, BTN_TR, BTN_NORTH),
}
EVENT = struct.Struct("llHHi")
INPUT_DIR = "/dev/input"
IN_CREATE = 0x100
IN_ATTRIB = 0x004
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
HOLD_SECONDS = 0.45


def ioc(direction, number, size):
    return (direction << 30) | (size << 16) | (ord("E") << 8) | number


def key_bits(fd):
    buffer = bytearray(KEY_CNT // 8)
    try:
        fcntl.ioctl(fd, ioc(2, 0x20 + EV_KEY, len(buffer)), buffer)
    except OSError:
        return None
    return buffer


def has_key(bits, code):
    return bool(bits[code // 8] & (1 << (code % 8)))


def device_name(fd):
    buffer = bytearray(256)
    try:
        length = fcntl.ioctl(fd, ioc(2, 0x06, len(buffer)), buffer)
    except OSError:
        return ""
    return bytes(buffer[:max(0, length - 1)]).decode(errors="replace") if isinstance(length, int) else ""


class InputMask(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("codes_size", ctypes.c_uint32), ("codes_ptr", ctypes.c_uint64)]


def apply_mask(fd, kind, codes, size):
    bitmap = (ctypes.c_uint8 * size)()
    for code in codes:
        bitmap[code // 8] |= 1 << (code % 8)
    mask = InputMask(kind, size, ctypes.addressof(bitmap))
    fcntl.ioctl(fd, ioc(1, 0x93, ctypes.sizeof(InputMask)), bytes(mask))


def restrict(fd, codes):
    apply_mask(fd, EV_SYN, (EV_KEY,), 8)
    apply_mask(fd, EV_KEY, codes, KEY_CNT // 8)


class Inotify:
    def __init__(self, path, callback):
        self.fd = None
        self.callback = callback
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
            if fd < 0:
                return
            if libc.inotify_add_watch(fd, path.encode(), IN_CREATE | IN_ATTRIB) < 0:
                os.close(fd)
                return
        except (OSError, AttributeError):
            return
        self.fd = fd
        asyncio.get_running_loop().add_reader(fd, self.drain)

    def drain(self):
        try:
            while os.read(self.fd, 4096):
                pass
        except BlockingIOError:
            pass
        except OSError:
            return
        self.callback()

    def close(self):
        if self.fd is not None:
            asyncio.get_running_loop().remove_reader(self.fd)
            os.close(self.fd)
            self.fd = None


class Pad:
    def __init__(self, on_down, on_up):
        self.on_down = on_down
        self.on_up = on_up
        self.codes = ()
        self.devices = {}
        self.pressed = {}
        self.active = False
        self.down_at = 0.0
        self.watcher = None
        self.rescan_handle = None

    def configure(self, shortcut):
        codes = SHORTCUTS.get(shortcut, ())
        if codes == self.codes and (self.watcher or not codes):
            return
        self.stop()
        self.codes = codes
        if not codes:
            return
        self.watcher = Inotify(INPUT_DIR, self.schedule_rescan)
        self.scan()

    def describe(self):
        return [name for _, name in self.devices.values()]

    def schedule_rescan(self):
        if self.rescan_handle is None:
            self.rescan_handle = asyncio.get_running_loop().call_later(1.0, self.scan)

    def scan(self):
        self.rescan_handle = None
        if not self.codes:
            return
        open_paths = {path for path, _ in self.devices.values()}
        try:
            entries = sorted(name for name in os.listdir(INPUT_DIR) if name.startswith("event"))
        except OSError:
            entries = []
        for entry in entries:
            path = os.path.join(INPUT_DIR, entry)
            if path in open_paths:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                continue
            bits = key_bits(fd)
            if not bits or not has_key(bits, BTN_SOUTH) or not all(has_key(bits, code) for code in self.codes):
                os.close(fd)
                continue
            try:
                restrict(fd, self.codes)
            except OSError as error:
                decky.logger.warning("cannot filter %s: %s", path, error)
                os.close(fd)
                continue
            name = device_name(fd)
            self.devices[fd] = (path, name)
            self.pressed[fd] = set()
            asyncio.get_running_loop().add_reader(fd, self.read, fd)
            decky.logger.info("voice shortcut listening on %s (%s)", path, name)

    def read(self, fd):
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            self.drop(fd)
            return
        if not data:
            self.drop(fd)
            return
        pressed = self.pressed[fd]
        for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
            _, _, kind, code, value = EVENT.unpack_from(data, offset)
            if kind != EV_KEY or code not in self.codes:
                continue
            if value:
                pressed.add(code)
            else:
                pressed.discard(code)
        self.update(all(code in pressed for code in self.codes))

    def update(self, chord):
        if chord and not self.active:
            self.active = True
            self.down_at = time.monotonic()
            self.on_down()
        elif not chord and self.active:
            self.active = False
            self.on_up(time.monotonic() - self.down_at >= HOLD_SECONDS)

    def drop(self, fd):
        try:
            asyncio.get_running_loop().remove_reader(fd)
        except RuntimeError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        self.devices.pop(fd, None)
        self.pressed.pop(fd, None)
        if self.active and not any(all(code in pressed for code in self.codes) for pressed in self.pressed.values()):
            self.update(False)
        self.schedule_rescan()

    def stop(self):
        if self.rescan_handle is not None:
            self.rescan_handle.cancel()
            self.rescan_handle = None
        if self.watcher:
            self.watcher.close()
            self.watcher = None
        for fd in list(self.devices):
            try:
                asyncio.get_running_loop().remove_reader(fd)
            except RuntimeError:
                pass
            os.close(fd)
        self.devices = {}
        self.pressed = {}
        self.active = False
        self.codes = ()
