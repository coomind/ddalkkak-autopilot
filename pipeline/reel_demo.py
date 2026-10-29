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


def schedule(spec):
    prompt = spec["prompt"].replace("**", "")
    s = {"type_start": 0.6}
    dur = min(max(len(prompt) / 26.0, 1.8), 3.4)
    s["type_end"] = s["type_start"] + dur
    s["send"] = s["type_end"] + 0.3
    t = s["send"] + 0.95
    s["lines"] = []
    for r in spec["response"]:
        s["lines"].append(round(t, 3))
        t += 1.25 if r.get("style") in ("big", "note") else 0.95
    s["payoff"] = round(t + 1.1, 3)
    s["end"] = round(s["payoff"] + float(spec.get("payoff_hold", 3.6)), 3)
    return s


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
    s = schedule(spec)
    data = dict(spec, schedule=s, handle=CONFIG["handle"])
    page_html = (ROOT / "templates" / "demo.html").read_text(encoding="utf-8")
    page_html = page_html.replace("__FONT__", (ROOT / "fonts" / "PretendardVariable.woff2").as_uri())
    page_html = page_html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    tmp_html = out / "_demo.html"
    tmp_html.write_text(page_html, encoding="utf-8")

    wav = out / "_audio.wav"
    audio.write_wav(wav, audio.make_track(s["end"], events(spec, s), seed=int(spec.get("music_seed", 0))))

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
