"""Upload a video to YouTube as private with a scheduled publish time."""
import os

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(path, title, description, tags, publish_at_utc, category_id="22"):
    """publish_at_utc must be like 2026-10-07T14:00:00Z and in the future."""
    yt = _client()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:15],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_utc,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(
        str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True
    )
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  upload {int(status.progress() * 100)}%")
    return response["id"]
