#!/usr/bin/env python3
"""Minimal X11 GUI automation for DISPLAY=:99 (no xdotool needed).

Usage:
  xgui.py screenshot OUT.png
  xgui.py click X Y [button]
  xgui.py move X Y
  xgui.py key COMBO...        e.g. key ctrl+shift+p  key Return  key Escape
  xgui.py type TEXT
"""
import ctypes, ctypes.util, subprocess, sys, time

class X:
    def __init__(self, disp=":99"):
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.xtst = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.d = self.x11.XOpenDisplay(disp.encode())
        if not self.d:
            raise RuntimeError("cannot open display " + disp)
        self.x11.XStringToKeysym.restype = ctypes.c_ulong
        self.x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

    def flush(self):
        self.x11.XFlush(self.d)

    def move(self, x, y):
        self.xtst.XTestFakeMotionEvent(self.d, -1, int(x), int(y), 0); self.flush()

    def click(self, x, y, button=1, settle=0.15):
        self.move(x, y); self.flush(); time.sleep(0.05)
        self.xtst.XTestFakeButtonEvent(self.d, button, 1, 0); self.flush()
        time.sleep(0.04)
        self.xtst.XTestFakeButtonEvent(self.d, button, 0, 0); self.flush()
        time.sleep(settle)

    def keycode(self, name):
        ks = self.x11.XStringToKeysym(name.encode())
        if not ks:
            raise ValueError("unknown keysym: " + name)
        kc = self.x11.XKeysymToKeycode(self.d, ks)
        if kc == 0:
            raise ValueError("no keycode for: " + name)
        return kc

    def press(self, name, shift=False, ctrl=False, alt=False):
        SPECIAL_KEYS = {"escape": "Escape", "return": "Return", "enter": "Return", "tab": "Tab",
                        "space": "space", "backspace": "BackSpace", "delete": "Delete",
                        "up": "Up", "down": "Down", "left": "Left", "right": "Right",
                        "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next"}
        name = SPECIAL_KEYS.get(name.lower() if name.isalpha() else name, name)
        mods = []
        if shift: mods.append(self.keycode("Shift_L"))
        if ctrl: mods.append(self.keycode("Control_L"))
        if alt: mods.append(self.keycode("Alt_L"))
        kc = self.keycode(name)
        for m in mods:
            self.xtst.XTestFakeKeyEvent(self.d, m, 1, 0)
        self.flush(); time.sleep(0.02)
        self.xtst.XTestFakeKeyEvent(self.d, kc, 1, 0); self.flush(); time.sleep(0.02)
        self.xtst.XTestFakeKeyEvent(self.d, kc, 0, 0); self.flush(); time.sleep(0.02)
        for m in reversed(mods):
            self.xtst.XTestFakeKeyEvent(self.d, m, 0, 0)
        self.flush()

    def combo(self, spec):
        parts = spec.split("+")
        names = {"ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L", "meta": "Super_L"}
        key = parts[-1]
        key = names.get(key.lower(), key.lower() if len(key) == 1 else key)
        self.press(key, shift="shift" in [p.lower() for p in parts[:-1]],
                   ctrl="ctrl" in [p.lower() for p in parts[:-1]],
                   alt="alt" in [p.lower() for p in parts[:-1]])

    def type_text(self, text):
        SPECIAL = {' ': 'space', '.': 'period', ',': 'comma', '/': 'slash', '-': 'minus',
                   '_': 'underscore', ':': 'colon', '=': 'equal', ';': 'semicolon',
                   "'": 'apostrophe', '"': 'quotedbl', '(': 'parenleft', ')': 'parenright',
                   '[': 'bracketleft', ']': 'bracketright', '{': 'braceleft', '}': 'braceright',
                   '*': 'asterisk', '+': 'plus', '!': 'exclam', '?': 'question', '>': 'greater',
                   '<': 'less', '@': 'at', '#': 'numbersign', '%': 'percent', '^': 'asciicircum',
                   '&': 'ampersand', '|': 'bar', '\\': 'backslash', '~': 'asciitilde', '`': 'grave'}
        SHIFTED = {'>': 'period', '<': 'comma', '?': 'slash', ':': 'semicolon', '_': 'minus',
                   '+': 'equal', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6',
                   '&': '7', '*': '8', '(': '9', ')': '0', '|': 'backslash', '~': 'grave',
                   '{': 'bracketleft', '}': 'bracketright', '"': 'apostrophe'}
        for ch in text:
            if ch.isupper():
                self.press(ch.lower(), shift=True)
            elif ch in SHIFTED:
                self.press(SHIFTED[ch], shift=True)
            elif ch in SPECIAL:
                self.press(SPECIAL[ch])
            elif ch.isalnum():
                self.press(ch)
            else:
                PLAIN = {'=': 'equal', '-': 'minus', '.': 'period', ',': 'comma', ';': 'semicolon',
                         '/': 'slash', '\\': 'backslash', '`': 'grave', '[': 'bracketleft',
                         ']': 'bracketright', "'": 'apostrophe', ' ': 'space', '\n': 'Return',
                         '\t': 'Tab'}
                self.press(PLAIN.get(ch, SPECIAL.get(ch, ch)))
            time.sleep(0.01)

def screenshot(path, disp=":99"):
    out = subprocess.run(["xdpyinfo", "-display", disp], capture_output=True, text=True).stdout
    size = [l.split()[1] for l in out.splitlines() if l.strip().startswith("dimensions:")][0]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-video_size", size,
                    "-i", disp + ".0", "-frames:v", "1", "-y", path], check=True)

if __name__ == "__main__":
    x = X()
    cmd = sys.argv[1]
    if cmd == "screenshot":
        screenshot(sys.argv[2])
    elif cmd == "click":
        x.click(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    elif cmd == "move":
        x.move(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "key":
        for spec in sys.argv[2:]:
            x.combo(spec); time.sleep(0.05)
    elif cmd == "type":
        x.type_text(sys.argv[2])
    else:
        raise SystemExit("unknown command " + cmd)
