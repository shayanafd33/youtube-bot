"""Host videos on GitHub Releases (public URL) and schedule them with the Buffer API."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import requests

BUFFER_URL = "https://api.buffer.com"
KEEP_RELEASES = 20  # Buffer fetches the file at post time, so keep recent ones


# ---------- GitHub Releases ----------
def upload_release(tag, files, title, notes):
    """Create a release with the video files; return {filename: public_url}."""
    repo = os.environ["GITHUB_REPOSITORY"]
    res = subprocess.run(
        ["gh", "release", "create", tag, *[str(f) for f in files],
         "--repo", repo, "--title", title, "--notes", notes],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"GitHub release failed: {res.stderr.strip() or res.stdout.strip()}")
    return {f.name: f"https://github.com/{repo}/releases/download/{tag}/{f.name}" for f in files}


def cleanup_old_releases():
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        out = subprocess.check_output(
            ["gh", "release", "list", "--repo", repo, "--limit", "100",
             "--json", "tagName,createdAt"], text=True)
        releases = sorted(json.loads(out), key=lambda r: r["createdAt"], reverse=True)
        for r in releases[KEEP_RELEASES:]:
            if r["tagName"].startswith("film-"):
                subprocess.run(["gh", "release", "delete", r["tagName"], "--repo", repo,
                                "--yes", "--cleanup-tag"], check=False)
    except Exception as e:
        print(f"  release cleanup skipped ({e})")


# ---------- Buffer ----------
def _clean_key(name):
    """Secrets pasted into GitHub often carry a hidden newline or space; remove them."""
    key = os.environ.get(name, "").strip().strip('"').strip("'").strip()
    if not key:
        raise RuntimeError(f"The {name} secret is empty or missing in GitHub Secrets")
    return key


def _gql(query, variables=None):
    r = requests.post(
        BUFFER_URL,
        headers={"Authorization": f"Bearer {_clean_key('BUFFER_API_KEY')}",
                 "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Buffer HTTP {r.status_code}: {r.text[:600]}")
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"Buffer API error: {data['errors']}")
    return data["data"]


def get_channels():
    """Return {service_name_lowercase: channel_id} for the first Buffer organization."""
    orgs = _gql("query { account { organizations { id name } } }")["account"]["organizations"]
    if not orgs:
        raise RuntimeError("No Buffer organization found")
    org_id = json.dumps(orgs[0]["id"])  # inlined, as in Buffer's own examples
    chans = _gql(
        f"query {{ channels(input: {{ organizationId: {org_id} }}) {{ id name service }} }}"
    )["channels"]
    found = {}
    for c in chans:
        found.setdefault(str(c["service"]).lower(), c)
    return found


_CREATE = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}
"""


def schedule_post(channel, service, video_url, caption, title, due_at_utc):
    """Create one scheduled video post. Returns (ok, message)."""
    post = {
        "text": caption,
        "channelId": channel["id"],
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "assets": [{"video": {"url": video_url}}],
    }
    if service == "youtube":
        post["metadata"] = {"youtube": {
            "title": title[:100], "categoryId": "1", "privacy": "public",
            "madeForKids": False, "notifySubscribers": True, "isAiGenerated": True}}
    elif service == "facebook":
        post["metadata"] = {"facebook": {"type": "reel"}}
    elif service == "tiktok":
        post["metadata"] = {"tiktok": {"isAiGenerated": True}}

    res = _gql(_CREATE, {"input": post})["createPost"]
    if res.get("post"):
        return True, f"scheduled for {res['post']['dueAt']}"
    return False, res.get("message", "unknown error")


# ---------- timing ----------
def next_due_time(post_time_utc, last_due_iso):
    """Next daily slot at HH:MM UTC, at least 20 minutes ahead and after the last scheduled day."""
    hh, mm = (int(x) for x in post_time_utc.split(":"))
    now = datetime.now(timezone.utc)
    due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if due < now + timedelta(minutes=20):
        due += timedelta(days=1)
    if last_due_iso:
        last = datetime.fromisoformat(last_due_iso)
        while due <= last:
            due += timedelta(days=1)
    return due
