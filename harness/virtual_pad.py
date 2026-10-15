import fcntl
import os
import struct
import sys
import time

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
BUTTONS = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E]
AXES = [0, 1, 3, 4]


def iow(number, size):
    return (1 << 30) | (size << 16) | (ord("U") << 8) | number


UI_DEV_CREATE = (ord("U") << 8) | 1
UI_DEV_DESTROY = (ord("U") << 8) | 2
UI_DEV_SETUP = iow(3, 92)
UI_ABS_SETUP = iow(4, 28)
UI_SET_EVBIT = iow(100, 4)
UI_SET_KEYBIT = iow(101, 4)
UI_SET_ABSBIT = iow(103, 4)
EVENT = struct.Struct("llHHi")


def emit(fd, kind, code, value):
    now = time.time()
    os.write(fd, EVENT.pack(int(now), int(now % 1 * 1e6), kind, code, value))


def main():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for kind in (EV_KEY, EV_ABS):
        fcntl.ioctl(fd, UI_SET_EVBIT, kind)
    for code in BUTTONS:
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    for code in AXES:
        fcntl.ioctl(fd, UI_SET_ABSBIT, code)
        fcntl.ioctl(fd, UI_ABS_SETUP, struct.pack("HH6i", code, 0, 0, -32768, 32767, 16, 128, 0))
    fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack("4H80sI", 3, 0x1234, 0x5678, 1, b"Claude Decky Test Pad", 0))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    print("ready", flush=True)
    for line in sys.stdin:
        words = line.split()
        if not words:
            continue
        if words[0] == "axes":
            for index in range(int(words[1])):
                emit(fd, EV_ABS, AXES[index % 4], (index * 997) % 60000 - 30000)
                emit(fd, EV_SYN, 0, 0)
                time.sleep(0.001)
        elif words[0] in ("press", "release"):
            for code in words[1:]:
                emit(fd, EV_KEY, int(code, 16), 1 if words[0] == "press" else 0)
            emit(fd, EV_SYN, 0, 0)
        elif words[0] == "quit":
            break
        print("done", flush=True)
    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)


main()
