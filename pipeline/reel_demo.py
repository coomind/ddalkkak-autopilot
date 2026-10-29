#!/usr/bin/env python3
"""Render a "screen demo" reel: hook on top, an AI chat window where the prompt is typed
and the answer streams in, then a payoff card. No voice; lo-fi beat + UI sounds.

Usage: python3 pipeline/reel_demo.py posts/<id>/spec.json
Output: posts/<id>/out/reel/reel.mp4 and cover.jpg
"""
import json, sys, subprocess, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import audio  # noqa: E402

CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
FPS = 30


def _chunks(text, maxlen=15):
    """Split a subtitle line into short on-screen chunks. '/' forces a break."""
    out = []
    for part in [p.strip() for p in text.split("/") if p.strip()]:
        words, cur = part.split(" "), ""
        for w in words:
            plain = (cur + " " + w).replace("**", "").strip()
            if cur and len(plain) > maxlen:
                out.append(cur.strip()); cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
    # keep **bold** balanced per chunk
    fixed = []
    carry = False
    for c in out:
        if carry:
            c = "**" + c
        carry = c.count("**") % 2 == 1
        if carry:
            c = c + "**"
        fixed.append(c)
    return fixed


def narrate(spec):
    """Synthesize narration segments. Returns (segments with t0/t1, mono float32 array @SR)."""
    import numpy as np
    from supertonic import TTS
    vcfg = CONFIG.get("voice", {})
    tts = TTS(auto_download=True)
    style = tts.get_voice_style(voice_name=spec.get("voice", vcfg.get("voice", "M1")))
    speed = float(spec.get("voice_speed", vcfg.get("speed", 1.15)))
    sr = getattr(tts, "sample_rate", audio.SR)
    segs, pieces, t = [], [], 0.0
    gap = 0.18
    for seg in spec["narration"]:
        wav, _ = tts.synthesize(seg["say"], voice_style=style, lang="ko", speed=speed, total_steps=10)
        wav = np.asarray(wav, dtype=np.float32).squeeze()
        if sr != audio.SR:
            idx = np.linspace(0, len(wav) - 1, int(len(wav) * audio.SR / sr))
            wav = np.interp(idx, np.arange(len(wav)), wav).astype(np.float32)
        # trim leading/trailing silence
        nz = np.where(np.abs(wav) > 0.01)[0]
        if len(nz):
            wav = wav[max(0, nz[0] - 600): nz[-1] + 2000]
        d = len(wav) / audio.SR
        segs.append(dict(seg, t0=round(t, 3), t1=round(t + d, 3)))
        pieces.append((t, wav))
        t += d + gap
    total = t
    voice = np.zeros(int((total + 3) * audio.SR), np.float32)
    for t0, w in pieces:
        i = int(t0 * audio.SR); voice[i:i + len(w)] += w
    voice /= (np.max(np.abs(voice)) + 1e-9)
    return segs, voice


def schedule(spec, segs=None):
    prompt = spec["prompt"].replace("**", "")
    n_lines = len(spec["response"])
    dur_type = min(max(len(prompt) / 26.0, 1.8), 3.4)
    if not segs:
        s = {"type_start": 0.6}
        s["type_end"] = s["type_start"] + dur_type
        s["send"] = s["type_end"] + 0.3
        t = s["send"] + 0.95
        s["lines"] = []
        for r in spec["response"]:
            s["lines"].append(round(t, 3))
            t += 1.25 if r.get("style") in ("big", "note") else 0.95
        s["payoff"] = round(t + 1.1, 3)
        s["end"] = round(s["payoff"] + float(spec.get("payoff_hold", 3.6)), 3)
        return s
    by = {}
    for g in segs:
        by.setdefault(g["cue"], []).append(g)
    s = {}
    ty = by.get("type", segs[1:2])[0]
    s["type_start"] = round(ty["t0"] + 0.1, 3)
    s["type_end"] = round(s["type_start"] + dur_type, 3)
    s["send"] = round(s["type_end"] + 0.3, 3)
    ans = by.get("answer", [])
    a0 = max(ans[0]["t0"] if ans else s["send"] + 0.9, s["send"] + 0.9)
    a1 = ans[-1]["t1"] if ans else a0 + n_lines
    note_seg = by.get("note", [None])[0]
    main_lines = [i for i, r in enumerate(spec["response"]) if r.get("style") != "note"]
    note_lines = [i for i, r in enumerate(spec["response"]) if r.get("style") == "note"]
    lines = [0.0] * n_lines
    step = min(max((a1 - a0) / max(len(main_lines), 1), 0.55), 1.3)
    for k, i in enumerate(main_lines):
        lines[i] = round(a0 + k * step, 3)
    nt = max(note_seg["t0"] if note_seg else a1, (lines[main_lines[-1]] + 0.6) if main_lines else a0)
    for k, i in enumerate(note_lines):
        lines[i] = round(nt + k * 0.8, 3)
    s["lines"] = lines
    cta = by.get("cta", [segs[-1]])[0]
    s["payoff"] = round(max(cta["t0"] - 0.1, max(lines) + 0.8), 3)
    s["end"] = round(segs[-1]["t1"] + 1.3, 3)
    return s


def subtitles(segs):
    subs = []
    for g in segs:
        chunks = _chunks(g.get("sub", g["say"]))
        total = sum(len(c.replace("**", "")) for c in chunks) or 1
        t = g["t0"]
        span = g["t1"] - g["t0"]
        for c in chunks:
            d = span * len(c.replace("**", "")) / total
            subs.append({"t0": round(t, 3), "t1": round(t + d, 3), "text": c})
            t += d
    return subs


def events(spec, s):
    ev = []
    prompt = spec["prompt"].replace("**", "")
    n = len(prompt)
    step = (s["type_end"] - s["type_start"]) / max(n, 1)
    k = 0
    for i in range(n):
        if prompt[i] == " ":
            continue
        k += 1
        if k % 2 == 0:  # every other char keeps it crisp, not machine-gun
            ev.append((s["type_start"] + i * step, "key"))
    ev.append((s["send"], "send"))
    for t in s["lines"]:
        ev.append((t, "pop"))
    ev.append((s["payoff"] - 0.25, "whoosh"))
    ev.append((s["payoff"] + 0.15, "ding"))
    return ev


def main():
    spec_path = Path(sys.argv[1]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out = spec_path.parent / "out" / "reel"
    out.mkdir(parents=True, exist_ok=True)
    segs, voice = (None, None)
    if spec.get("narration") and CONFIG.get("voice", {}).get("engine") == "supertonic" and not spec.get("no_voice"):
        segs, voice = narrate(spec)
    s = schedule(spec, segs)
    data = dict(spec, schedule=s, handle=CONFIG["handle"], subs=subtitles(segs) if segs else [])
    page_html = (ROOT / "templates" / "demo.html").read_text(encoding="utf-8")
    page_html = page_html.replace("__FONT__", (ROOT / "fonts" / "PretendardVariable.woff2").as_uri())
    page_html = page_html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    tmp_html = out / "_demo.html"
    tmp_html.write_text(page_html, encoding="utf-8")

    wav = out / "_audio.wav"
    audio.write_wav(wav, audio.make_track(s["end"], events(spec, s), seed=int(spec.get("music_seed", 0)), voice=voice))

    from playwright.sync_api import sync_playwright
    nframes = int(math.ceil(s["end"] * FPS))
    mp4 = out / "reel.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
        "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(mp4)],
        stdin=subprocess.PIPE)
    cover_t = spec.get("cover_t", s["lines"][-1] + 0.5)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.goto(tmp_html.as_uri())
        pg.wait_for_function("document.fonts.status === 'loaded'")
        pg.wait_for_timeout(200)
        for i in range(nframes):
            pg.evaluate(f"render({i / FPS})")
            ff.stdin.write(pg.screenshot(type="jpeg", quality=92))
        pg.evaluate(f"render({cover_t}); document.getElementById('bar').style.display='none'")
        pg.screenshot(path=str(out / "cover.jpg"), type="jpeg", quality=92)
        for name, t in spec.get("qa_frames", {"qa_0": 0.05, "qa_type": s["type_end"] - 0.4,
                                               "qa_mid": s["lines"][len(s["lines"]) // 2] + 0.4,
                                               "qa_pay": s["payoff"] + 1.0}).items():
            pg.evaluate(f"document.getElementById('bar').style.display=''; render({t})")
            pg.screenshot(path=str(out / f"{name}.jpg"), type="jpeg", quality=80)
        b.close()
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("ffmpeg failed")
    tmp_html.unlink(); wav.unlink()
    print(json.dumps({"reel": str(mp4), "duration": s["end"], "frames": nframes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
