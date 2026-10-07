"""TikTok via Buffer's official API (Buffer is an approved TikTok publisher; free plan)."""
from .common import env, next_slot, slot_on, buffer_ready, buffer_create_post, gql_str

NAME = "tiktok"
HAS_SLOT = True


def resolve():
    return "buffer" if buffer_ready() and env("BUFFER_CHANNEL_ID") else "package"


def slot(day=None):
    t = env("POST_TIME_UK", "19:30")
    return slot_on(day, t) if day else next_slot(t)


def publish(ctx):
    c = ctx["copy"]
    meta = f"tiktok: {{ isAiGenerated: true, title: {gql_str(c['title'])} }}"
    post = buffer_create_post(env("BUFFER_CHANNEL_ID"), c["text"], ctx["url"], ctx["slot"], meta)
    return post["id"]
