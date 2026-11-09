"""Desktop backends for the Flowline executor.

A `Desktop` is the thing the agent drives: it can take a screenshot, move and
click the mouse, type, press keys, scroll, read the active window title, say how
long the user has been idle, run a shell command on that machine and open a file.

Two backends:

* `DockerDesktop(container, host="mini")` - an XFCE desktop inside a Docker
  container on a remote Mac mini (`ssh mini`).  Actions are xdotool commands and
  screenshots are `scrot`.  To keep each action in the tens of milliseconds a
  small helper process is kept alive inside the container (one `ssh` +
  `docker exec -i` pipe, JSON lines in both directions); if the pipe dies we
  fall back to one-shot `docker exec` and try to restart it.
* `MacDesktop()` - this Mac, via `screencapture` and Quartz CGEvents.  Only
  screenshot and mouse move are exercised by the tests (never click around on
  the developer's machine unattended).

Coordinates given to a Desktop are always *logical* points of that display
(`size()`); screenshots report their pixel size separately so callers can scale.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

SSH_OPTS = [
    "-o", "ControlMaster=auto",
    "-o", "ControlPath=/tmp/flowline-ssh-%r@%h:%p",
    "-o", "ControlPersist=600",
    "-o", "BatchMode=yes",
    "-o", "ServerAliveInterval=15",
]
DOCKER = "/opt/homebrew/bin/docker"
# Where the desk containers live: an ssh host (default "mini"), or "local" when this code runs on the mini itself.
DEFAULT_HOST = os.environ.get("FLOWLINE_DESK_HOST", "mini")


def docker_binary() -> str:
    """Docker CLI for the local case: Homebrew path first, then PATH."""
    if os.path.exists(DOCKER):
        return DOCKER
    import shutil
    return shutil.which("docker") or DOCKER


@dataclass
class Screenshot:
    png: bytes
    width: int      # pixel size of the PNG
    height: int
    logical_w: int  # logical display size (points)
    logical_h: int

    @property
    def scale(self) -> float:
        """Pixels per logical point (2.0 on Retina, 1.0 elsewhere)."""
        return self.width / self.logical_w if self.logical_w else 1.0


@dataclass
class ActionTiming:
    action: str
    seconds: float
    at: float = field(default_factory=time.time)


class Desktop:
    """Interface. Subclasses implement the `_`-prefixed primitives."""

    name = "desktop"

    def __init__(self):
        self.timings: list[ActionTiming] = []
        self._last_mouse: Optional[tuple[int, int]] = None
        self._last_title: Optional[str] = None
        self._last_change = time.time()

    # -- timing helper -----------------------------------------------------
    def _timed(self, action: str, fn, *a, **kw):
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            self.timings.append(ActionTiming(action, time.perf_counter() - t0))

    def timing_summary(self) -> dict:
        out: dict[str, dict] = {}
        for t in self.timings:
            d = out.setdefault(t.action, {"n": 0, "total": 0.0, "max": 0.0})
            d["n"] += 1
            d["total"] += t.seconds
            d["max"] = max(d["max"], t.seconds)
        for d in out.values():
            d["mean_ms"] = round(1000 * d["total"] / d["n"], 1)
            d["max_ms"] = round(1000 * d["max"], 1)
            del d["total"], d["max"]
        return out

    # -- public API ----------------------------------------------------------
    def size(self) -> tuple[int, int]:
        raise NotImplementedError

    def screenshot(self) -> Screenshot:
        return self._timed("screenshot", self._screenshot)

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._timed("click", self._click, int(x), int(y), button)

    def double_click(self, x: int, y: int) -> None:
        self._timed("double_click", self._double_click, int(x), int(y))

    def triple_click(self, x: int, y: int) -> None:
        self._timed("triple_click", self._triple_click, int(x), int(y))

    def move(self, x: int, y: int) -> None:
        self._timed("move", self._move, int(x), int(y))

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._timed("drag", self._drag, int(x0), int(y0), int(x1), int(y1))

    def type(self, text: str) -> None:
        self._timed("type", self._type, text)

    def key(self, combo: str, repeat: int = 1) -> None:
        self._timed("key", self._key, combo, repeat)

    def scroll(self, x: int, y: int, direction: str, amount: int = 3) -> None:
        self._timed("scroll", self._scroll, int(x), int(y), direction, int(amount))

    def mouse_position(self) -> tuple[int, int]:
        return self._timed("mouse_position", self._mouse_position)

    def active_window_title(self) -> str:
        return self._timed("active_window_title", self._active_window_title)

    def idle_seconds(self) -> float:
        """Seconds since the pointer last moved or the active window changed.

        Backends with a real idle source (xprintidle) override this; otherwise
        it is derived from repeated calls, so poll it.
        """
        try:
            pos = self._mouse_position()
        except Exception:
            pos = self._last_mouse
        try:
            title = self._active_window_title()
        except Exception:
            title = self._last_title
        now = time.time()
        if pos != self._last_mouse or title != self._last_title:
            self._last_change = now
        self._last_mouse, self._last_title = pos, title
        return now - self._last_change

    def run(self, cmd: str, timeout: float = 60) -> tuple[int, str]:
        """Run a shell command on the target machine → (returncode, output)."""
        return self._timed("run", self._run, cmd, timeout)

    def open_file(self, path: str) -> None:
        self._timed("open_file", self._open_file, path)

    def close(self) -> None:
        pass

    # -- primitives ---------------------------------------------------------
    def _screenshot(self) -> Screenshot: raise NotImplementedError
    def _click(self, x, y, button): raise NotImplementedError
    def _double_click(self, x, y): raise NotImplementedError
    def _triple_click(self, x, y): raise NotImplementedError
    def _move(self, x, y): raise NotImplementedError
    def _drag(self, x0, y0, x1, y1): raise NotImplementedError
    def _type(self, text): raise NotImplementedError
    def _key(self, combo, repeat): raise NotImplementedError
    def _scroll(self, x, y, direction, amount): raise NotImplementedError
    def _mouse_position(self): raise NotImplementedError
    def _active_window_title(self): raise NotImplementedError
    def _run(self, cmd, timeout): raise NotImplementedError
    def _open_file(self, path): raise NotImplementedError


# ---------------------------------------------------------------------------
# Helper that lives inside the container.  Reads one JSON object per line:
#   {"id": n, "cmd": "sh",   "args": "<shell>", "timeout": s}
#   {"id": n, "cmd": "shot"}            -> runs scrot, returns base64 PNG
#   {"id": n, "cmd": "ping"}
# and writes one JSON object per line: {"id": n, "rc": int, "out": str, "png": b64}
# ---------------------------------------------------------------------------
_AGENT_SRC = r'''
import sys, json, subprocess, base64, os
os.environ.setdefault("DISPLAY", ":1")
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception as e:
        sys.stdout.write(json.dumps({"id": None, "rc": 1, "out": "bad json: %s" % e}) + "\n"); sys.stdout.flush(); continue
    rid = req.get("id"); cmd = req.get("cmd")
    resp = {"id": rid, "rc": 0, "out": ""}
    try:
        if cmd == "ping":
            resp["out"] = "pong"
        elif cmd == "sh":
            p = subprocess.run(["sh", "-c", req["args"]], capture_output=True, text=True,
                               timeout=req.get("timeout", 60), errors="replace")
            resp["rc"] = p.returncode; resp["out"] = (p.stdout + p.stderr)[-200000:]
        elif cmd == "shot":
            path = "/tmp/flowline_shot.png"
            p = subprocess.run(["scrot", "-o", path], capture_output=True, text=True, timeout=10)
            if p.returncode != 0:
                resp["rc"] = p.returncode; resp["out"] = p.stdout + p.stderr
            else:
                with open(path, "rb") as f:
                    resp["png"] = base64.b64encode(f.read()).decode()
        else:
            resp["rc"] = 2; resp["out"] = "unknown cmd %r" % cmd
    except subprocess.TimeoutExpired:
        resp["rc"] = 124; resp["out"] = "timeout"
    except Exception as e:
        resp["rc"] = 1; resp["out"] = "error: %s" % e
    sys.stdout.write(json.dumps(resp) + "\n"); sys.stdout.flush()
'''


class DockerDesktop(Desktop):
    """XFCE desktop in a Docker container on a remote host, driven with xdotool."""

    name = "docker"

    def __init__(self, container: str = "desk1", host: str | None = None, user: str = "abc",
                 display: str = ":1", home: str = "/config", docker: str | None = None,
                 persistent: bool = True):
        super().__init__()
        self.host = DEFAULT_HOST if host is None else host
        self.container, self.user = container, user
        self.display, self.home = display, home
        # remote: the mini's Homebrew docker (not on PATH for non-login shells); local: whatever is installed
        self.docker = docker or (DOCKER if self._ssh_prefix() else docker_binary())
        self._size: Optional[tuple[int, int]] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._persistent = persistent

    # -- transport ----------------------------------------------------------
    def _ssh_prefix(self) -> list[str]:
        if self.host in ("", "local", "localhost"):
            return []
        return ["ssh", *SSH_OPTS, self.host]

    def _exec_argv(self, interactive: bool, shell_cmd: str) -> list[str]:
        """argv to run `sh -c shell_cmd` inside the container (maybe over ssh)."""
        inner = [self.docker, "exec"] + (["-i"] if interactive else []) + [
            "-u", self.user, "-e", f"DISPLAY={self.display}", "-e", f"HOME={self.home}",
            self.container, "sh", "-c", shell_cmd]
        pre = self._ssh_prefix()
        if pre:
            # ssh joins argv with spaces and runs it through the remote shell: quote.
            return pre + [" ".join(shlex.quote(a) for a in inner)]
        return inner

    def _oneshot(self, shell_cmd: str, timeout: float = 60, binary: bool = False):
        p = subprocess.run(self._exec_argv(False, shell_cmd), capture_output=True,
                           timeout=timeout + 30)
        if binary:
            return p.returncode, p.stdout
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")

    def _ensure_agent(self) -> Optional[subprocess.Popen]:
        if not self._persistent:
            return None
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        b64 = base64.b64encode(_AGENT_SRC.encode()).decode()
        boot = f"exec /usr/bin/python3 -u -c \"import base64;exec(base64.b64decode('{b64}'))\""
        try:
            self._proc = subprocess.Popen(self._exec_argv(True, boot), stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          text=True, bufsize=1)
            r = self._request({"cmd": "ping"}, timeout=20)
            if r.get("out") != "pong":
                raise RuntimeError("agent did not answer ping")
        except Exception:
            self._kill_agent()
        return self._proc

    def _kill_agent(self):
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def _request(self, req: dict, timeout: float = 60) -> dict:
        assert self._proc is not None
        self._next_id += 1
        req = dict(req, id=self._next_id)
        line = json.dumps(req) + "\n"
        result: dict = {}
        exc: list[BaseException] = []

        def reader():
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                while True:
                    out = self._proc.stdout.readline()
                    if not out:
                        raise RuntimeError("agent pipe closed")
                    resp = json.loads(out)
                    if resp.get("id") == req["id"]:
                        result.update(resp)
                        return
            except BaseException as e:  # noqa: BLE001
                exc.append(e)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout + 30)
        if t.is_alive():
            self._kill_agent()
            raise TimeoutError(f"desktop action timed out: {req.get('cmd')}")
        if exc:
            self._kill_agent()
            raise exc[0]
        return result

    def sh(self, shell_cmd: str, timeout: float = 60) -> tuple[int, str]:
        """Run a shell command inside the container (fast path via the agent)."""
        with self._lock:
            if self._ensure_agent() is not None:
                try:
                    r = self._request({"cmd": "sh", "args": shell_cmd, "timeout": timeout}, timeout)
                    return r.get("rc", 1), r.get("out", "")
                except Exception:
                    pass  # fall through to one-shot
            return self._oneshot(shell_cmd, timeout)

    def xdotool(self, *args: str) -> str:
        rc, out = self.sh("xdotool " + " ".join(shlex.quote(a) for a in args))
        if rc != 0:
            raise RuntimeError(f"xdotool {' '.join(args)} failed ({rc}): {out.strip()}")
        return out

    # -- primitives ---------------------------------------------------------
    def size(self) -> tuple[int, int]:
        if self._size is None:
            rc, out = self.sh("xdpyinfo | awk '/dimensions/{print $2}'")
            try:
                w, h = out.strip().split("x")
                self._size = (int(w), int(h))
            except Exception:
                self._size = (1920, 1080)
        return self._size

    def _screenshot(self) -> Screenshot:
        w, h = self.size()
        with self._lock:
            png = None
            if self._ensure_agent() is not None:
                try:
                    r = self._request({"cmd": "shot"}, 20)
                    if r.get("png"):
                        png = base64.b64decode(r["png"])
                except Exception:
                    png = None
            if png is None:
                rc, data = self._oneshot("scrot -o /tmp/flowline_shot.png >/dev/null 2>&1 && cat /tmp/flowline_shot.png",
                                         timeout=20, binary=True)
                if rc != 0 or not data.startswith(b"\x89PNG"):
                    raise RuntimeError("screenshot failed")
                png = data
        pw, ph = _png_size(png)
        return Screenshot(png, pw, ph, w, h)

    _BTN = {"left": "1", "middle": "2", "right": "3"}

    def _click(self, x, y, button):
        self.xdotool("mousemove", str(x), str(y), "click", self._BTN.get(button, "1"))

    def _double_click(self, x, y):
        self.xdotool("mousemove", str(x), str(y), "click", "--repeat", "2", "--delay", "80", "1")

    def _triple_click(self, x, y):
        self.xdotool("mousemove", str(x), str(y), "click", "--repeat", "3", "--delay", "80", "1")

    def _move(self, x, y):
        self.xdotool("mousemove", str(x), str(y))

    def _drag(self, x0, y0, x1, y1):
        self.xdotool("mousemove", str(x0), str(y0), "mousedown", "1", "mousemove", str(x1), str(y1), "mouseup", "1")

    def _type(self, text):
        if not text:
            return
        # xdotool type handles unicode; keep newlines as Return presses.
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if part:
                self.xdotool("type", "--delay", "20", "--", part)
            if i < len(parts) - 1:
                self.xdotool("key", "Return")

    def _key(self, combo, repeat):
        combo = _xdo_key(combo)
        args = ["key", "--delay", "40"]
        if repeat and repeat > 1:
            args += ["--repeat", str(repeat)]
        self.xdotool(*args, combo)

    def _scroll(self, x, y, direction, amount):
        btn = {"up": "4", "down": "5", "left": "6", "right": "7"}[direction]
        self.xdotool("mousemove", str(x), str(y), "click", "--repeat", str(max(1, amount)), "--delay", "30", btn)

    def _mouse_position(self):
        out = self.xdotool("getmouselocation")
        d = dict(kv.split(":") for kv in out.split() if ":" in kv)
        return int(d["x"]), int(d["y"])

    def _active_window_title(self):
        rc, out = self.sh("xdotool getactivewindow getwindowname 2>/dev/null")
        return out.strip()

    def active_window_class(self) -> str:
        rc, out = self.sh("xprop -id $(xdotool getactivewindow) WM_CLASS 2>/dev/null")
        # WM_CLASS(STRING) = "libreoffice", "libreoffice-calc"
        if "=" in out:
            parts = [p.strip().strip('"') for p in out.split("=", 1)[1].split(",")]
            return parts[-1] if parts else ""
        return ""

    def _run(self, cmd, timeout):
        return self.sh(cmd, timeout)

    def _open_file(self, path):
        # Open with LibreOffice in the GUI; detach so the call returns.
        self.sh(f"nohup soffice --norestore {shlex.quote(path)} >/dev/null 2>&1 &")

    def put_file(self, local_path: str, remote_path: str) -> None:
        data = base64.b64encode(open(local_path, "rb").read()).decode()
        # chunk to keep lines sane
        self.sh(f": > {shlex.quote(remote_path)}.b64")
        for i in range(0, len(data), 60000):
            self.sh(f"printf %s {shlex.quote(data[i:i+60000])} >> {shlex.quote(remote_path)}.b64")
        rc, out = self.sh(f"base64 -d {shlex.quote(remote_path)}.b64 > {shlex.quote(remote_path)} && rm {shlex.quote(remote_path)}.b64")
        if rc != 0:
            raise RuntimeError(f"put_file failed: {out}")

    def get_file(self, remote_path: str) -> bytes:
        rc, out = self.sh(f"base64 -w0 {shlex.quote(remote_path)}")
        if rc != 0:
            raise RuntimeError(f"get_file failed: {out}")
        return base64.b64decode(out.strip())

    def idle_seconds(self) -> float:
        rc, out = self.sh("command -v xprintidle >/dev/null && xprintidle")
        if rc == 0 and out.strip().isdigit():
            return int(out.strip()) / 1000.0
        return super().idle_seconds()

    def close(self):
        self._kill_agent()


# ---------------------------------------------------------------------------
class MacDesktop(Desktop):
    """This Mac. Screenshot via `screencapture`, input via Quartz CGEvents.

    Coordinates are logical points (what Quartz uses).  `screencapture` returns
    device pixels on Retina, so `Screenshot.scale` is 2.0 there; callers that
    locate things in the PNG divide by `scale` before clicking.
    """

    name = "mac"

    def __init__(self):
        super().__init__()
        import Quartz  # noqa: F401  (pyobjc-framework-Quartz)
        self.Q = Quartz
        self._size = None

    def size(self):
        if self._size is None:
            b = self.Q.CGDisplayBounds(self.Q.CGMainDisplayID())
            self._size = (int(b.size.width), int(b.size.height))
        return self._size

    def _screenshot(self):
        import tempfile
        w, h = self.size()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        try:
            subprocess.run(["screencapture", "-x", "-t", "png", path], check=True, timeout=15)
            png = open(path, "rb").read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        pw, ph = _png_size(png)
        return Screenshot(png, pw, ph, w, h)

    def _post(self, ev):
        self.Q.CGEventPost(self.Q.kCGHIDEventTap, ev)

    def _mouse_event(self, kind, x, y, button=None):
        btn = {None: self.Q.kCGMouseButtonLeft, "left": self.Q.kCGMouseButtonLeft,
               "right": self.Q.kCGMouseButtonRight, "middle": self.Q.kCGMouseButtonCenter}[button]
        return self.Q.CGEventCreateMouseEvent(None, kind, (x, y), btn)

    def _move(self, x, y):
        self._post(self._mouse_event(self.Q.kCGEventMouseMoved, x, y))

    def _click(self, x, y, button):
        Q = self.Q
        down, up = {"left": (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp),
                    "right": (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp),
                    "middle": (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp)}[button]
        self._move(x, y)
        self._post(self._mouse_event(down, x, y, button))
        self._post(self._mouse_event(up, x, y, button))

    def _multi_click(self, x, y, n):
        Q = self.Q
        self._move(x, y)
        for i in range(1, n + 1):
            for kind in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
                ev = self._mouse_event(kind, x, y, "left")
                Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, i)
                self._post(ev)

    def _double_click(self, x, y):
        self._multi_click(x, y, 2)

    def _triple_click(self, x, y):
        self._multi_click(x, y, 3)

    def _drag(self, x0, y0, x1, y1):
        Q = self.Q
        self._move(x0, y0)
        self._post(self._mouse_event(Q.kCGEventLeftMouseDown, x0, y0, "left"))
        steps = 10
        for i in range(1, steps + 1):
            xi = x0 + (x1 - x0) * i / steps
            yi = y0 + (y1 - y0) * i / steps
            self._post(self._mouse_event(Q.kCGEventLeftMouseDragged, xi, yi, "left"))
            time.sleep(0.01)
        self._post(self._mouse_event(Q.kCGEventLeftMouseUp, x1, y1, "left"))

    def _type(self, text):
        Q = self.Q
        for ch in text:
            if ch == "\n":
                self._key("Return", 1)
                continue
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
                self._post(ev)
            time.sleep(0.02)

    _KEYCODES = {"return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
                 "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
                 "home": 115, "end": 119, "pageup": 116, "pagedown": 121, "forwarddelete": 117,
                 "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
                 "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
                 "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
                 "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
                 "l": 37, "j": 38, "k": 40, "n": 45, "m": 46}

    def _key(self, combo, repeat):
        Q = self.Q
        parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
        mods = 0
        key = parts[-1]
        for m in parts[:-1]:
            mods |= {"cmd": Q.kCGEventFlagMaskCommand, "command": Q.kCGEventFlagMaskCommand,
                     "super": Q.kCGEventFlagMaskCommand, "ctrl": Q.kCGEventFlagMaskControl,
                     "control": Q.kCGEventFlagMaskControl, "alt": Q.kCGEventFlagMaskAlternate,
                     "option": Q.kCGEventFlagMaskAlternate, "shift": Q.kCGEventFlagMaskShift}.get(m, 0)
        code = self._KEYCODES.get(key)
        if code is None:
            raise ValueError(f"unknown key {combo!r}")
        for _ in range(max(1, repeat)):
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(None, code, down)
                if mods:
                    Q.CGEventSetFlags(ev, mods)
                self._post(ev)
            time.sleep(0.03)

    def _scroll(self, x, y, direction, amount):
        Q = self.Q
        self._move(x, y)
        dy = {"up": amount, "down": -amount}.get(direction, 0)
        dx = {"left": amount, "right": -amount}.get(direction, 0)
        ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 2, dy, dx)
        self._post(ev)

    def _mouse_position(self):
        ev = self.Q.CGEventCreate(None)
        p = self.Q.CGEventGetLocation(ev)
        return int(p.x), int(p.y)

    def _active_window_title(self):
        Q = self.Q
        wins = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                                            Q.kCGNullWindowID) or []
        for w in wins:
            if w.get("kCGWindowLayer", 1) == 0:
                owner = w.get("kCGWindowOwnerName", "")
                name = w.get("kCGWindowName", "")
                return f"{name} — {owner}" if name else owner
        return ""

    def idle_seconds(self):
        Q = self.Q
        return float(Q.CGEventSourceSecondsSinceLastEventType(
            Q.kCGEventSourceStateHIDSystemState, Q.kCGAnyInputEventType))

    def _run(self, cmd, timeout):
        p = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr

    # the same file/shell surface as DockerDesktop, on this machine
    def sh(self, shell_cmd: str, timeout: float = 60) -> tuple[int, str]:
        return self._run(shell_cmd, timeout)

    def put_file(self, local_path: str, remote_path: str) -> None:
        import shutil
        dest = os.path.expanduser(remote_path)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        shutil.copyfile(local_path, dest)

    def get_file(self, remote_path: str) -> bytes:
        with open(os.path.expanduser(remote_path), "rb") as f:
            return f.read()

    def _open_file(self, path):
        subprocess.run(["open", path], check=False)


# ---------------------------------------------------------------------------
def _png_size(png: bytes) -> tuple[int, int]:
    if png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR":
        return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    return im.size


_XDO_KEYS = {"enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
             "backspace": "BackSpace", "delete": "Delete", "tab": "Tab", "space": "space",
             "up": "Up", "down": "Down", "left": "Left", "right": "Right", "home": "Home", "end": "End",
             "pageup": "Prior", "page_up": "Prior", "pagedown": "Next", "page_down": "Next",
             "ctrl": "ctrl", "alt": "alt", "shift": "shift", "super": "super", "cmd": "super",
             "win": "super", "meta": "super"}


def _xdo_key(combo: str) -> str:
    """Normalise a key combo like 'ctrl+shift+s' or 'Return' to xdotool syntax."""
    parts = [p for p in combo.replace("-", "+").split("+") if p]
    out = []
    for p in parts:
        low = p.lower()
        if low in _XDO_KEYS:
            out.append(_XDO_KEYS[low])
        elif len(p) == 1:
            out.append(p)
        elif low.startswith("f") and low[1:].isdigit():
            out.append("F" + low[1:])
        else:
            out.append(p)
    return "+".join(out)


def make_desktop(target: str) -> Desktop:
    """`mac` → MacDesktop; anything else is a container name on the mini."""
    if target == "mac":
        return MacDesktop()
    return DockerDesktop(container=target)


# ---------------------------------------------------------------------------
# Coordinate scaling between the model's view (≤ max_w wide) and the display.
# ---------------------------------------------------------------------------
@dataclass
class ViewScale:
    """Maps model-view pixels ↔ display logical points.

    `factor` = display_w / view_w (≥ 1).  The model sees a screenshot at most
    `max_w` wide; its coordinates are multiplied by `factor` before clicking.
    """
    display_w: int
    display_h: int
    view_w: int
    view_h: int

    @property
    def factor(self) -> float:
        return self.display_w / self.view_w

    def to_display(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x * self.factor)), int(round(y * self.factor))

    def to_view(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x / self.factor)), int(round(y / self.factor))

    @classmethod
    def fit(cls, display_w: int, display_h: int, max_w: int = 1280) -> "ViewScale":
        if display_w <= max_w:
            return cls(display_w, display_h, display_w, display_h)
        f = display_w / max_w
        return cls(display_w, display_h, max_w, int(round(display_h / f)))


def scale_png(png: bytes, shot: Screenshot, view: ViewScale) -> bytes:
    """Resize a screenshot PNG to the model view size (also undoes Retina)."""
    from PIL import Image
    im = Image.open(io.BytesIO(png))
    if im.size != (view.view_w, view.view_h):
        im = im.convert("RGB").resize((view.view_w, view.view_h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
