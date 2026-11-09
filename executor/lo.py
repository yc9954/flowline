"""LibreOffice helpers for a desk container: start soffice with a UNO socket,
and run small UNO scripts inside the container against the *live* document
(read table cells back without saving, jump to a slide, close without saving).

All functions take a `DockerDesktop` (anything with `.sh()` and `.put_file()`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import time

UNO_PORT = 2002

# The command body is shared by two heads: in a desk container it runs with the system python3 (python3-uno)
# as a client of the GUI soffice's UNO socket; on a Mac it runs *inside* the GUI soffice as a user Python script
# (LibreOffice's bundled interpreter cannot be launched from a shell on macOS — launch constraint — and no other
# Python can load pyuno), dispatched with `soffice "vnd.sun.star.script:flowline_uno.py$main?language=Python&location=user"`.
_UNO_BODY = r'''
def find_doc(suffix):
    comps = desktop.getComponents().createEnumeration()
    docs = []
    while comps.hasMoreElements():
        c = comps.nextElement()
        try:
            url = c.getURL()
        except Exception:
            continue
        docs.append((url, c))
        if suffix and url.endswith(suffix):
            return c
    if suffix:
        raise SystemExit("no document ending with %r open; have %s" % (suffix, [u for u, _ in docs]))
    return docs

def table_shape(page):
    for i in range(page.getCount()):
        s = page.getByIndex(i)
        if s.getShapeType() == "com.sun.star.drawing.TableShape":
            return s
    return None

out = {}
if cmd == "list":
    out["docs"] = [u for u, _ in find_doc(None)]
elif cmd == "status":
    doc = find_doc(args[0]); out = {"url": doc.getURL(), "modified": bool(doc.isModified())}
    try:
        ctrl = doc.getCurrentController(); out["current_slide"] = ctrl.getCurrentPage().Number
    except Exception: pass
elif cmd == "goto":
    doc = find_doc(args[0]); n = int(args[1])
    page = doc.getDrawPages().getByIndex(n - 1)
    doc.getCurrentController().setCurrentPage(page)
    out = {"slide": n, "name": page.Name}
elif cmd == "cells":
    doc = find_doc(args[0]); n = int(args[1])
    page = doc.getDrawPages().getByIndex(n - 1)
    ts = table_shape(page)
    if ts is None: raise SystemExit("no table on slide %d" % n)
    m = ts.Model; rows = m.RowCount; cols = m.ColumnCount
    out = {"rows": rows, "cols": cols, "cells": [[m.getCellByPosition(c, r).getString() for c in range(cols)] for r in range(rows)],
           "modified": bool(doc.isModified())}
elif cmd == "geometry":
    # Shape positions (1/100 mm) on the slide + the view's visible area and zoom, for mapping to pixels.
    doc = find_doc(args[0]); n = int(args[1])
    page = doc.getDrawPages().getByIndex(n - 1)
    ctrl = doc.getCurrentController()
    shapes = []
    for i in range(page.getCount()):
        s = page.getByIndex(i); p = s.getPosition(); z = s.getSize()
        item = {"type": s.getShapeType(), "x": p.X, "y": p.Y, "w": z.Width, "h": z.Height}
        if s.getShapeType() == "com.sun.star.drawing.TableShape":
            m = s.Model
            item["rows"] = [m.getRows().getByIndex(r).Height for r in range(m.RowCount)]
            item["cols"] = [m.getColumns().getByIndex(c).Width for c in range(m.ColumnCount)]
        else:
            try: item["text"] = s.getString()[:60]
            except Exception: pass
        shapes.append(item)
    out = {"page_w": page.Width, "page_h": page.Height, "shapes": shapes}
    try:
        va = ctrl.VisibleArea; out["visible_area"] = {"x": va.X, "y": va.Y, "w": va.Width, "h": va.Height}
        out["zoom"] = ctrl.ZoomValue
    except Exception as e:
        out["view_error"] = str(e)
    try:
        w = ctrl.getFrame().getComponentWindow().getPosSize(); out["component_window"] = {"x": w.X, "y": w.Y, "w": w.Width, "h": w.Height}
        w = ctrl.getFrame().getContainerWindow().getPosSize(); out["container_window"] = {"x": w.X, "y": w.Y, "w": w.Width, "h": w.Height}
    except Exception as e:
        out["win_error"] = str(e)
elif cmd == "open":
    # Load a document into the running (possibly invisible) instance; it gets a normal, visible window.
    url = uno.systemPathToFileUrl(args[0])
    doc = desktop.loadComponentFromURL(url, "_blank", 0, ())
    out = {"url": doc.getURL(), "title": getattr(doc, "Title", "")}
elif cmd == "close":
    # Close without saving: drop the modified flag first so no dialog appears.
    doc = find_doc(args[0]); doc.setModified(False)
    try: doc.close(True)
    except Exception: doc.dispose()
    out = {"closed": True}
elif cmd == "closeall":
    for url, c in find_doc(None):
        try:
            c.setModified(False); c.close(True)
        except Exception:
            try: c.dispose()
            except Exception: pass
    out = {"closed": True}
elif cmd == "setcell":
    # test helper: write a cell through UNO (not used by the skill)
    doc = find_doc(args[0]); n = int(args[1]); c, r, text = int(args[2]), int(args[3]), args[4]
    m = table_shape(doc.getDrawPages().getByIndex(n - 1)).getModel(); m.getCellByPosition(c, r).setString(text)
    out = {"ok": True}
elif cmd == "fit":
    # Mac: no wmctrl — size the document's own window (x, y, w, h in screen points)
    doc = find_doc(args[0]); x, y, w, h = (int(v) for v in args[1:5])
    win = doc.getCurrentController().getFrame().getContainerWindow()
    win.setPosSize(x, y, w, h, 15)
    try: win.setVisible(True); win.toFront()
    except Exception: pass
    out = {"fit": [x, y, w, h]}
else:
    raise SystemExit("unknown cmd %s" % cmd)
'''

# head 1: socket client (desk containers)
_UNO_SCRIPT = r'''
import sys, json, uno, time
from com.sun.star.beans import PropertyValue

def connect(tries=20):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    last = None
    for _ in range(tries):
        try:
            return resolver.resolve("uno:socket,host=127.0.0.1,port=%d;urp;StarOffice.ComponentContext" % PORT)
        except Exception as e:
            last = e; time.sleep(0.5)
    raise SystemExit("uno connect failed: %s" % last)

PORT = int(sys.argv[1]); cmd = sys.argv[2]; args = sys.argv[3:]
ctx = connect()
desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
''' + _UNO_BODY + r'''
print(json.dumps(out))
'''

# head 2: in-process user script (Mac). Request/response through JSON files next to the profile.
_UNO_MAC_SCRIPT = r'''
# Flowline executor helper — runs inside LibreOffice (user script). Reads REQ, answers in REQ["out"].
import json, os, traceback, uno
REQ = __REQ__

def _handle(desktop, cmd, args):
    out = {}
''' + "\n".join("    " + l if l.strip() else l for l in _UNO_BODY.splitlines()) + r'''
    return out

def main(*a):
    req = {}
    try:
        req = json.load(open(REQ))
        out = _handle(XSCRIPTCONTEXT.getDesktop(), req["cmd"], req.get("args") or [])
    except SystemExit as e:
        out = {"error": str(e)}
    except Exception:
        out = {"error": traceback.format_exc()}
    dest = req.get("out") or (REQ + ".out")
    with open(dest + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(dest + ".tmp", dest)

g_exportedScripts = (main,)
'''


# The script lives at a content-addressed path, so a changed script is always (re)installed on first use.
_UNO_SCRIPT_PATH = "/tmp/flowline_uno_%s.py" % hashlib.sha1(_UNO_SCRIPT.encode()).hexdigest()[:10]

# ---------------------------------------------------------------------------
# Mac: the executor's own LibreOffice profile (never the person's), the soffice binary, the helper script.
# ---------------------------------------------------------------------------
_ROOT = os.environ.get("FLOWLINE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAC_PROFILE = os.environ.get("FLOWLINE_LO_PROFILE") or os.path.join(_ROOT, "data", "mac", "lo-profile")
_MAC_SOFFICE_CANDIDATES = ["/opt/homebrew/bin/soffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                           "/usr/local/bin/soffice"]
MAC_SOFFICE = os.environ.get("FLOWLINE_SOFFICE") or next((p for p in _MAC_SOFFICE_CANDIDATES if os.path.exists(p)), None)
_MAC_SCRIPT_URL = "vnd.sun.star.script:flowline_uno.py$main?language=Python&location=user"
_MAC_REGISTRY = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Setup/Office"><prop oor:name="OfficeRestartInProgress" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
'''


def is_mac(d) -> bool:
    return getattr(d, "name", "") == "mac"


def mac_profile_url() -> str:
    return "file://" + MAC_PROFILE


def mac_argv(*extra: str) -> list[str]:
    if not MAC_SOFFICE:
        raise RuntimeError("LibreOffice for Mac not found (brew install --cask libreoffice, or set FLOWLINE_SOFFICE)")
    return [MAC_SOFFICE, f"-env:UserInstallation={mac_profile_url()}", "--norestore", "--nologo", "--nofirststartwizard", *extra]


def mac_install() -> str:
    """The helper script into the executor's own profile (idempotent); returns the request file path."""
    import subprocess as _sp  # noqa: F401
    scripts = os.path.join(MAC_PROFILE, "user", "Scripts", "python")
    os.makedirs(scripts, exist_ok=True)
    req = os.path.join(MAC_PROFILE, "flowline-uno-req.json")
    body = _UNO_MAC_SCRIPT.replace("__REQ__", json.dumps(req))
    target = os.path.join(scripts, "flowline_uno.py")
    if not os.path.exists(target) or open(target, encoding="utf-8").read() != body:
        with open(target, "w", encoding="utf-8") as f:
            f.write(body)
    reg = os.path.join(MAC_PROFILE, "user", "registrymodifications.xcu")
    if not os.path.exists(reg):
        with open(reg, "w", encoding="utf-8") as f:
            f.write(_MAC_REGISTRY)
    return req


def _mac_pids() -> list[int]:
    import subprocess
    p = subprocess.run(["pgrep", "-f", f"UserInstallation={mac_profile_url()}"], capture_output=True, text=True)
    return [int(x) for x in p.stdout.split() if x.isdigit()]


def _mac_ready() -> bool:
    """The instance accepts IPC: its profile lock says so. A dispatch before that would start a second instance
    (which then owns the pipe, and dies with the launcher's timeout) — seen on the first Mac smoke test."""
    if not _mac_pids():
        return False
    try:
        return "IPCServer=true" in open(os.path.join(MAC_PROFILE, ".lock"), encoding="utf-8", errors="replace").read()
    except OSError:
        return False


def _uno_mac(cmd: str, args: tuple, timeout: float) -> dict:
    import subprocess, uuid
    if not _mac_ready():
        raise RuntimeError("uno %s failed: the executor's LibreOffice is not running (or not ready) on this Mac" % cmd)
    req = mac_install()
    out_path = os.path.join(MAC_PROFILE, f"flowline-uno-out-{uuid.uuid4().hex[:8]}.json")
    with open(req + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"cmd": cmd, "args": [str(a) for a in args], "out": out_path}, f)
    os.replace(req + ".tmp", req)
    # the launcher hands the URL to the running instance and exits; it is only ever killed itself (never the instance)
    try:
        p = subprocess.run(mac_argv(_MAC_SCRIPT_URL), capture_output=True, text=True, timeout=max(timeout, 20))
        rc, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, err = -1, f"launcher timed out: {e}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(out_path):
            try:
                data = json.load(open(out_path, encoding="utf-8"))
            finally:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
            if "error" in data:
                raise RuntimeError(f"uno {cmd} failed: {data['error'].strip()[-500:]}")
            return data
        time.sleep(0.15)
    raise RuntimeError(f"uno {cmd} timed out after {timeout}s (dispatch rc={rc} {str(err).strip()[-200:]})")


def install(d) -> None:
    import os, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(_UNO_SCRIPT)
        p = f.name
    try:
        d.put_file(p, _UNO_SCRIPT_PATH)
    finally:
        os.unlink(p)


def uno(d, cmd: str, *args: str, timeout: float = 60, retry_install: bool = True) -> dict:
    """Run a UNO subcommand against the live GUI soffice and return its JSON (container: socket client; Mac: in-process)."""
    if is_mac(d):
        return _uno_mac(cmd, args, timeout)
    argv = " ".join(shlex.quote(str(a)) for a in (UNO_PORT, cmd, *args))
    rc, out = d.sh(f"/usr/bin/python3 {_UNO_SCRIPT_PATH} {argv} 2>&1", timeout=timeout)
    if rc != 0 and "No such file" in out and retry_install:
        install(d)
        return uno(d, cmd, *args, timeout=timeout, retry_install=False)
    if rc != 0:
        raise RuntimeError(f"uno {cmd} failed ({rc}): {out.strip()[-500:]}")
    line = out.strip().splitlines()[-1]
    return json.loads(line)


def soffice_running(d) -> bool:
    if is_mac(d):  # only the executor's own instance (its profile); the person's LibreOffice is not ours
        return bool(_mac_pids())
    rc, out = d.sh("pgrep -f '[s]office.bin' >/dev/null && echo yes || echo no")  # [s] so pgrep does not match this shell
    return out.strip() == "yes"


def kill_soffice(d) -> None:
    if is_mac(d):
        import signal, subprocess
        for pid in _mac_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.8)
        for pid in _mac_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        for lock in (os.path.join(MAC_PROFILE, ".lock"), os.path.join(MAC_PROFILE, "user", ".lock")):
            try:
                os.unlink(lock)
            except OSError:
                pass
        return
    d.sh("pkill -f soffice.bin; sleep 0.5; pkill -9 -f soffice.bin; rm -f /config/.config/libreoffice/4/.lock /config/.config/libreoffice/4/user/.lock 2>/dev/null; true")


def start_soffice(d, path: str | None = None, app: str | None = None, wait_title: str | None = None,
                  timeout: float = 40) -> None:
    """Start (or reuse) the GUI soffice with a UNO socket and open `path`.

    `app` = calc | impress | writer picks the module when `path` is None.
    """
    t0 = time.time()
    if is_mac(d):
        import subprocess
        mac_install()
        if not _mac_pids():  # a lock left by a crashed instance would make LibreOffice ask about recovery
            try:
                os.unlink(os.path.join(MAC_PROFILE, ".lock"))
            except OSError:
                pass
        target = [path] if path else ([f"--{app}"] if app else ["--invisible"])
        subprocess.Popen(mac_argv(*target), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        while time.time() - t0 < timeout and not _mac_ready():   # never dispatch into a half-started instance
            time.sleep(0.3)
        time.sleep(0.5)
        while time.time() - t0 < timeout:
            try:
                docs = uno(d, "list", timeout=20)["docs"]
                if not path or any(u.endswith(path.rsplit('/', 1)[-1]) for u in docs):
                    break
            except Exception:
                pass
            time.sleep(0.7)
        return
    accept = f'--accept="socket,host=127.0.0.1,port={UNO_PORT};urp;StarOffice.ServiceManager"'
    # no document: start invisible (no Start Center) so documents opened later still get normal windows
    target = shlex.quote(path) if path else (f"--{app}" if app else "--invisible")
    d.sh(f"nohup soffice --norestore --nologo --nofirststartwizard {accept} {target} >/dev/null 2>&1 &")
    install(d)
    while time.time() - t0 < timeout:
        try:
            docs = uno(d, "list")["docs"]
            if not path or any(u.endswith(path.rsplit('/', 1)[-1]) for u in docs):
                break
        except Exception:
            pass
        time.sleep(0.7)
    if wait_title:
        while time.time() - t0 < timeout:
            if wait_title.lower() in d.active_window_title().lower():
                break
            time.sleep(0.5)


def open_document(d, path: str, timeout: float = 30) -> dict:
    """Open `path` in the running soffice through UNO (fast, works with the warm invisible instance)."""
    return uno(d, "open", path, timeout=timeout)


def uno_alive(d) -> bool:
    try:
        uno(d, "list", timeout=15)
        return True
    except Exception:
        return False


def warm(d, timeout: float = 40) -> dict:
    """Make sure a GUI soffice with the UNO socket is up (invisible until a document opens),
    so the first run opens the deck in ~2 s instead of a cold start."""
    t0 = time.time()
    if soffice_running(d) and uno_alive(d):
        return {"warmed": False, "already": True, "seconds": round(time.time() - t0, 2)}
    if soffice_running(d):  # running without our socket (e.g. started by hand): restart it
        kill_soffice(d)
        time.sleep(1.0)
    start_soffice(d, None, timeout=timeout)
    return {"warmed": True, "uno": uno_alive(d), "seconds": round(time.time() - t0, 2)}


def maximize_active(d, doc_suffix: str | None = None) -> None:
    if is_mac(d):  # no window manager to ask: size the document's own window to the screen (below the menu bar)
        if doc_suffix:
            w, h = d.size()
            uno(d, "fit", doc_suffix, "0", "25", str(w), str(h - 25))
        return
    d.sh("wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz")


def activate_window(d, title_substring: str) -> bool:
    if is_mac(d):  # bring the executor's LibreOffice to the front
        try:
            from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication
            ok = False
            for pid in _mac_pids():
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                if app is not None:
                    ok = bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)) or ok
            return ok
        except Exception:  # noqa: BLE001  (no pyobjc AppKit): fall back to AppleScript on the bundle
            import subprocess
            p = subprocess.run(["osascript", "-e", 'tell application "LibreOffice" to activate'], capture_output=True)
            return p.returncode == 0
    rc, out = d.sh(f"wmctrl -a {shlex.quote(title_substring)} && echo ok")
    return "ok" in out


# ---------------------------------------------------------------------------
# Mapping document geometry (1/100 mm) onto screen pixels, used by the actor to
# click table cells like a person would.
# ---------------------------------------------------------------------------
def find_slide_rect(png: bytes, edit_box: tuple[int, int, int, int] | None = None):
    """Locate the white slide rectangle in a screenshot → (left, top, width, height) or None."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("L")
    W, H = im.size
    px = im.load()
    x_lo, y_lo, x_hi, y_hi = edit_box or (int(W * 0.08), int(H * 0.11), int(W * 0.83), int(H * 0.96))

    def longest_white_run(line_iter):
        best = (0, 0)
        start = None
        n = 0
        for i, v in line_iter:
            if v >= 250:
                if start is None:
                    start = i
                n += 1
                if n > best[0]:
                    best = (n, start)
            else:
                start, n = None, 0
        return best

    row_best = (0, 0, 0)
    for y in range(y_lo, y_hi, 4):
        ln, st = longest_white_run((x, px[x, y]) for x in range(x_lo, x_hi))
        if ln > row_best[0]:
            row_best = (ln, st, y)
    if row_best[0] < (x_hi - x_lo) * 0.3:
        return None
    left, width = row_best[1], row_best[0]
    xc = left + width // 2
    col_best = (0, 0)
    for xx in (xc - width // 3, xc + width // 3, left + 10, left + width - 10):
        ln, st = longest_white_run((y, px[xx, y]) for y in range(y_lo, y_hi))
        if ln > col_best[0]:
            col_best = (ln, st)
    if col_best[0] < 100:
        return None
    return left, col_best[1], width, col_best[0]


def cell_positions_from_geometry(geom: dict, slide_rect: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Centres of the last (amount) column's cells, in display pixels, from `uno(... "geometry")`."""
    left, top, width, height = slide_rect
    sx = width / geom["page_w"]
    sy = height / geom["page_h"]
    table = next((s for s in geom["shapes"] if s["type"].endswith("TableShape")), None)
    if table is None:
        raise RuntimeError("no table on the slide")
    col_x = table["x"] + sum(table["cols"][:-1]) + table["cols"][-1] / 2
    out = []
    y = table["y"]
    for rh in table["rows"]:
        out.append((int(round(left + col_x * sx)), int(round(top + (y + rh / 2) * sy))))
        y += rh
    return out
