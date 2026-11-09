"""Desktop bridge: one Desktop per target, shared by the Run API and the TS agent.

The agent (agent-ts/run.mjs, Vercel AI SDK) never touches xdotool itself; it calls
  POST /desk/{target}/action  {action, coordinate, text, ...}   (computer toolset members)
  POST /desk/{target}/run     {cmd}
  GET  /desk/{target}/sheet?path=
  GET  /desk/{target}/deck_cells?deck=&slide=
  GET  /desk/{target}/view
which `main.py` routes here.  Coordinates from the model are in the view space
(screenshots scaled to ≤1280 wide); `perform` maps them to display points.
"""
from __future__ import annotations

import base64
import io
import os
import threading
import time
from typing import Any

from desktop import Desktop, DockerDesktop, ViewScale, _xdo_key, make_desktop, scale_png
from runs import RUNS_DIR

MAX_VIEW_W = int(os.environ.get("FLOWLINE_VIEW_W", "1280"))

COMPUTER_MEMBERS = {
    "screenshot", "zoom", "left_click", "right_click", "middle_click", "double_click", "triple_click",
    "left_click_drag", "mouse_move", "left_mouse_down", "left_mouse_up", "cursor_position", "scroll",
    "type", "key", "hold_key", "wait",
}


class Target:
    def __init__(self, name: str):
        self.name = name
        self.desktop: Desktop = make_desktop(name)
        w, h = self.desktop.size()
        self.view = ViewScale.fit(w, h, MAX_VIEW_W)
        self.lock = threading.RLock()
        self.shots = 0
        self.run_id: str | None = None          # the run that owns this desk right now (one run per target)
        self._frame_lock = threading.Lock()
        self._frame: dict[int, tuple[float, bytes]] = {}   # width → (taken_at, jpeg)


class DesktopPool:
    def __init__(self):
        self._targets: dict[str, Target] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> Target:
        with self._lock:
            t = self._targets.get(name)
            if t is None:
                t = self._targets[name] = Target(name)
            return t

    def close(self):
        for t in self._targets.values():
            try:
                t.desktop.close()
            except Exception:
                pass


def _coord(view: ViewScale, c) -> tuple[int, int]:
    return view.to_display(float(c[0]), float(c[1]))


def screenshot_payload(t: Target, run_id: str | None, label: str = "shot") -> dict:
    shot = t.desktop.screenshot()
    png = scale_png(shot.png, shot, t.view)
    out: dict[str, Any] = {"ok": True, "image": base64.b64encode(png).decode(), "width": t.view.view_w, "height": t.view.view_h}
    if run_id:
        d = os.path.join(RUNS_DIR, run_id)
        os.makedirs(d, exist_ok=True)
        t.shots += 1
        path = os.path.join(d, f"{label}-{t.shots:03d}.png")
        with open(path, "wb") as f:
            f.write(shot.png)
        out["path"] = path
    return out


def perform(t: Target, inp: dict, run_id: str | None = None) -> dict:
    """Execute one computer-toolset action. Returns {ok, result|image, ...} (errors as ok=False)."""
    d, view = t.desktop, t.view
    action = inp.get("action")
    with t.lock:
        try:
            if action == "screenshot":
                return screenshot_payload(t, run_id)
            if action == "zoom":
                return _zoom(t, inp["region"], run_id)
            if action in ("left_click", "right_click", "middle_click"):
                x, y = _coord(view, inp["coordinate"]) if inp.get("coordinate") else d.mouse_position()
                button = action.split("_")[0]
                mods = inp.get("text")
                if mods and d.name == "docker":
                    btn = {"left": "1", "middle": "2", "right": "3"}[button]
                    k = _xdo_key(mods)
                    rc, out = d.run(f"xdotool keydown {k} mousemove {x} {y} click {btn} keyup {k}")
                    if rc != 0:
                        raise RuntimeError(out.strip())
                else:
                    d.click(x, y, button)
                return {"ok": True, "result": "OK"}
            if action == "double_click":
                x, y = _coord(view, inp["coordinate"]) if inp.get("coordinate") else d.mouse_position()
                d.double_click(x, y)
                return {"ok": True, "result": "OK"}
            if action == "triple_click":
                x, y = _coord(view, inp["coordinate"]) if inp.get("coordinate") else d.mouse_position()
                d.triple_click(x, y)
                return {"ok": True, "result": "OK"}
            if action == "left_click_drag":
                x0, y0 = _coord(view, inp["start_coordinate"])
                x1, y1 = _coord(view, inp["coordinate"])
                d.drag(x0, y0, x1, y1)
                return {"ok": True, "result": "OK"}
            if action == "mouse_move":
                d.move(*_coord(view, inp["coordinate"]))
                return {"ok": True, "result": "OK"}
            if action in ("left_mouse_down", "left_mouse_up"):
                if d.name == "docker":
                    d.run("xdotool mousedown 1" if action == "left_mouse_down" else "xdotool mouseup 1")
                return {"ok": True, "result": "OK"}
            if action == "cursor_position":
                x, y = d.mouse_position()
                vx, vy = view.to_view(x, y)
                return {"ok": True, "result": f"[{vx}, {vy}]"}
            if action == "scroll":
                x, y = _coord(view, inp["coordinate"]) if inp.get("coordinate") else d.mouse_position()
                d.scroll(x, y, inp.get("scroll_direction", "down"), int(inp.get("scroll_amount", 3) or 3))
                return {"ok": True, "result": "OK"}
            if action == "type":
                d.type(inp.get("text", ""))
                return {"ok": True, "result": "OK"}
            if action == "key":
                d.key(inp["text"], int(inp.get("repeat", 1) or 1))
                return {"ok": True, "result": "OK"}
            if action == "hold_key":
                d.key(inp["text"])
                time.sleep(min(float(inp.get("duration", 1) or 1), 300))
                return {"ok": True, "result": "OK"}
            if action == "wait":
                time.sleep(min(float(inp.get("duration", 1) or 1), 300))
                return {"ok": True, "result": "OK"}
            return {"ok": False, "error": f"unknown action {action!r}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _zoom(t: Target, region, run_id: str | None) -> dict:
    from PIL import Image
    shot = t.desktop.screenshot()
    im = Image.open(io.BytesIO(shot.png)).convert("RGB")
    f = im.width / t.view.view_w
    x0, y0, x1, y1 = [int(round(float(v) * f)) for v in region]
    x0, x1 = max(0, min(x0, x1)), min(im.width, max(x0, x1))
    y0, y1 = max(0, min(y0, y1)), min(im.height, max(y0, y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise ValueError("zoom region too small")
    crop = im.crop((x0, y0, x1, y1))
    if crop.width > t.view.view_w or crop.height > t.view.view_h:
        crop.thumbnail((t.view.view_w, t.view.view_h))
    buf = io.BytesIO()
    crop.save(buf, format="PNG", optimize=True)
    out: dict[str, Any] = {"ok": True, "image": base64.b64encode(buf.getvalue()).decode(), "width": crop.width, "height": crop.height}
    if run_id:
        d = os.path.join(RUNS_DIR, run_id)
        os.makedirs(d, exist_ok=True)
        t.shots += 1
        path = os.path.join(d, f"zoom-{t.shots:03d}.png")
        crop.save(path)
        out["path"] = path
    return out


FRAME_TTL = float(os.environ.get("FLOWLINE_FRAME_TTL", "0.4"))


def frame_jpeg(t: Target, width: int = 960, quality: int = 72) -> tuple[bytes, float]:
    """Live frame of the desk as JPEG (scrot through the persistent helper), cached ~400 ms per target and width.

    Does not take `t.lock`: the helper pipe has its own lock, so a frame can be grabbed while the agent
    is between actions without delaying them; at worst it waits for one xdotool/scrot round trip.
    Returns (jpeg_bytes, age_seconds)."""
    from PIL import Image
    width = max(160, min(int(width or 960), 1920))
    now = time.time()
    with t._frame_lock:
        hit = t._frame.get(width)
        if hit and now - hit[0] < FRAME_TTL:
            return hit[1], now - hit[0]
        shot = t.desktop.screenshot()
        im = Image.open(io.BytesIO(shot.png)).convert("RGB")
        if im.width > width:
            im = im.resize((width, int(round(im.height * width / im.width))), Image.BILINEAR)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg = buf.getvalue()
        t._frame = {width: (time.time(), jpeg)}  # one width cached at a time; the grid and the big view rarely overlap
        return jpeg, 0.0


def warm(t: Target) -> dict:
    import lo
    if not isinstance(t.desktop, DockerDesktop):
        return {"warmed": False, "reason": "only desk containers run LibreOffice with the UNO socket"}
    with t.lock:
        return lo.warm(t.desktop)


def read_target_file(desktop: Desktop, path: str) -> bytes:
    if isinstance(desktop, DockerDesktop):
        return desktop.get_file(path)
    with open(os.path.expanduser(path), "rb") as f:
        return f.read()


def sheet_json(t: Target, path: str) -> dict:
    from sheet import read_sheet_bytes
    with t.lock:
        s = read_sheet_bytes(read_target_file(t.desktop, path))
    return {"items": [{"item": a, "amount": b} for a, b in s.items], "total": s.total,
            "sum_of_items": s.sum_items, "consistent": s.consistent()}


def deck_cells(t: Target, deck: str, slide: int) -> dict:
    import lo
    if not isinstance(t.desktop, DockerDesktop):
        raise RuntimeError("read_deck_cells needs the LibreOffice UNO bridge (desk containers only)")
    with t.lock:
        info = lo.uno(t.desktop, "cells", deck.rsplit("/", 1)[-1], str(slide))
    return {"rows": info["cells"], "amount_column": [r[-1] for r in info["cells"]], "modified": info["modified"]}
