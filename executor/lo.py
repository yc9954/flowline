"""LibreOffice helpers for a desk container: start soffice with a UNO socket,
and run small UNO scripts inside the container against the *live* document
(read table cells back without saving, jump to a slide, close without saving).

All functions take a `DockerDesktop` (anything with `.sh()` and `.put_file()`).
"""
from __future__ import annotations

import hashlib
import json
import shlex
import time

UNO_PORT = 2002

# Runs inside the container with the system python3 (python3-uno is installed).
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
else:
    raise SystemExit("unknown cmd %s" % cmd)
print(json.dumps(out))
'''


# The script lives at a content-addressed path, so a changed script is always (re)installed on first use.
_UNO_SCRIPT_PATH = "/tmp/flowline_uno_%s.py" % hashlib.sha1(_UNO_SCRIPT.encode()).hexdigest()[:10]


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
    """Run a UNO subcommand inside the container and return its JSON."""
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
    rc, out = d.sh("pgrep -f '[s]office.bin' >/dev/null && echo yes || echo no")  # [s] so pgrep does not match this shell
    return out.strip() == "yes"


def kill_soffice(d) -> None:
    d.sh("pkill -f soffice.bin; sleep 0.5; pkill -9 -f soffice.bin; rm -f /config/.config/libreoffice/4/.lock /config/.config/libreoffice/4/user/.lock 2>/dev/null; true")


def start_soffice(d, path: str | None = None, app: str | None = None, wait_title: str | None = None,
                  timeout: float = 40) -> None:
    """Start (or reuse) the GUI soffice with a UNO socket and open `path`.

    `app` = calc | impress | writer picks the module when `path` is None.
    """
    accept = f'--accept="socket,host=127.0.0.1,port={UNO_PORT};urp;StarOffice.ServiceManager"'
    # no document: start invisible (no Start Center) so documents opened later still get normal windows
    target = shlex.quote(path) if path else (f"--{app}" if app else "--invisible")
    d.sh(f"nohup soffice --norestore --nologo --nofirststartwizard {accept} {target} >/dev/null 2>&1 &")
    install(d)
    t0 = time.time()
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


def maximize_active(d) -> None:
    d.sh("wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz")


def activate_window(d, title_substring: str) -> bool:
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
