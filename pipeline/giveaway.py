#!/usr/bin/env python3
"""Render the comment-keyword giveaway (spec["giveaway"]) into posts/<id>/out/giveaway.pdf.

spec["giveaway"] = {"title": str, "subtitle": str,
                    "blocks": [{"h": str, "p": str (optional), "prompt": str (optional), "list": [str] (optional)}]}
Usage: python3 pipeline/giveaway.py posts/<id>/spec.json
"""
import json, sys, html, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def md(t):
    t = html.escape(t or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


def build(g):
    font = (ROOT / "fonts" / "PretendardVariable.woff2").as_uri()
    blocks = []
    for i, b in enumerate(g["blocks"], 1):
        x = f'<section><div class="n">{i:02d}</div><h2>{md(b["h"])}</h2>'
        if b.get("p"):
            x += f'<p>{md(b["p"])}</p>'
        if b.get("list"):
            x += "<ul>" + "".join(f"<li>{md(li)}</li>" for li in b["list"]) + "</ul>"
        if b.get("prompt"):
            x += f'<div class="pr"><span>복붙 프롬프트</span>{md(b["prompt"])}</div>'
        blocks.append(x + "</section>")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family:'Pretendard'; src:url('{font}') format('woff2'); font-weight:100 900; }}
@page {{ size: 148mm 210mm; margin: 0; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Pretendard',sans-serif; background:#0B0B0D; color:#ECECF1; word-break:keep-all; letter-spacing:-0.02em;
  -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
.cover {{ height:210mm; padding:22mm 14mm; display:flex; flex-direction:column; justify-content:space-between; page-break-after:always;
  background: radial-gradient(120mm 90mm at 50% 20%, rgba(70,90,255,.25), transparent 70%), #0B0B0D; }}
.cover .tag {{ display:inline-block; background:#FFD60A; color:#0B0B0D; font-weight:800; font-size:10pt; padding:2mm 4mm; border-radius:99px; }}
.cover h1 {{ font-size:30pt; line-height:1.18; font-weight:900; color:#fff; margin-top:8mm; }}
.cover h1 b {{ color:#FFD60A; }}
.cover .sub {{ font-size:12pt; line-height:1.6; color:#B9B9C4; margin-top:6mm; }}
.cover .h {{ font-size:11pt; color:#7A7A86; font-weight:700; }}
main {{ padding:14mm 12mm; }}
section {{ background:#16161B; border:1px solid #26262D; border-radius:5mm; padding:7mm 7mm 6mm; margin-bottom:6mm; page-break-inside:avoid; }}
.n {{ font-size:10pt; font-weight:900; color:#FFD60A; }}
h2 {{ font-size:15pt; line-height:1.3; font-weight:850; color:#fff; margin-top:1.5mm; }}
h2 b {{ color:#FFD60A; }}
p {{ font-size:10.5pt; line-height:1.65; color:#C9C9D3; margin-top:3mm; }}
p b, li b {{ color:#FFD60A; }}
ul {{ margin-top:3mm; padding-left:5mm; }}
li {{ font-size:10.5pt; line-height:1.6; color:#C9C9D3; margin-bottom:1.2mm; }}
.pr {{ margin-top:4mm; background:#0B0B0D; border:1px solid #33333C; border-left:3px solid #FFD60A; border-radius:3mm; padding:5mm 5mm 4mm;
  font-size:10.5pt; line-height:1.7; color:#F2F2F6; position:relative; }}
.pr span {{ display:block; font-size:8.5pt; font-weight:800; color:#FFD60A; margin-bottom:2mm; }}
.end {{ text-align:center; color:#7A7A86; font-size:10pt; padding:4mm 0 2mm; }}
.end b {{ color:#fff; }}
</style></head><body>
<div class="cover"><div><span class="tag">AI 딸깍 무료 자료</span><h1>{md(g["title"])}</h1><div class="sub">{md(g.get("subtitle",""))}</div></div>
<div class="h">{html.escape(CONFIG["handle"])}</div></div>
<main>{"".join(blocks)}<div class="end">더 많은 과제·업무 AI 꿀팁은 <b>{html.escape(CONFIG["handle"])}</b></div></main>
</body></html>"""


def main():
    spec_path = Path(sys.argv[1]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    g = spec.get("giveaway")
    if not g:
        sys.exit("spec has no giveaway")
    out = spec_path.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_giveaway.html"
    tmp.write_text(build(g), encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.as_uri())
        pg.wait_for_function("document.fonts.status === 'loaded'")
        pg.pdf(path=str(out / "giveaway.pdf"), prefer_css_page_size=True, print_background=True)
        b.close()
    tmp.unlink()
    print(out / "giveaway.pdf")


if __name__ == "__main__":
    main()
