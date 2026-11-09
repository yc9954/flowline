"""Voice-over per cut: text + target seconds. Writes out/timing.json.

usage: python3 vo.py [--voice Samantha] [--rate 165]
Real narration: vo_higgsfield.py writes out/vo/NN.wav (Eleven v4, voice Holden, tempo 1.15); this script prefers an
existing NN.wav and only synthesises the macOS `say` fallback (NN.aiff) when there is none.
Text for data-driven cuts is overridden by out/vo_text.json (supers_from_data.py).
"""
import argparse, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "vo")
os.makedirs(OUT, exist_ok=True)

# Story v3: problem → market → product → test case → THE SIMULATION (time-lapse) → demo: collect · learn · act
# (six desks live, then the whole runs at 50×) → results → close.
CUTS = {
    1: (9, "Small multi-site businesses run on processes nobody wrote down. Work waits more than it's worked, and when someone leaves, the process leaves too."),
    2: (7.1, "Six million small US firms. The tools that map work need system logs — they have none."),
    3: (8.5, "Not an ERP: a company-level agent. Approved days join one hub; it finds the bottleneck, proposes the fix, and does the work."),
    4: (5.5, "Our test case: Northwind Fitness, a simulated chain. Three gyms, eight people."),
    5: (3.6, "At six, each laptop drafts how the day went."),
    6: (4.6, "Personal things stay out. Nothing leaves until you approve it."),
    7: (5.7, "Approved records become one knowledge of how the business works — learned, not drawn."),
    8: (8, "A proposal takes a hundred and nine hours, eighty-five waiting. It tests nine fixes on the same team, same luck."),
    9: (5.5, "It never starts on its own. From the knowledge everyone built, it finds the bottleneck step and offers to take it — only to the person it affects."),
    10: (9.3, "Six people said yes once. Now, mid-work, Flowline clears the same bottleneck on six desks at once — quotes, sheets, decks, packets — each from the knowledge all six built together."),
    11: (8, "Every run ends as a proposal left on the person's desk to check. Nothing saved, nothing sent outside, without them. One knowledge, many hands."),
    12: (8, "Then we ran the whole chain for eleven simulated weeks — three hundred approved days, every hand-off, every wait — on a world engine, not a script."),
    13: (8.0, "Cycle time: a hundred and nine hours to eighty-eight. The test said ninety-one."),
    14: (8.4, "Ten of ten runs correct, zero leaks. On real Census data, its picks were 7.4 times as likely to get new gyms."),
    15: (4.7, "Flowline. The agent that runs your company's work — with your people."),
    16: (1.5, ""),  # end card, no voice
}


def load_overrides():
    p = os.path.join(HERE, "out", "vo_text.json")
    if os.path.exists(p):
        with open(p) as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}


def duration(path):
    r = subprocess.run(["afinfo", path], capture_output=True, text=True)
    m = re.search(r"estimated duration: ([0-9.]+) sec", r.stdout)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="Samantha")
    ap.add_argument("--rate", type=int, default=165)
    a = ap.parse_args()
    over = load_overrides()
    timing = {}
    for n, (target, text) in CUTS.items():
        text = over.get(n, text)
        human = os.path.join(OUT, f"{n:02d}.wav")
        aiff = os.path.join(OUT, f"{n:02d}.aiff")
        if not text:
            timing[n] = {"target_s": target, "vo_s": 0.0, "file": None, "text": ""}
            print(f"{n:02d}  target {target:>4}s  (no voice)")
            continue
        if os.path.exists(human):
            src = human
        else:
            subprocess.run(["say", "-v", a.voice, "-r", str(a.rate), "-o", aiff, text], check=True)
            src = aiff
        d = duration(src)
        timing[n] = {"target_s": target, "vo_s": d, "file": os.path.relpath(src, HERE), "text": text}
        flag = "" if d is None or d <= target else "  <- longer than the cut"
        print(f"{n:02d}  target {target:>4}s  vo {d:5.1f}s{flag}")
    with open(os.path.join(HERE, "out", "timing.json"), "w") as f:
        json.dump(timing, f, indent=2, ensure_ascii=False)
    total_vo = sum(v["vo_s"] or 0 for v in timing.values())
    total_cut = sum(max(v["target_s"], (v["vo_s"] or 0) + 0.4 if v["vo_s"] else v["target_s"]) for v in timing.values())
    print(f"total VO {total_vo:.1f}s · film at these targets {total_cut:.1f}s of 90s")


if __name__ == "__main__":
    main()
