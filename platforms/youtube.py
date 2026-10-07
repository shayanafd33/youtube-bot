"""YouTube Shorts.

mode 'buffer': Buffer's official API (Buffer's YouTube integration is audited, so videos can go public).
mode 'direct': YouTube Data API v3 videos.insert. NOTE: Google locks uploads from *unaudited* API projects to
               private. Direct mode works fully only after your Google Cloud project passes YouTube's API audit.
"""
import os, json
import requests
from .common import env, next_slot, slot_on, buffer_ready, buffer_create_post, gql_str, utc_iso, log

NAME = "youtube"
HAS_SLOT = True


def _direct_ready():
    return all(env(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def resolve():
    m = env("YT_MODE", "auto").lower()
    buf = buffer_ready() and bool(env("YT_BUFFER_CHANNEL_ID"))
    if m == "buffer" or (m == "auto" and buf):
        return "buffer" if buf else "package"
    if m == "direct" or (m == "auto" and _direct_ready()):
        return "direct" if _direct_ready() else "package"
    return "package"


def slot(day=None):
    t = env("YT_TIME_UK", "18:00")
    return slot_on(day, t) if day else next_slot(t)


def _publish_buffer(ctx):
    c = ctx["copy"]
    meta = (f'youtube: {{ title: {gql_str(c["title"])}, categoryId: "28", madeForKids: false, '
            f'notifySubscribers: true, isAiGenerated: true }}')
    return buffer_create_post(env("YT_BUFFER_CHANNEL_ID"), c["description"], ctx["url"], ctx["slot"], meta)["id"]


def _access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=60)
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"YouTube token refresh failed: {j} (if 'invalid_grant': your OAuth app is probably still in "
                           f"'Testing' mode - refresh tokens expire after 7 days there; publish the app and re-authorise)")
    return j["access_token"]


def _publish_direct(ctx):
    c = ctx["copy"]; path = ctx["video"]; data = path.read_bytes()
    tok = _access_token()
    meta = {
        "snippet": {"title": c["title"][:100], "description": c["description"][:4900], "tags": c.get("tags", []),
                    "categoryId": "28", "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "private", "publishAt": utc_iso(ctx["slot"]),
                   "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True, "embeddable": True},
    }
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(len(data)), "X-Upload-Content-Type": "video/mp4"},
        data=json.dumps(meta), timeout=120)
    if init.status_code != 200 or "Location" not in init.headers:
        raise RuntimeError(f"YouTube upload init failed: {init.status_code} {init.text[:400]}")
    up = requests.put(init.headers["Location"], headers={"Content-Type": "video/mp4"}, data=data, timeout=1200)
    if up.status_code not in (200, 201):
        raise RuntimeError(f"YouTube upload failed: {up.status_code} {up.text[:400]}")
    vid = up.json()["id"]
    log("youtube uploaded (scheduled, private until publishAt). If your API project is unaudited it stays private - see README.")
    return vid


def publish(ctx):
    return _publish_buffer(ctx) if ctx["mode"] == "buffer" else _publish_direct(ctx)
