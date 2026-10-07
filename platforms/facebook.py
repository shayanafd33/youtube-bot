"""Facebook Reels on a Page.

mode 'direct': Meta Graph API Reels Publishing API (needs a Page access token with pages_manage_posts).
mode 'buffer': Buffer's official API.
Reels must be 9:16, 3-90 s.
"""
import time
import requests
from .common import env, next_slot, slot_on, buffer_ready, buffer_create_post, log

NAME = "facebook"
HAS_SLOT = True


def _direct_ready():
    return all(env(k) for k in ("FB_PAGE_ID", "FB_PAGE_TOKEN"))


def resolve():
    m = env("FB_MODE", "auto").lower()
    buf = buffer_ready() and bool(env("FB_BUFFER_CHANNEL_ID"))
    if m == "buffer" or (m == "auto" and buf):
        return "buffer" if buf else "package"
    if m == "direct" or (m == "auto" and _direct_ready()):
        return "direct" if _direct_ready() else "package"
    return "package"


def slot(day=None):
    t = env("FB_TIME_UK", "21:00")
    return slot_on(day, t) if day else next_slot(t)


def _publish_buffer(ctx):
    return buffer_create_post(env("FB_BUFFER_CHANNEL_ID"), ctx["copy"]["text"], ctx["url"], ctx["slot"],
                              "facebook: { type: reel }")["id"]


def _check(r, what):
    try:
        j = r.json()
    except Exception:
        j = {}
    if r.status_code >= 400 or "error" in j:
        raise RuntimeError(f"Facebook {what} failed: {r.status_code} {r.text[:400]}")
    return j


def _publish_direct(ctx):
    page, tok = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    V = env("META_GRAPH_VERSION", "v25.0")
    data = ctx["video"].read_bytes()
    base = f"https://graph.facebook.com/{V}"
    j = _check(requests.post(f"{base}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60), "start")
    vid, upload_url = j["video_id"], j["upload_url"]
    _check(requests.post(upload_url, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))},
                         data=data, timeout=1200), "upload")
    for _ in range(12):  # wait until Facebook has received the file
        st = requests.get(f"{base}/{vid}", params={"fields": "status", "access_token": tok}, timeout=60).json()
        s = st.get("status", {})
        if s.get("uploading_phase", {}).get("status") == "complete" or s.get("video_status") in ("upload_complete", "ready"):
            break
        time.sleep(5)
    c = ctx["copy"]
    _check(requests.post(f"{base}/{page}/video_reels", data={
        "upload_phase": "finish", "video_id": vid, "access_token": tok,
        "video_state": "SCHEDULED", "scheduled_publish_time": int(ctx["slot"].timestamp()),
        "description": c["text"], "title": c.get("title", "")[:100]}, timeout=120), "publish")
    log("facebook reel scheduled")
    return vid


def publish(ctx):
    return _publish_buffer(ctx) if ctx["mode"] == "buffer" else _publish_direct(ctx)
