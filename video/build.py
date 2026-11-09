"""Assemble the 90-second video from recorded cuts, the VO, and supers.

usage: python3 build.py [--music path.mp3] [--out out/flowline-90s.mp4]

Inputs
  out/cuts/NN.(webm|mov|mp4)  one recording per cut (board: Playwright WebM; mac: ffmpeg mov)
  out/vo/NN.(wav|aiff)        voice-over per cut (vo.py)
  out/timing.json             from vo.py
  supers.json                 cut → super text (written by this script's defaults, edited by hand or from data/out)

Each cut becomes a normalised segment: 1920×1080, 30 fps, duration = max(storyboard target, VO + 0.6 s),
super burned bottom-left for ≥ 2 s, VO starting 0.3 s in, then all segments are concatenated.
Mac recordings (3024×1964) are centre-cropped to 16:9 before scaling. Cuts marked `push` get a slow zoompan.
"""
import argparse, glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SEG = os.path.join(OUT, "segments")
FONT = os.path.join(HERE, "fonts", "InstrumentSans.ttf")
MONO = os.path.join(HERE, "fonts", "GeistMono.ttf")
os.makedirs(SEG, exist_ok=True)

DEFAULT_SUPERS = {
    1: "One knowledge. Five surfaces.",
    2: "Simulated team · on-device, nothing sent until approved",
    3: "Personal items never leave the laptop",
    4: "18 steps · 7 roles · 4 decisions · 4 loops — learned, not drawn",
    5: "19 h waiting · 18 min of work",
    6: "Same team. Same luck. Nine plans.",
    7: "Asked only of the person it affects · 41 s vs 22 min",
    8: "50 h → 29.4 h · the test predicted 29.0",
    9: "US Census · 26,011 ZIP codes · clock frozen at 2020",
    10: "Opening 18 days sooner",
    11: "Flowline — one knowledge, many surfaces",
}
# cut → (zoom_from, zoom_to) applied linearly over the segment; None = static
PUSH = {}  # no slow pushes: zoompan rounds the crop origin per frame, which reads as a shake at small zoom levels
MENUBAR_FRACTION = 50 / 1964
START = json.load(open(os.path.join(OUT, "start.json"))) if os.path.exists(os.path.join(OUT, "start.json")) else {}
START = {int(k): float(v) for k, v in START.items()}  # seconds to skip at the head of a recording (out/start.json, e.g. {"10": 95})
SUB_BAND = {11, 12}  # the wall: letterbox the bottom so the subtitle never covers the desk labels
FADE_OUT = {16}
FADE_IN = {1, 16}


def ff(*args):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,duration", "-of", "json", path], capture_output=True, text=True)
    j = json.loads(r.stdout)["streams"][0]
    d = j.get("duration")
    if d is None:  # webm often lacks stream duration
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                           capture_output=True, text=True)
        d = json.loads(r.stdout)["format"]["duration"]
    return int(j["width"]), int(j["height"]), float(d)


def find(pattern):
    m = sorted(glob.glob(pattern))
    return m[0] if m else None


def esc(t):
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def super_png(text, path, max_w=1500):
    """Render a centred subtitle (Instrument Sans 36px, white on black 78%, wrapped to max_w) to a PNG; returns (w, h)."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(FONT, 36)
    pad_x, pad_y, gap = 26, 16, 8
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if tmp.textbbox((0, 0), trial, font=font)[2] > max_w - 2 * pad_x and cur:
            lines.append(cur); cur = wd
        else:
            cur = trial
    if cur:
        lines.append(cur)
    boxes = [tmp.textbbox((0, 0), ln, font=font) for ln in lines]
    lh = max(b[3] - b[1] for b in boxes) + gap
    w = max(b[2] - b[0] for b in boxes) + 2 * pad_x
    h = lh * len(lines) - gap + 2 * pad_y
    im = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * 0.78)))
    d = ImageDraw.Draw(im)
    y = pad_y
    for ln, bx in zip(lines, boxes):
        d.text(((w - (bx[2] - bx[0])) / 2 - bx[0], y - bx[1]), ln, font=font, fill=(255, 255, 255, 255))
        y += lh
    im.save(path)
    return w, h


def segment(n, cut, vo, dur, super_text, vo_s=None):
    still = cut.lower().endswith(".png")
    if still:
        from PIL import Image
        w, h = Image.open(cut).size
        src_dur = dur
    else:
        w, h, src_dur = probe(cut)
    vf = []
    if abs(w / h - 16 / 9) > 0.02:  # Retina Mac capture → crop to 16:9 just below the menu bar (its clock is the real time, in Korean)
        ch = int(w * 9 / 16)
        menubar = int(h * MENUBAR_FRACTION)
        vf.append(f"crop={w}:{ch}:0:{min(menubar, h - ch)}")
    vf.append("scale=1920:960:flags=lanczos,pad=1920:1080:0:0:black,fps=30,format=yuv420p" if n in SUB_BAND else "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p")
    src_dur -= START.get(n, 0.0)
    if src_dur < dur:  # hold the last frame
        vf.append(f"tpad=stop_mode=clone:stop_duration={dur - src_dur + 0.5:.2f}")
    if n in PUSH:
        z0, z1 = PUSH[n]
        frames = int(dur * 30)
        vf.append(f"zoompan=z='{z0}+({z1}-{z0})*on/{frames}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30")
    vf.append(f"trim=0:{dur:.3f},setpts=PTS-STARTPTS")
    inputs = (["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", cut] if still else
              (["-ss", f"{START[n]:.2f}", "-i", cut] if n in START else ["-i", cut]))
    if vo:
        inputs += ["-i", vo]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    graph = f"[0:v]{','.join(vf)}[v0]"
    last = "[v0]"
    if super_text:
        png = os.path.join(SEG, f"{n:02d}_super.png")
        super_png(super_text, png)
        inputs += ["-loop", "1", "-i", png]
        show = max(1.5, min(dur - 0.3, (vo_s or dur) + 0.4))   # the subtitle stays while the line is spoken
        graph += f";{last}[2:v]overlay=(W-w)/2:H-64-h:enable='between(t,0.3,{0.3 + show:.2f})':shortest=1[v1]"
        last = "[v1]"
    if n in FADE_OUT or n in FADE_IN:
        fades = []
        if n in FADE_IN:
            fades.append("fade=t=in:st=0:d=0.5")
        if n in FADE_OUT:
            fades.append(f"fade=t=out:st={dur - 0.8:.2f}:d=0.8")
        graph += f";{last}{','.join(fades)}[v2]"
        last = "[v2]"
    graph += f";[1:a]adelay=300|300,apad,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a]"
    seg = os.path.join(SEG, f"{n:02d}.mp4")
    ff(*inputs, "-filter_complex", graph, "-map", last, "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
       "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", seg)
    return seg, dur


TIMELAPSE = {12: (11, 50, 420)}  # cut 12 = the whole 7-minute wall take (cut 11's recording) at 50×


def make_timelapses():
    for dst, (src, speed, end_s) in TIMELAPSE.items():
        s = find(os.path.join(OUT, "cuts", f"{src:02d}.*"))
        d = os.path.join(OUT, "cuts", f"{dst:02d}.mp4")
        if not s or s.endswith(".png"):
            continue
        if os.path.exists(d) and os.path.getmtime(d) > os.path.getmtime(s):
            continue
        skip = START.get(src, 0.0)
        ff("-ss", f"{skip:.2f}", "-t", f"{end_s:.1f}", "-i", s, "-an", "-vf", f"setpts=PTS/{speed},fps=30", "-c:v", "libx264", "-preset", "fast", "-crf", "18", d)
        print(f"cut {dst:02d}: time-lapse of {os.path.basename(s)} at {speed}x")


def main():
    make_timelapses()
    ap = argparse.ArgumentParser()
    ap.add_argument("--music")
    ap.add_argument("--out", default=os.path.join(OUT, "flowline-90s.mp4"))
    ap.add_argument("--only", type=int, nargs="*", help="build only these cuts (debug)")
    a = ap.parse_args()
    timing = {int(k): v for k, v in json.load(open(os.path.join(OUT, "timing.json"))).items()}
    sp = os.path.join(HERE, "supers.json")
    if not os.path.exists(sp):
        json.dump({str(k): v for k, v in DEFAULT_SUPERS.items()}, open(sp, "w"), indent=2, ensure_ascii=False)
    supers = {int(k): v for k, v in json.load(open(sp)).items()}
    segs, total = [], 0.0
    for n in sorted(timing):
        if a.only and n not in a.only:
            continue
        cut = find(os.path.join(OUT, "cuts", f"{n:02d}.*"))
        if not cut:
            print(f"cut {n:02d}: no recording in out/cuts — skipped", file=sys.stderr)
            continue
        vo = find(os.path.join(OUT, "vo", f"{n:02d}.wav")) or find(os.path.join(OUT, "vo", f"{n:02d}.aiff"))
        dur = max(timing[n]["target_s"], (timing[n]["vo_s"] or 0) + 0.4)  # VO starts at 0.3 s
        seg, d = segment(n, cut, vo, dur, timing[n]["text"] or "", timing[n]["vo_s"])   # subtitle = the narration line
        segs.append(seg); total += d
        print(f"cut {n:02d}: {d:4.1f}s  {os.path.basename(cut)}")
    lst = os.path.join(SEG, "list.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    if a.music and os.path.exists(a.music):
        ff("-f", "concat", "-safe", "0", "-i", lst, "-i", a.music, "-filter_complex",
           f"[1:a]volume=-18dB,afade=t=out:st={total - 2:.2f}:d=2,atrim=0:{total:.2f}[m];[0:a][m]amix=inputs=2:duration=first[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", a.out)
    else:
        ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", a.out)
    print(f"wrote {a.out}  ({total:.1f}s)")


if __name__ == "__main__":
    main()
