#!/usr/bin/env python3
"""
Instagram Graph API (Facebook Login, page token) client for @ai.ddalkkak.

Token: set IG_SECRET_FILE=/home/claude/ddalkkak-secrets/ig_token.json (private repo).
Fallback: secrets/ig_token.enc decrypted with env IG_PASSPHRASE.
  python3 pipeline/ig.py me                       # sanity check
  python3 pipeline/ig.py refresh                  # refresh long-lived token (do weekly)
  python3 pipeline/ig.py publish <post_dir> carousel|reel|trial_reel [--dry]
  python3 pipeline/ig.py insights <media_id>
  python3 pipeline/ig.py recent [n]               # recent media + core metrics
  python3 pipeline/ig.py comments <media_id>
  python3 pipeline/ig.py reply_private <comment_id> <message>
  python3 pipeline/ig.py autodm [--dry]              # 댓글 키워드 → 자료 링크 DM (최근 7일 게시물)
Media URLs: files must be pushed to the public repo first; base = config.media_base with {sha}.
"""
import json, os, sys, time, subprocess, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
API = CONFIG.get("ig_api_host", "https://graph.facebook.com") + "/" + CONFIG.get("ig_api_version", "v23.0")
ENC = ROOT / "secrets" / "ig_token.enc"


def _openssl(args, data: bytes) -> bytes:
    pw = os.environ.get("IG_PASSPHRASE")
    if not pw:
        sys.exit("IG_PASSPHRASE env var missing")
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt",
                        "-pass", "env:IG_PASSPHRASE"] + args, input=data, capture_output=True)
    if r.returncode:
        sys.exit("openssl failed: " + r.stderr.decode())
    return r.stdout


def load_secret() -> dict:
    # Preferred: plaintext JSON kept in the PRIVATE repo coomind/ddalkkak-secrets (path in IG_SECRET_FILE).
    f = os.environ.get("IG_SECRET_FILE")
    if f and Path(f).exists():
        d = json.loads(Path(f).read_text())
        d.setdefault("user_id", CONFIG["ig_user_id"])
        d.setdefault("page_id", CONFIG["fb_page_id"])
        if "token" not in d and "user_token" in d:
            # derive the page token from the user's long-lived token at runtime (never written anywhere)
            u = f"{API}/{d['page_id']}?" + urllib.parse.urlencode({"fields": "access_token", "access_token": d["user_token"]})
            with urllib.request.urlopen(u, timeout=30) as r:
                d["token"] = json.loads(r.read().decode())["access_token"]
        return d
    return json.loads(_openssl(["-d", "-a", "-A"], ENC.read_bytes()).decode())


def save_secret(d: dict):
    ENC.parent.mkdir(exist_ok=True)
    ENC.write_bytes(_openssl(["-a", "-A"], json.dumps(d).encode()))


def req(method, path, params=None, data=None, headers=None, url=None):
    params = dict(params or {})
    global _SEC
    sec = _SEC = _SEC or load_secret()
    params.setdefault("access_token", sec["token"])
    u = url or f"{API}/{path.lstrip('/')}"
    if method == "GET":
        u += "?" + urllib.parse.urlencode(params)
        body = None
    else:
        body = data if data is not None else urllib.parse.urlencode(params).encode()
        if data is not None:
            u += "?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(u, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"API error {e.code} on {path}: {e.read().decode()[:800]}")


_SEC = None


def uid():
    return CONFIG["ig_user_id"]


def wait_ready(container_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = req("GET", container_id, {"fields": "status_code,status"})
        code = s.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise SystemExit(f"container {container_id} failed: {s}")
        time.sleep(6)
    raise SystemExit(f"container {container_id} timeout")


def publish_container(cid):
    wait_ready(cid)
    for attempt in range(5):
        try:
            return req("POST", f"{uid()}/media_publish", {"creation_id": cid})["id"]
        except SystemExit as e:
            if attempt == 4:
                raise
            time.sleep(10)


def caption_of(spec):
    tags = " ".join(spec.get("hashtags", [])[:5])  # Instagram caps hashtags at 5
    return (spec["caption"].rstrip() + ("\n\n" + tags if tags else "")).strip()


def publish(post_dir: Path, kind: str, base_url: str, dry=False):
    spec = json.loads((post_dir / "spec.json").read_text(encoding="utf-8"))
    cap = caption_of(spec)
    rel = post_dir.relative_to(ROOT).as_posix()
    if kind == "carousel":
        imgs = sorted((post_dir / "out" / "carousel").glob("*.png"))
        urls = [f"{base_url}{rel}/out/carousel/{p.name}" for p in imgs]
        if dry:
            return {"dry": urls, "caption": cap}
        kids = [req("POST", f"{uid()}/media", {"image_url": u, "is_carousel_item": "true"})["id"] for u in urls]
        for k in kids:
            wait_ready(k)
        cid = req("POST", f"{uid()}/media", {"media_type": "CAROUSEL", "children": ",".join(kids),
                                            "caption": cap})["id"]
    elif kind in ("reel", "trial_reel"):
        video = f"{base_url}{rel}/out/reel/reel.mp4"
        cover = f"{base_url}{rel}/out/reel/cover.jpg"
        p = {"media_type": "REELS", "video_url": video, "cover_url": cover, "caption": cap,
             "share_to_feed": "true"}
        if kind == "trial_reel":
            p["trial_params"] = json.dumps({"graduation_strategy": "SS_PERFORMANCE"})
            p.pop("share_to_feed")
        if dry:
            return {"dry": p}
        cid = req("POST", f"{uid()}/media", p)["id"]
    else:
        raise SystemExit("kind must be carousel|reel|trial_reel")
    media_id = publish_container(cid)
    fc = spec.get("first_comment")
    if fc:
        req("POST", f"{media_id}/comments", {"message": fc})
    info = req("GET", media_id, {"fields": "permalink,timestamp,media_type"})
    return {"media_id": media_id, **info}


def insights(media_id, media_type="CAROUSEL_ALBUM"):
    metrics = ["reach", "likes", "comments", "shares", "saved", "views", "total_interactions"]
    if media_type in ("REELS", "VIDEO"):
        metrics += ["ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
    out = {}
    for m in metrics:  # one by one so an unsupported metric doesn't kill the rest
        try:
            r = req("GET", f"{media_id}/insights", {"metric": m})
            out[m] = r["data"][0]["values"][0]["value"]
        except SystemExit:
            pass
    if out.get("reach"):
        out["sends_per_reach"] = round(out.get("shares", 0) / out["reach"], 4)
        out["saves_per_reach"] = round(out.get("saved", 0) / out["reach"], 4)
        out["likes_per_reach"] = round(out.get("likes", 0) / out["reach"], 4)
    return out


def _norm(t):
    return "".join((t or "").split()).lower().strip("'\"“”‘’!.~")


def autodm(dry=False, max_send=200):
    """Comment-keyword giveaway: anyone who comments the post's keyword gets the resource link by DM
    (Instagram private reply, allowed once per comment within 7 days). Needs instagram_manage_messages
    + instagram_manage_comments on the token. Falls back to a public reply pointing at the bio link."""
    import datetime as dt
    done_f = ROOT / "state" / "dm_done.json"
    done = set(json.loads(done_f.read_text())) if done_f.exists() else set()
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    base = CONFIG["media_base"].format(sha=sha)
    now = dt.datetime.now(dt.timezone.utc)
    sent = fallback = 0
    report = []
    for line in (ROOT / "state" / "log.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("status") != "published" or not e.get("media_id"):
            continue
        spec_f = ROOT / "posts" / e["id"] / "spec.json"
        if not spec_f.exists():
            continue
        spec = json.loads(spec_f.read_text(encoding="utf-8"))
        kw = (spec.get("payoff") or {}).get("keyword") or spec.get("keyword")
        gift = ROOT / "posts" / e["id"] / "out" / "giveaway.pdf"
        if not kw or not gift.exists():
            continue
        link = f"{base}posts/{e['id']}/out/giveaway.pdf"
        after = None
        while True:
            params = {"fields": "id,text,username,timestamp", "limit": 50}
            if after:
                params["after"] = after
            r = req("GET", f"{e['media_id']}/comments", params)
            for c in r.get("data", []):
                if c["id"] in done or c.get("username") == CONFIG["handle"].lstrip("@") or _norm(kw) not in _norm(c.get("text")):
                    continue
                ts = dt.datetime.strptime(c["timestamp"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
                if (now - ts).days >= 7:
                    done.add(c["id"]); continue
                msg = (spec.get("dm_text") or "댓글 남겨주셔서 감사해요! 약속한 자료예요 👇\n{link}\n\n도움 됐으면 팔로우하고 다음 꿀팁도 받아가세요 🙌").format(link=link)
                if dry:
                    report.append(f"[dry] @{c.get('username')} <- {link}")
                    continue
                try:
                    req("POST", f"{load_secret()['page_id']}/messages",
                        data=json.dumps({"recipient": {"comment_id": c["id"]}, "message": {"text": msg}}).encode(),
                        headers={"Content-Type": "application/json"})
                    req("POST", f"{c['id']}/replies", {"message": "DM 보내드렸어요! 📩 메시지함(요청함) 확인해주세요"})
                    sent += 1
                except SystemExit as err:
                    try:
                        req("POST", f"{c['id']}/replies", {"message": "프로필 링크 자료실에 올려뒀어요! 📎"})
                    except SystemExit:
                        pass
                    fallback += 1
                    report.append(f"DM 실패 → 공개 답글: {str(err)[:120]}")
                done.add(c["id"])
                time.sleep(1.2)
                if sent + fallback >= max_send:
                    break
            after = (r.get("paging") or {}).get("cursors", {}).get("after") if (r.get("paging") or {}).get("next") else None
            if not after or sent + fallback >= max_send:
                break
    if not dry:
        done_f.write_text(json.dumps(sorted(done)))
    return {"sent": sent, "fallback_public_reply": fallback, "notes": report[:20]}


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "me":
        print(json.dumps(req("GET", uid(), {"fields": "id,username,followers_count,media_count"}),
                         ensure_ascii=False, indent=1))
    elif cmd == "refresh":
        # Page token derived from a long-lived user token does not expire; just verify it still works.
        sec = load_secret()
        r = req("GET", "debug_token", {"input_token": sec["token"]})
        d = r.get("data", {})
        print("valid:", d.get("is_valid"), "expires_at:", d.get("expires_at"), "scopes:", len(d.get("scopes", [])))
    elif cmd == "publish":
        post_dir = (ROOT / a[1]).resolve() if not Path(a[1]).is_absolute() else Path(a[1])
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
        base = CONFIG["media_base"].format(sha=sha)
        print(json.dumps(publish(post_dir, a[2], base, dry="--dry" in a), ensure_ascii=False, indent=1))
    elif cmd == "insights":
        print(json.dumps(insights(a[1], a[2] if len(a) > 2 else "CAROUSEL_ALBUM"), indent=1))
    elif cmd == "recent":
        n = int(a[1]) if len(a) > 1 else 10
        r = req("GET", f"{uid()}/media", {"fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                                         "limit": n})
        for m in r.get("data", []):
            m["insights"] = insights(m["id"], m["media_type"])
            m["caption"] = (m.get("caption") or "")[:60]
        print(json.dumps(r.get("data", []), ensure_ascii=False, indent=1))
    elif cmd == "comments":
        print(json.dumps(req("GET", f"{a[1]}/comments", {"fields": "id,text,username,timestamp"}),
                         ensure_ascii=False, indent=1))
    elif cmd == "reply_private":
        print(req("POST", f"{load_secret()['page_id']}/messages", data=json.dumps({"recipient": {"comment_id": a[1]},
                                                                "message": {"text": a[2]}}).encode(),
                  headers={"Content-Type": "application/json"}))
    elif cmd == "autodm":
        print(json.dumps(autodm(dry="--dry" in a), ensure_ascii=False, indent=1))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
