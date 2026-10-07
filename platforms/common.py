"""Helpers shared by the platform modules. Nothing here imports the main pipeline."""
import os, json, datetime, time
from zoneinfo import ZoneInfo
import requests

LONDON = ZoneInfo("Europe/London")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def env(name, default=""):
    """Like os.getenv but treats an empty string as 'not set' (GitHub passes empty strings for unset secrets)."""
    return os.getenv(name) or default


def next_slot(hhmm):
    """Next occurrence of hh:mm UK local time (GMT/BST handled), at least 30 min from now."""
    now = datetime.datetime.now(LONDON)
    h, m = map(int, hhmm.split(":"))
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if slot < now + datetime.timedelta(minutes=30):
        slot += datetime.timedelta(days=1)
    return slot


def slot_on(day, hhmm):
    """Slot at hh:mm UK local time on a given calendar day (datetime.date)."""
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=LONDON)


def utc_iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def gql_str(s):
    return json.dumps(s, ensure_ascii=False)


# ---------- public hosting (free): GitHub release assets in a public media repo ----------
def hosting_ready():
    return all(env(k) for k in ("MEDIA_GH_TOKEN", "MEDIA_REPO"))


def buffer_ready():
    return bool(env("BUFFER_API_KEY")) and hosting_ready()


def host_files(files, key):
    """files: {platform: Path}. One release per day, one asset per platform. Returns {platform: public_url}."""
    repo = os.environ["MEDIA_REPO"]
    H = {"Authorization": f"Bearer {os.environ['MEDIA_GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}"
    tag = f"v{key}"
    rel = requests.get(f"{api}/releases/tags/{tag}", headers=H, timeout=60)
    if rel.status_code == 404:
        rel = requests.post(f"{api}/releases", headers=H, json={"tag_name": tag, "name": key}, timeout=60)
    rel.raise_for_status()
    rel = rel.json()
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    up = rel["upload_url"].split("{")[0]
    urls = {}
    for name, path in files.items():
        asset = f"{key}-{name}.mp4"
        if asset in existing:
            requests.delete(f"{api}/releases/assets/{existing[asset]}", headers=H, timeout=60)
        a = requests.post(f"{up}?name={asset}", headers={**H, "Content-Type": "video/mp4"},
                          data=path.read_bytes(), timeout=900)
        a.raise_for_status()
        urls[name] = a.json()["browser_download_url"]
    # housekeeping: delete the hosted videos of days that are already over (tag = publish date).
    # Future days stay, because Buffer may fetch the file when the post goes out.
    try:
        today = datetime.datetime.now(LONDON).date()
        for r in requests.get(f"{api}/releases?per_page=100", headers=H, timeout=60).json():
            try:
                day = datetime.date.fromisoformat(r["tag_name"].lstrip("v"))
            except Exception:
                continue
            if (today - day).days > 3:
                requests.delete(f"{api}/releases/{r['id']}", headers=H, timeout=60)
                requests.delete(f"{api}/git/refs/tags/{r['tag_name']}", headers=H, timeout=60)
    except Exception as ex:
        log("media cleanup skipped:", ex)
    return urls


# ---------- Buffer (official GraphQL API) ----------
def buffer_create_post(channel_id, text, video_url, due, metadata_gql):
    """Schedules one video post. metadata_gql is the inside of metadata:{ ... } e.g. 'tiktok: { ... }'."""
    j = gql_str
    q = f"""mutation {{ createPost(input: {{
      text: {j(text)}, channelId: {j(channel_id)},
      schedulingType: automatic, mode: customScheduled, dueAt: "{utc_iso(due)}",
      assets: [{{ video: {{ url: {j(video_url)}, metadata: {{ thumbnailOffset: 1500 }} }} }}],
      metadata: {{ {metadata_gql} }}
    }}) {{ ... on PostActionSuccess {{ post {{ id dueAt }} }} ... on MutationError {{ message }} }} }}"""
    r = requests.post("https://api.buffer.com", json={"query": q},
                      headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}"}, timeout=120).json()
    res = (r.get("data") or {}).get("createPost") or {}
    if r.get("errors") or "post" not in res:
        raise RuntimeError(f"Buffer rejected the post: {json.dumps(r)[:600]}")
    return res["post"]
