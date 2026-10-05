"""Generate one vertical Short and upload it to YouTube, scheduled for later.

Flow: pick next schedule item -> Gemini writes script -> edge-tts voice ->
Pexels stock clips -> FFmpeg assembles + burns captions -> YouTube upload.
Set DRY_RUN=1 to build the video without uploading.
"""
import asyncio
import json
import os
import random
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import edge_tts
import requests

from youtube_upload import upload_video

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "schedule.json"
WORK = ROOT / "work"
W, H, FPS = 1080, 1920, 30
VOICE = os.getenv("TTS_VOICE", "en-US-AndrewNeural")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def run(cmd, cwd=None):
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


# ---------- schedule ----------
def parse_time(s):
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def pick_next(data):
    now = datetime.now(timezone.utc)
    for item in data["items"]:
        if item.get("done"):
            continue
        if parse_time(item["publish_at"]) > now + timedelta(minutes=15):
            return item
    return None


# ---------- 1. script ----------
def write_script(style, topic, past_titles):
    topic_line = (
        f"Topic: {topic}"
        if topic
        else "Pick a fresh, specific topic yourself (not in the avoid list)."
    )
    prompt = f"""You write scripts for YouTube Shorts.
Style: {style}
{topic_line}
Avoid these already-used titles: {past_titles}

Return ONLY JSON with this shape:
{{
  "title": "catchy title under 70 characters, no hashtags",
  "description": "2 short sentences",
  "tags": ["5 to 8 tags"],
  "scenes": [
    {{"narration": "1-2 short spoken sentences", "search_query": "2-3 word concrete visual for stock footage"}}
  ]
}}
Rules: 6 to 8 scenes, 110-140 words of narration in total (about 45-55 seconds).
Scene 1 must be a strong hook. The last scene is a short closing line.
Narration is plain spoken text: no emojis, no stage directions."""
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=120,
    )
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# ---------- 2. voice ----------
async def _tts(text, path):
    await edge_tts.Communicate(text, VOICE).save(str(path))


def make_voice(text, path):
    asyncio.run(_tts(text, path))


def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]
    )
    return float(out)


# ---------- 3. visuals ----------
def fetch_clip(query, dest, used):
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": os.environ["PEXELS_API_KEY"]},
        params={"query": query, "orientation": "portrait", "per_page": 10},
        timeout=30,
    )
    r.raise_for_status()
    videos = r.json().get("videos", [])
    random.shuffle(videos)
    for v in videos:
        if v["id"] in used:
            continue
        files = [
            f for f in v["video_files"]
            if f.get("file_type") == "video/mp4" and (f.get("width") or 0) >= 720
        ]
        if not files:
            continue
        best = min(files, key=lambda f: abs(f["width"] - W))
        data = requests.get(best["link"], timeout=180)
        data.raise_for_status()
        dest.write_bytes(data.content)
        used.add(v["id"])
        return True
    return False


# ---------- 4. assemble ----------
def render_scene(clip, audio, dur, out):
    if clip:
        src = ["-stream_loop", "-1", "-i", clip]
    else:  # fallback background if no stock clip was found
        src = ["-f", "lavfi", "-i", f"color=c=0x16213e:s={W}x{H}:r={FPS}"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"setsar=1,fps={FPS},format=yuv420p")
    run(["ffmpeg", "-y", "-loglevel", "error", *src, "-i", audio,
         "-t", f"{dur:.3f}", "-vf", vf, "-af", "apad",
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "160k", out])


def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build_ass(scenes_timing, path):
    """scenes_timing: list of (start, speech_duration, narration)."""
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,DejaVu Sans,72,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,6,2,2,80,80,520,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    lines = []
    for start, dur, text in scenes_timing:
        words = text.split()
        chunks = [" ".join(words[i:i + 3]) for i in range(0, len(words), 3)]
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = dur * len(c) / total
            lines.append(
                f"Dialogue: 0,{ass_time(t)},{ass_time(t + d)},Default,,0,0,0,,{c.upper()}"
            )
            t += d
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def build_video(script):
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    used, parts, timing, cursor = set(), [], [], 0.0

    for i, sc in enumerate(script["scenes"]):
        audio = WORK / f"a{i}.mp3"
        make_voice(sc["narration"], audio)
        speech = duration(audio)
        dur = speech + 0.25

        clip_path = WORK / f"c{i}.mp4"
        try:
            ok = fetch_clip(sc["search_query"], clip_path, used)
        except requests.RequestException as e:
            print(f"  clip fetch failed ({e}); using fallback background")
            ok = False

        part = WORK / f"p{i}.mp4"
        render_scene(str(clip_path) if ok else None, str(audio), dur, str(part))
        parts.append(part)
        timing.append((cursor, speech, sc["narration"]))
        cursor += dur
        print(f"  scene {i + 1}/{len(script['scenes'])} done ({dur:.1f}s)")

    (WORK / "list.txt").write_text(
        "".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", "list.txt", "-c", "copy", "joined.mp4"], cwd=WORK)

    build_ass(timing, WORK / "subs.ass")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", "joined.mp4",
         "-vf", "ass=subs.ass", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-c:a", "copy", "final.mp4"], cwd=WORK)
    return WORK / "final.mp4", cursor


# ---------- main ----------
def main():
    data = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    item = pick_next(data)
    if not item:
        print("Nothing to do: no pending future slot in schedule.json")
        return

    past = [i["title"] for i in data["items"] if i.get("title")]
    print("Writing script...")
    script = write_script(data.get("style", "interesting facts"), item.get("topic", ""), past)
    print("Title:", script["title"])

    print("Building video...")
    video, seconds = build_video(script)
    print(f"Video ready: {seconds:.0f}s")
    if seconds > 60:
        print("Warning: longer than 60s, so YouTube may not treat it as a Short")

    if os.getenv("DRY_RUN"):
        print("DRY_RUN set: skipping upload. Video at", video)
        return

    publish_at = parse_time(item["publish_at"]).astimezone(timezone.utc)
    video_id = upload_video(
        video,
        f"{script['title']} #Shorts",
        f"{script['description']}\n\n#Shorts",
        script.get("tags", []),
        publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    item.update(done=True, title=script["title"], video_id=video_id)
    SCHEDULE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Uploaded and scheduled:", f"https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
