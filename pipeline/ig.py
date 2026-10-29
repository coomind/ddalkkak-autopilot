#!/usr/bin/env python3
"""
Instagram API (Instagram Login) client for @ai.ddalkkak.

Token is kept encrypted in secrets/ig_token.enc (AES-256, passphrase in env IG_PASSPHRASE).
  python3 pipeline/ig.py me                       # sanity check
  python3 pipeline/ig.py refresh                  # refresh long-lived token (do weekly)
  python3 pipeline/ig.py publish <post_dir> carousel|reel|trial_reel [--dry]
  python3 pipeline/ig.py insights <media_id>
  python3 pipeline/ig.py recent [n]               # recent media + core metrics
  python3 pipeline/ig.py comments <media_id>
  python3 pipeline/ig.py reply_private <comment_id> <message>
Media URLs: files must be pushed to the public repo first; base = config.media_base with {sha}.
"""
import json, os, sys, time, subprocess, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
API = "https://graph.instagram.com/" + CONFIG.get("ig_api_version", "v23.0")
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
    return json.loads(_openssl(["-d", "-a", "-A"], ENC.read_bytes()).decode())


def save_secret(d: dict):
    ENC.parent.mkdir(exist_ok=True)
    ENC.write_bytes(_openssl(["-a", "-A"], json.dumps(d).encode()))


def req(method, path, params=None, data=None, headers=None, url=None):
    params = dict(params or {})
    sec = load_secret()
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


def uid():
    return load_secret()["user_id"]


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


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "me":
        print(json.dumps(req("GET", "me", {"fields": "user_id,username,account_type,followers_count,media_count"}),
                         ensure_ascii=False, indent=1))
    elif cmd == "refresh":
        sec = load_secret()
        r = req("GET", "", {"grant_type": "ig_refresh_token", "access_token": sec["token"]},
                url="https://graph.instagram.com/refresh_access_token")
        sec["token"] = r["access_token"]
        sec["expires_at"] = int(time.time()) + int(r.get("expires_in", 5184000))
        save_secret(sec)
        print("refreshed; expires in days:", round(int(r.get("expires_in", 0)) / 86400))
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
        print(req("POST", f"{uid()}/messages", data=json.dumps({"recipient": {"comment_id": a[1]},
                                                                "message": {"text": a[2]}}).encode(),
                  headers={"Content-Type": "application/json"}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
