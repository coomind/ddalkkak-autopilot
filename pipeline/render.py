#!/usr/bin/env python3
"""
Render one post spec into:
  out/carousel/01.png ... (1080x1350, Instagram 4:5 carousel)
  out/reel/reel.mp4      (1080x1920, 9:16 reel with TTS narration)
  out/reel/cover.jpg     (reel cover = first frame)

Usage: python3 pipeline/render.py posts/<id>/spec.json [--no-reel] [--no-voice]
"""
import json, sys, os, re, html, subprocess, shutil, tempfile, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = (ROOT / "fonts" / "PretendardVariable.woff2").as_uri()
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def md(text: str) -> str:
    """Tiny markup: **word** -> highlighted, newline -> <br>."""
    t = html.escape(text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r'<mark>\1</mark>', t)
    return t.replace("\n", "<br>")


CSS = """
@font-face { font-family: 'Pretendard'; src: url('%(font)s') format('woff2'); font-weight: 100 900; }
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:%(w)dpx; height:%(h)dpx; }
body { font-family:'Pretendard',sans-serif; background:%(bg)s; color:%(ink)s;
       letter-spacing:-0.03em; word-break:keep-all; overflow:hidden; }
.frame { position:absolute; inset:0; padding:%(pad_top)dpx %(pad_x)dpx %(pad_bottom)dpx; display:flex; flex-direction:column; }
.top { display:flex; justify-content:space-between; align-items:center; font-size:30px; font-weight:700; }
.tag { background:%(ink)s; color:%(bg)s; padding:10px 22px; border-radius:999px; }
.count { color:%(muted)s; }
.body { flex:1; display:flex; flex-direction:column; justify-content:center; gap:%(gap)dpx; }
.kicker { font-size:40px; font-weight:800; color:%(accent)s; }
h1 { font-size:%(h1)dpx; line-height:1.18; font-weight:900; }
h2 { font-size:%(h2)dpx; line-height:1.22; font-weight:850; }
.num { font-size:40px; font-weight:900; color:%(accent)s; }
p, li { font-size:%(p)dpx; line-height:1.5; font-weight:500; color:%(ink2)s; }
mark { background:none; color:%(mark)s; padding:0; }
.prompt { background:%(panel)s; border:2px solid %(panel_line)s; color:#F2F2F6; border-radius:28px; padding:62px 50px 50px; font-size:%(prompt)dpx; line-height:1.55; font-weight:500; position:relative; }
.prompt .label { position:absolute; top:-22px; left:36px; background:%(mark)s; color:#0B0B0D; font-size:26px; font-weight:800; padding:8px 18px; border-radius:999px; }
ul { list-style:none; display:flex; flex-direction:column; gap:22px; }
li { display:flex; gap:18px; align-items:flex-start; }
li .ck { flex:none; width:46px; height:46px; border-radius:12px; background:%(accent)s; color:#0B0B0D; font-weight:900; display:flex; align-items:center; justify-content:center; font-size:28px; margin-top:6px; }
.bottom { display:flex; justify-content:space-between; align-items:center; font-size:30px; font-weight:700; color:%(muted)s; }
.swipe { color:%(ink)s; }
.bignum { position:absolute; right:60px; top:%(bn_top)dpx; font-size:300px; font-weight:900; line-height:1; color:transparent; -webkit-text-stroke:4px %(accent)s; opacity:.28; }
.cta-box { border:4px solid %(ink)s; border-radius:32px; padding:40px 44px; display:flex; flex-direction:column; gap:20px; }
.cta-row { font-size:%(p)dpx; font-weight:700; }
.rv.off { visibility:hidden; }
.sub { font-size:%(sub)dpx; font-weight:600; color:%(ink2)s; line-height:1.4; }
"""


def slide_html(s, idx, total, w, h, reel=False):
    c = CONFIG["design"]
    scale = dict(
        w=w, h=h, font=FONT, bg=c["bg"], ink=c["ink"], ink2=c["ink2"], muted=c["muted"],
        accent=c["accent"], mark=c["mark"], panel=c.get("panel","#17171C"), panel_line=c.get("panel_line","#2A2A31"), pad_x=84,
        pad_top=300 if reel else 80, bn_top=340 if reel else 110, pad_bottom=330 if reel else 80,
        gap=48 if reel else 40, h1=128 if reel else 112, h2=100 if reel else 88,
        p=58 if reel else 46, prompt=48 if reel else 42, sub=56 if reel else 50,
    )
    css = CSS % scale
    handle = html.escape(CONFIG["handle"])
    tag = html.escape(s.get("tag") or CONFIG.get("series_default", "AI 꿀팁"))
    t = s["type"]
    count = f"{idx+1}/{total}"
    inner = ""
    if t == "cover":
        inner = f"""
        {f'<div class="kicker rv" data-s="1">{md(s.get("kicker"))}</div>' if s.get("kicker") else ''}
        <h1 class="rv" data-s="1">{md(s["title"])}</h1>
        {f'<div class="sub rv" data-s="2">{md(s.get("sub"))}</div>' if s.get("sub") else ''}"""
    elif t in ("step", "prompt"):
        num = f'<div class="num rv" data-s="1">STEP {s["num"]}</div>' if s.get("num") else ""
        body = f'<p class="rv" data-s="2">{md(s.get("body"))}</p>' if s.get("body") else ""
        ps = 3 if s.get("body") else 2
        prompt = (f'<div class="prompt rv" data-s="{ps}"><span class="label">복붙 프롬프트</span>{md(s["prompt"])}</div>'
                  if s.get("prompt") else "")
        big = f'<div class="bignum">{int(s["num"]):02d}</div>' if s.get("num") else ""
        inner = f"{big}{num}<h2 class=\"rv\" data-s=\"1\">{md(s['title'])}</h2>{body}{prompt}"
    elif t == "checklist":
        items = "".join(f'<li class="rv" data-s="{k+2}"><span class="ck">✓</span><span>{md(i)}</span></li>'
                        for k, i in enumerate(s["items"]))
        inner = f"<h2 class=\"rv\" data-s=\"1\">{md(s['title'])}</h2><ul>{items}</ul>"
    elif t == "cta":
        rows = "".join(f'<div class="cta-row">{md(r)}</div>' for r in s.get("rows", []))
        inner = f"""<h2 class="rv" data-s="1">{md(s['title'])}</h2>
        {f'<div class="sub rv" data-s="2">{md(s.get("sub"))}</div>' if s.get("sub") else ''}
        {f'<div class="cta-box rv" data-s="3">{rows}</div>' if rows else ''}"""
    else:
        raise ValueError(f"unknown slide type {t}")
    swipe = '<span class="swipe">넘겨서 보기 →</span>' if (t == "cover" and not reel) else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>
<body><div class="frame">
  <div class="top"><span class="tag">{tag}</span><span class="count">{'' if reel else count}</span></div>
  <div class="body">{inner}</div>
  <div class="bottom"><span>{handle}</span>{swipe}</div>
</div></body></html>"""


def render_pngs(spec, outdir: Path, w, h, reel):
    from playwright.sync_api import sync_playwright
    outdir.mkdir(parents=True, exist_ok=True)
    slides = spec["slides"]
    paths = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": w, "height": h})
        for i, s in enumerate(slides):
            page.set_content(slide_html(s, i, len(slides), w, h, reel=reel), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            if not reel:
                f = outdir / f"{i+1:02d}.png"
                page.screenshot(path=str(f))
                paths.append(f)
                continue
            # reel: kinetic reveal -> one frame per reveal step (elements pop in one after another)
            nmax = page.evaluate("Math.max(1,...[...document.querySelectorAll('.rv')].map(e=>+e.dataset.s))")
            states = []
            for k in range(1, nmax + 1):
                page.evaluate(f"document.querySelectorAll('.rv').forEach(e=>e.classList.toggle('off', +e.dataset.s>{k}))")
                f = outdir / f"{i+1:02d}_{k}.png"
                page.screenshot(path=str(f))
                states.append(f)
            paths.append(states)
        b.close()
    return paths


def tts(text, out_mp3: Path):
    from gtts import gTTS
    raw = out_mp3.with_suffix(".raw.mp3")
    gTTS(text, lang="ko").save(str(raw))
    tempo = CONFIG["voice"].get("tempo", 1.25)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter:a",
                    f"atempo={tempo}", "-ar", "44100", "-ac", "2", str(out_mp3)], check=True)
    raw.unlink()


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render_reel(spec, outdir: Path, voice=True):
    frames = render_pngs(spec, outdir / "frames", 1080, 1920, reel=True)
    tmp = Path(tempfile.mkdtemp())
    segs = []
    fps = 30
    for i, (s, states) in enumerate(zip(spec["slides"], frames)):
        line = s.get("voice")
        aud = None
        if voice and line:
            aud = tmp / f"a{i}.mp3"
            tts(line, aud)
            dur = duration(aud) + 0.35
        else:
            dur = s.get("seconds", 2.5)
        if i == 0:
            dur = max(dur, 1.8)  # hook frame visible from 0s
        # split slide time across reveal states: first state 35%, rest equal (each >= 0.5s)
        ns = len(states)
        if ns == 1:
            parts = [dur]
        else:
            first = max(0.6, dur * 0.35)
            rest = max(0.5, (dur - first) / (ns - 1))
            parts = [first] + [rest] * (ns - 1)
        lst_s = tmp / f"st{i}.txt"
        lst_s.write_text("".join(f"file '{st}'\nduration {d:.3f}\n" for st, d in zip(states, parts))
                         + f"file '{states[-1]}'\n")
        dur = sum(parts)
        seg = tmp / f"s{i}.mp4"
        vf = f"fps={fps},scale=1080:1920,format=yuv420p"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst_s)]
        if aud:
            cmd += ["-i", str(aud), "-filter_complex", f"[0:v]{vf}[v];[1:a]apad[a]",
                    "-map", "[v]", "-map", "[a]"]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a"]
        cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-r", str(fps), str(seg)]
        subprocess.run(cmd, check=True)
        segs.append(seg)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in segs))
    joined = tmp / "joined.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(joined)], check=True)
    total = duration(joined)
    # progress bar on top edge keeps people watching to the end
    acc = CONFIG["design"]["accent"].lstrip("#")
    out = outdir / "reel.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
                    "-f", "lavfi", "-i", f"color=c=0x{acc}:s=1080x14:r={fps}",
                    "-filter_complex", f"[0:v][1:v]overlay=x='-w+w*t/{total:.3f}':y=0:shortest=1[v]",
                    "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-c:a", "copy", "-movflags", "+faststart", str(out)], check=True)
    shutil.copy(frames[0][-1], outdir / "cover.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(outdir / "cover.png"),
                    "-q:v", "3", str(outdir / "cover.jpg")], check=True)
    shutil.rmtree(tmp)
    return out, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--no-reel", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    a = ap.parse_args()
    spec_path = Path(a.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out = spec_path.parent / "out"
    pngs = render_pngs(spec, out / "carousel", 1080, 1350, reel=False)
    print(f"carousel: {len(pngs)} slides -> {out/'carousel'}")
    if not a.no_reel:
        mp4, total = render_reel(spec, out / "reel", voice=not a.no_voice)
        print(f"reel: {mp4} ({total:.1f}s)")


if __name__ == "__main__":
    main()
