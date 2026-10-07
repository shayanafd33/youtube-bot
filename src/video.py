"""FFmpeg: Ken Burns zoom on each image, subtitles (English / Chinese), music mixing."""
import json
import random
import re
import requests

from util import ROOT, run

W, H, FPS = 1080, 1920, 30

FONTS = {"en": "Liberation Sans", "zh": "Noto Sans CJK SC"}


# ---------- scene clips with zoom motion ----------
def _zoom_filter(variant, frames):
    base = f"scale=1620:2880,setsar=1,"
    common = f":d={frames}:s={W}x{H}:fps={FPS}"
    if variant == 0:  # slow zoom in
        z = f"zoompan=z='min(1+0.25*on/{frames},1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif variant == 1:  # slow zoom out
        z = f"zoompan=z='max(1.25-0.25*on/{frames},1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    elif variant == 2:  # pan left to right
        z = f"zoompan=z=1.2:x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'"
    else:  # pan right to left
        z = f"zoompan=z=1.2:x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'"
    return base + z + common + ",format=yuv420p"


def render_scene_clips(image_paths, scene_seconds, workdir):
    clips = []
    for i, (img, secs) in enumerate(zip(image_paths, scene_seconds)):
        frames = max(int(round(secs * FPS)), FPS)
        out = workdir / f"clip{i}.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", img,
             "-vf", _zoom_filter(i % 4, frames), "-frames:v", frames,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", out])
        clips.append(out)
    listing = workdir / "clips.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    base = workdir / "base.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", listing, "-c", "copy", base])
    return base


# ---------- subtitles ----------
def _ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _chunks(text, lang):
    if lang == "zh":
        parts = [p for p in re.split(r"(?<=[，。！？、；,.!?])", text) if p.strip()]
        out, cur = [], ""
        for p in parts:
            if cur and len(cur) + len(p) > 14:
                out.append(cur)
                cur = p
            else:
                cur += p
        if cur:
            out.append(cur)
        return [c.strip("，。！？、；,.!? ") or c for c in out]
    words = text.split()
    return [" ".join(words[i:i + 3]) for i in range(0, len(words), 3)]


def _ass_header(lang):
    font = FONTS[lang]
    size = 74 if lang == "en" else 70
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,6,2,2,90,90,430,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )


def build_ass_events(events, lang, path):
    """events: [(start_seconds, duration_seconds, text)] -> ASS subtitle file."""
    out = []
    for start, dur, text in events:
        chunks = _chunks(text, lang) or [text]
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = dur * len(c) / total
            shown = c.upper() if lang == "en" else c
            out.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + d)},Default,,0,0,0,,{shown}")
            t += d
    path.write_text(_ass_header(lang) + "\n".join(out) + "\n", encoding="utf-8")


def build_ass(lines, speech_seconds, scene_seconds, lang, path):
    events, cursor = [], 0.0
    for text, speech, scene in zip(lines, speech_seconds, scene_seconds):
        events.append((cursor, speech, text))
        cursor += scene
    build_ass_events(events, lang, path)


# ---------- music ----------
def pick_music(workdir, key="tracks"):
    """Download one Kevin MacLeod track (tries several). Returns (path, credit) or (None, '')."""
    try:
        cfg = json.loads((ROOT / "music.json").read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  no music this time ({e})")
        return None, ""
    local = sorted((ROOT / "music").glob("*.mp3")) if (ROOT / "music").exists() else []
    if local:  # your own tracks in the music/ folder take priority (add credit yourself if needed)
        return local[random.randrange(len(local))], ""
    tracks = list(cfg.get(key) or cfg["tracks"])
    random.shuffle(tracks)
    for track in tracks:
        try:
            r = requests.get(track["url"], timeout=120)
            r.raise_for_status()
            if len(r.content) < 50000:
                raise ValueError("file too small")
            dest = workdir / "music.mp3"
            dest.write_bytes(r.content)
            return dest, cfg["credit_template"].format(title=track["title"])
        except Exception as e:
            print(f"  music '{track['title']}' failed ({e}), trying another")
    print("  no music this time")
    return None, ""


# ---------- final mix ----------
def mix_and_burn(base, voice_wav, music, subs_path, duration, out_path, workdir):
    """Burn subtitles, mix voice + (ducked) music, write the final MP4. Run with cwd=workdir."""
    sub_name = subs_path.name
    fade_start = max(duration - 2.0, 0)
    inputs = ["-i", base.name, "-i", voice_wav.name]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        audio = (
            "[1:a]asplit=2[vo][sc];"
            f"[2:a]volume=0.22,atrim=0:{duration:.2f},afade=t=out:st={fade_start:.2f}:d=2[bg];"
            "[bg][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
            "[vo][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio = "[1:a]anull[a]"
    graph = f"[0:v]ass={sub_name}[v];{audio}"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         "-t", f"{duration:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         out_path.name], cwd=workdir)
    return out_path
