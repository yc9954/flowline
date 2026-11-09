"""Observer daemon for a desk container: one Event (SCHEMA §1) per second.

Inside the container a shell loop prints `<epoch>\t<title>\t<WM_CLASS>\t<mouse>` once
a second (one docker exec pipe, so the ~0.3 s ssh round trip is paid once);
this process turns each line into an Event:

  Event { ts, app, title_hash, title_masked?, file_hint?, idle_s, url_host? }
  + private: "personal_chat"|"banking"|null   (device-only hint for the compiler)

Idle: `xprintidle` when present, else seconds since the title or pointer last changed.
Chat/bank windows (privacy denylist) keep only app/private/idle - no title, no hash.

Output: data/runs/observer/<container>/<date>.jsonl (append).

    uv run python observer.py --container desk1 --duration 600 [--time-scale 10]

`--time-scale` stretches timestamps (ts = start + scale × real elapsed) so a day
played by the actor at --speed 10 is recorded as a day; idle_s is scaled too.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from desktop import DEFAULT_HOST, DockerDesktop
from privacy import app_from_wm_class, app_label, classify_private, file_hint, mask_title, title_hash

from runs import RUNS_DIR

OBS_DIR = os.environ.get("FLOWLINE_OBS_DIR", os.path.join(RUNS_DIR, "observer"))

_SAMPLER = r'''
command -v xprintidle >/dev/null 2>&1 && HAVE_IDLE=1 || HAVE_IDLE=0
while true; do
  w=$(xdotool getactivewindow 2>/dev/null)
  if [ -n "$w" ]; then
    t=$(xdotool getwindowname "$w" 2>/dev/null | tr '\t\n' '  ')
    c=$(xprop -id "$w" WM_CLASS 2>/dev/null | sed 's/^[^=]*= *//' | tr '\t\n' '  ')
  else t=""; c=""; fi
  m=$(xdotool getmouselocation 2>/dev/null | awk '{print $1","$2}')
  if [ "$HAVE_IDLE" = 1 ]; then i=$(xprintidle 2>/dev/null); else i=""; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date +%s.%N)" "$t" "$c" "$m" "$i"
  sleep 1
done
'''


class Observer:
    def __init__(self, container: str = "desk1", host: str | None = None, out_dir: str = OBS_DIR,
                 time_scale: float = 1.0, origin: float | None = None, fresh: bool = False):
        """`origin`: real epoch at which the scaled clock equals real time
        (share it with the actor so both clocks agree); default = first sample."""
        self.desktop = DockerDesktop(container, host=host, persistent=False)
        self.container = container
        self.out_dir = os.path.join(out_dir, container)
        os.makedirs(self.out_dir, exist_ok=True)
        self.time_scale = time_scale
        self.start_real = origin
        self.start_ts = origin
        self._proc = None
        self._stop = threading.Event()
        self._last_title = None
        self._last_mouse = None
        self._last_change_real = None
        self.n_events = 0
        self.path = None
        self.events: list[dict] = []
        self.fresh = fresh  # truncate the day file first (measurement runs)

    def scaled_ts(self, real: float) -> float:
        return self.start_ts + (real - self.start_real) * self.time_scale

    def _event(self, real: float, title: str, wm_class: str, mouse: str, idle_ms: str) -> dict:
        if self._last_change_real is None:
            self._last_change_real = real
        if title != self._last_title or mouse != self._last_mouse:
            self._last_change_real = real
        self._last_title, self._last_mouse = title, mouse
        if idle_ms.strip().isdigit():
            idle_real = int(idle_ms) / 1000.0
        else:
            idle_real = real - self._last_change_real
        app_raw = app_from_wm_class(wm_class)
        app = app_label(app_raw, title)
        private = classify_private(app_raw, title)
        ts = datetime.fromtimestamp(self.scaled_ts(real), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        ev = {"ts": ts, "app": app, "idle_s": round(idle_real * self.time_scale, 1), "private": private}
        if private:
            ev["title_hash"] = ""  # denylisted: nothing about the window leaves the sampler
            ev["title_masked"] = ""
        else:
            ev["title_hash"] = title_hash(title)
            ev["title_masked"] = mask_title(title)
            fh = file_hint(title)
            if fh:
                ev["file_hint"] = fh
        return ev

    def run(self, duration: float | None = None, quiet: bool = False) -> str:
        day = datetime.now().strftime("%Y-%m-%d")
        self.path = os.path.join(self.out_dir, f"{day}.jsonl")
        b64 = base64.b64encode(_SAMPLER.encode()).decode()
        boot = f"echo {b64} | base64 -d > /tmp/flowline_sampler.sh; exec sh /tmp/flowline_sampler.sh"
        # binary pipe: window titles may be Latin-1 STRING properties (xmessage's "·"), not UTF-8
        self._proc = subprocess.Popen(self.desktop._exec_argv(True, boot), stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, bufsize=0)
        t_end = time.time() + duration if duration else None
        with open(self.path, "w" if self.fresh else "a", encoding="utf-8") as f:
            while not self._stop.is_set():
                if t_end and time.time() > t_end:
                    break
                raw = self._proc.stdout.readline()
                if not raw:
                    break
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw.decode("latin-1")
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                try:
                    real = float(parts[0])
                except ValueError:
                    continue
                if self.start_real is None:
                    self.start_real = real
                    if self.start_ts is None:
                        self.start_ts = real
                ev = self._event(real, parts[1], parts[2], parts[3], parts[4])
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                f.flush()
                self.events.append(ev)
                self.n_events += 1
                if not quiet and self.n_events % 10 == 0:
                    print(f"[observer] {self.n_events} events, last: {ev['app']} {ev.get('title_masked', '')[:50]!r} idle={ev['idle_s']}",
                          file=sys.stderr)
        self.stop()
        return self.path

    def stop(self):
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        # the sampler loop inside the container keeps running after the pipe closes; kill it
        try:
            self.desktop.sh("pkill -f flowline_sampler.sh; true")
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="desk1")
    ap.add_argument("--host", default=DEFAULT_HOST, help="ssh host of the docker engine, or 'local'")
    ap.add_argument("--duration", type=float, default=None, help="seconds (default: until Ctrl-C)")
    ap.add_argument("--time-scale", type=float, default=1.0)
    ap.add_argument("--out", default=OBS_DIR)
    ap.add_argument("--origin", type=float, default=None, help="epoch seconds shared with the actor's clock")
    args = ap.parse_args()
    obs = Observer(args.container, args.host, args.out, args.time_scale, origin=args.origin)
    signal.signal(signal.SIGINT, lambda *a: obs.stop())
    signal.signal(signal.SIGTERM, lambda *a: obs.stop())
    path = obs.run(args.duration)
    print(json.dumps({"path": path, "events": obs.n_events}))


if __name__ == "__main__":
    main()
