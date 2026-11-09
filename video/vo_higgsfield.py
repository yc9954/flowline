"""Generate the voice-over with Higgsfield (Eleven v4) and drop it in as out/vo/NN.wav, where vo.py picks it up.

usage: python3 vo_higgsfield.py [--cuts 1 2 ...] [--voice Holden] [--force]

Uses the `higgsfield` CLI (already logged in, workspace selected). Text comes from vo.py's CUTS with the
out/vo_text.json overrides, exactly as vo.py uses it. Existing out/vo/NN.wav are kept unless --force.
"""
import argparse, json, os, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "vo")
sys.path.insert(0, HERE)
from vo import CUTS, load_overrides  # noqa: E402

VOICES = {  # Higgsfield preset voices (higgsfield voices list)
    "Holden": "3c9d6053-6334-592c-8997-4e325286af3f",
    "Isla": "7367e919-3069-5a0b-939e-dfb1c0fd91b4",
    "Reid": "66469f5a-10db-586a-bab1-72f6ee66ba69",
}


def generate(text, voice_id):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump([{"text": text, "voice_type": "preset", "voice_id": voice_id}], f)
        dialogue = f.name
    r = subprocess.run(["higgsfield", "generate", "create", "elevenlabs_v4", "--dialogue", f"@{dialogue}", "--wait", "--wait-timeout", "2m", "--json"],
                       capture_output=True, text=True)
    os.unlink(dialogue)
    if r.returncode != 0:
        raise SystemExit(f"higgsfield failed: {r.stderr.strip() or r.stdout.strip()}")
    s = r.stdout
    # the result URL is the generated file (the voice's own preview URL also appears; skip it)
    urls = [u for u in __import__("re").findall(r'https?://[^"\s]+\.mp3', s) if "/audio_voice/" not in u]
    if not urls:
        raise SystemExit(f"no mp3 url in result: {s[:400]}")
    return urls[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuts", type=int, nargs="*")
    ap.add_argument("--voice", default="Holden")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tempo", type=float, default=1.2, help="atempo applied to the narration (Holden reads ~2.9 words/s; 1.08 keeps the pitch and is barely audible)")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    over = load_overrides()
    voice_id = VOICES[a.voice]
    for n, (target, text) in sorted(CUTS.items()):
        if a.cuts and n not in a.cuts:
            continue
        text = over.get(n, text)
        if not text:
            continue
        wav = os.path.join(OUT, f"{n:02d}.wav")
        if os.path.exists(wav) and not a.force:
            print(f"{n:02d}  kept {os.path.relpath(wav, HERE)}")
            continue
        url = generate(text, voice_id)
        mp3 = wav[:-4] + ".mp3"
        urllib.request.urlretrieve(url, mp3)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp3, "-af", f"atempo={a.tempo}", "-ar", "48000", "-ac", "2", wav], check=True)
        os.unlink(mp3)
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav],
                           capture_output=True, text=True).stdout.strip()
        print(f"{n:02d}  {float(d):5.1f}s  target {target}s  {a.voice}: {text[:60]}")


if __name__ == "__main__":
    main()
