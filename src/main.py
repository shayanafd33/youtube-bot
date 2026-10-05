"""Make one short film and schedule it on YouTube Shorts, TikTok and Facebook Reels via Buffer.

Env flags:  DRY_RUN=1   build the video only (no GitHub release, no Buffer)
            TTS_FAKE=1  silent voice (testing only)
"""
import os
import shutil
import sys
from datetime import datetime, timezone

import images
import llm
import publish
import topics
import video
import voice
from util import WORK, load_config, load_state, probe_duration, save_state


def build_caption(service, film, version, zh, credit):
    tags = " ".join("#" + t.strip("# ") for t in film.get("hashtags", [])[:7])
    if version == "zh" and zh:
        title, desc = zh["title"], zh["description"]
    else:
        title, desc = film["title"], film["description"]
    if service == "youtube":
        return f"{desc}\n\n{tags} #Shorts\n\nMade with AI. {credit}".strip()
    if service == "tiktok":
        return f"{title}\n{tags}"[:2000]
    return f"{title}\n\n{desc}\n\n{tags}\n\n{credit}".strip()[:2000]


def main():
    cfg = load_config()
    state = load_state()
    dry = bool(os.getenv("DRY_RUN"))

    print("1/7 Finding trending topics...")
    candidates = topics.fetch_candidates()

    print("2/7 Writing the script (Gemini)...")
    film = llm.write_film(cfg, candidates, state["used_topics"])
    print("   draft title:", film["title"])

    print("3/7 Fact-checking (Gemini)...")
    try:
        checked = llm.fact_check(cfg, film, candidates)
        if len(checked.get("scenes", [])) == len(film["scenes"]):
            print("   corrections:", checked.pop("changes", []))
            film = checked
        else:
            print("   fact-check changed the scene count; keeping the original draft")
    except Exception as e:
        print(f"   fact-check skipped ({e})")
    print("   final title:", film["title"])

    versions = set(cfg["channels"].values())
    zh = None
    if "zh" in versions:
        print("   translating to Chinese...")
        zh = llm.translate_zh(cfg, film)
        if len(zh["lines"]) != len(film["scenes"]):
            raise RuntimeError("Chinese translation has the wrong number of lines")

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    scenes = film["scenes"]

    print("4/7 Recording the narration (Kokoro)...")
    voice_wav = WORK / "voice.wav"
    timings = voice.synthesize_scenes(scenes, cfg["voice"], cfg["speech_speed"], voice_wav)
    speech = [t[0] for t in timings]
    scene_secs = [t[1] for t in timings]
    duration = sum(scene_secs)
    print(f"   total length {duration:.0f}s")

    print("5/7 Making images (Pollinations Flux)...")
    img_paths = images.fetch_images(scenes, cfg["image_model"], WORK)

    print("6/7 Assembling the film (FFmpeg)...")
    base = video.render_scene_clips(img_paths, scene_secs, WORK)
    music, credit = video.pick_music(WORK) if cfg.get("music", True) else (None, "")
    outputs = {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    for version in sorted(versions):
        lines = [s["narration"] for s in scenes] if version == "en" else zh["lines"]
        subs = WORK / f"subs_{version}.ass"
        video.build_ass(lines, speech, scene_secs, version, subs)
        out = WORK / f"film-{stamp}-{version}.mp4"
        video.mix_and_burn(base, voice_wav, music, subs, duration, out, WORK)
        outputs[version] = out
        print(f"   built {out.name} ({out.stat().st_size / 1e6:.1f} MB)")

    if dry:
        print("DRY_RUN: stopping before publishing. Videos are in", WORK)
        return

    print("7/7 Publishing (GitHub Releases + Buffer)...")
    tag = f"film-{stamp}"
    urls = publish.upload_release(
        tag, list(outputs.values()), film["title"],
        f"{film['description']}\n\nAI-generated short film.")
    channels = publish.get_channels()
    due = publish.next_due_time(cfg["post_time_utc"], state.get("last_due", ""))

    ok_count = 0
    for service, version in cfg["channels"].items():
        channel = channels.get(service)
        if not channel:
            print(f"   {service}: no such channel connected in Buffer, skipped")
            continue
        caption = build_caption(service, film, version, zh, credit)
        title = zh["title"] if (version == "zh" and zh) else film["title"]
        url = urls[outputs[version].name]
        try:
            ok, msg = publish.schedule_post(channel, service, url, caption, title, due)
        except Exception as e:
            ok, msg = False, str(e)
        print(f"   {service}: {'OK' if ok else 'FAILED'} - {msg}")
        ok_count += ok

    if ok_count:
        state["used_topics"].append(film.get("topic") or film["title"])
        state["last_due"] = due.isoformat()
        save_state(state)
        publish.cleanup_old_releases()
    else:
        print("Nothing was scheduled; check the messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
