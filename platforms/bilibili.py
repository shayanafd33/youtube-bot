"""Bilibili.

Default ('package'): builds a ready-to-upload folder (1920x1080 video, cover, Chinese title/description/tags,
upload instructions). You upload it in Bilibili's creator centre. This needs no approval.

'direct' (opt-in, EXPERIMENTAL): Bilibili Open Platform (open.bilibili.com) official API. It needs a developer
application approved by Bilibili plus an OAuth access token. Written from Bilibili's public API docs and NOT yet
tested against a live account. Turn it on with BILI_PUBLISH=1 once you have: BILI_CLIENT_ID, BILI_APP_SECRET,
BILI_ACCESS_TOKEN, BILI_MID. The open API has no scheduling field: the video is submitted for review immediately.
No unofficial cookie/login tools are used anywhere.
"""
import json, time, uuid, hmac, hashlib, shutil, pathlib
import requests
from .common import env, log

NAME = "bilibili"
HAS_SLOT = False
BASE = "https://member.bilibili.com"
PART = 10 * 1024 * 1024


def _direct_ready():
    return env("BILI_PUBLISH") == "1" and all(env(k) for k in ("BILI_CLIENT_ID", "BILI_APP_SECRET", "BILI_ACCESS_TOKEN", "BILI_MID"))


def resolve():
    return "direct" if _direct_ready() else "package"


def slot(day=None):
    return None


# ---------- request signing (HMAC-SHA256, signature version 2.0, per Bilibili's documented scheme) ----------
def sign_headers(body: bytes, access_key, secret, access_token, nonce=None, ts=None):
    h = {
        "x-bili-accesskeyid": access_key,
        "x-bili-content-md5": hashlib.md5(body).hexdigest(),
        "x-bili-signature-method": "HMAC-SHA256",
        "x-bili-signature-nonce": nonce or uuid.uuid4().hex,
        "x-bili-signature-version": "2.0",
        "x-bili-timestamp": str(ts or int(time.time())),
    }
    to_sign = "\n".join(f"{k}:{h[k]}" for k in sorted(h))
    h["Authorization"] = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    h["Access-Token"] = access_token
    h["Accept"] = "application/json"
    return h


def _call(path, *, params=None, json_body=None, raw=None, files=None):
    ak, sk, tok = env("BILI_CLIENT_ID"), env("BILI_APP_SECRET"), env("BILI_ACCESS_TOKEN")
    body = b""
    headers = {}
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        headers["Content-Type"] = "application/octet-stream"   # file content is excluded from the md5 per the docs
    headers.update(sign_headers(body, ak, sk, tok))
    r = requests.post(BASE + path, params=params, headers=headers,
                      data=body if json_body is not None else raw, files=files, timeout=600)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"Bilibili {path}: HTTP {r.status_code} {r.text[:300]}")
    if j.get("code") != 0:
        raise RuntimeError(f"Bilibili {path}: {json.dumps(j, ensure_ascii=False)[:400]}")
    return j.get("data") or {}


def _publish_direct(ctx):
    c, path = ctx["copy"], ctx["video"]
    data = path.read_bytes()
    log("bilibili: starting upload (experimental)")
    token = _call("/arcopen/fn/archive/video/init", json_body={"name": path.name, "utype": 1})["upload_token"]
    for i in range(0, len(data), PART):
        _call("/arcopen/fn/archive/video/part/upload",
              params={"upload_token": token, "part_number": i // PART + 1}, raw=data[i:i + PART])
    _call("/arcopen/fn/archive/video/complete", params={"upload_token": token}, json_body={})
    cover_url = None
    if ctx.get("cover") and pathlib.Path(ctx["cover"]).exists():
        with open(ctx["cover"], "rb") as f:
            cover_url = _call("/arcopen/fn/archive/cover/upload", files={"file": ("cover.jpg", f, "image/jpeg")}).get("url")
    body = {"mid": int(env("BILI_MID")), "title": c["title"][:79], "tid": int(env("BILI_TID", "201")),
            "tag": c["tags"][:199], "desc": c["desc"][:249], "copyright": 1, "no_reprint": 0}
    if cover_url:
        body["cover"] = cover_url
    return _call("/arcopen/fn/archive/add-by-utoken", params={"upload_token": token}, json_body=body)["resource_id"]


def package(ctx):
    """Manual-upload folder: video, cover, metadata and instructions."""
    c = ctx["copy"]
    d = pathlib.Path(ctx["out"]) / f"bilibili-{ctx['key']}"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(ctx["video"], d / "video.mp4")
    if ctx.get("cover") and pathlib.Path(ctx["cover"]).exists():
        shutil.copy(ctx["cover"], d / "cover.jpg")
    (d / "metadata.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
    (d / "UPLOAD_INSTRUCTIONS.txt").write_text(
        "Upload at https://member.bilibili.com/platform/upload/video/frame\n"
        f"1. Choose video.mp4 and set the cover to cover.jpg\n2. Title: {c['title']}\n"
        f"3. Category: Knowledge > Science (科学科普)\n4. Type: Original (自制)\n"
        f"5. Tags: {c['tags']}\n6. Description:\n{c['desc']}\n"
        "7. Tick the 'AI-generated content' declaration (本内容为AI生成) before submitting.\n")
    return f"packaged:{d}"


def publish(ctx):
    if ctx["mode"] == "direct":
        return _publish_direct(ctx)
    return package(ctx)
