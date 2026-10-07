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
import story
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


def clean_shots(bible, film, scene, ep):
    """Keep only valid shots: known characters, living characters, sensible lines."""
    allowed = set(scene["cast"])
    dead = {c for c, v in film["chars"].items() if str(v.get("status", "")).lower().startswith("dead")}
    shots = []
    for sh in ep.get("shots", []):
        chars = [c for c in sh.get("characters", []) if story.is_known(bible, c) and c in allowed and c not in dead]
        named = [c for c in chars if c in bible["characters"]][:2]
        infected = [c for c in chars if c in bible["infected"]][:1]
        lines = []
        for ln in sh.get("lines", [])[:2]:
            text = str(ln.get("text", "")).strip()
            if not text:
                continue
            sp = ln.get("speaker", "NARRATOR")
            if sp not in bible["characters"] or sp in dead:
                sp = "NARRATOR"
            lines.append({"speaker": sp, "text": text})
        shots.append({
            "characters": named + infected,
            "camera": str(sh.get("camera", "medium shot, 50mm lens")),
            "visual": str(sh.get("visual", scene["title"])),
            "lines": lines,
        })
    if len(shots) < 5:
        raise RuntimeError("Gemini returned too few usable shots")
    return shots[:11]


def run_film(cfg, state, dry):
    bible = story.load_bible()
    film = story.get_film_state(state, bible)
    idx = film["scene_index"]
    total = len(bible["scenes"])
    if idx >= total:
        print(f"The film is finished: all {total} episodes have been made. Nothing to do.")
        return
    scene = bible["scenes"][idx]
    nxt = bible["scenes"][idx + 1] if idx + 1 < total else None
    print(f"Episode {scene['n']}/{total}: {scene['title']}")

    print("1/6 Writing the episode (Gemini)...")
    ep = llm.write_episode(cfg, bible, film, scene, nxt)
    shots = clean_shots(bible, film, scene, ep)
    words = sum(len(l["text"].split()) for sh in shots for l in sh["lines"])
    print(f"   {len(shots)} shots, {words} spoken words: {ep.get('episode_title')}")

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()

    print("2/6 Acting the lines (Kokoro, one voice per character)...")
    speakers = [l["speaker"] for sh in shots for l in sh["lines"]]
    vmap = story.voice_map(bible, speakers)
    voice_wav = WORK / "voice.wav"
    shot_secs, events = voice.synthesize_shots(shots, vmap, voice_wav)
    duration = sum(shot_secs)
    print(f"   total length {duration:.0f}s")

    print("3/6 Shooting the scenes (Pollinations Flux, locked actors)...")
    items = [{"image_prompt": story.shot_image_prompt(bible, film, scene, sh),
              "seed": story.shot_seed(bible, sh)} for sh in shots]
    img_paths = images.fetch_images(items, cfg["image_model"], WORK, style="")

    print("4/6 Editing (FFmpeg: camera moves, subtitles, music)...")
    base = video.render_scene_clips(img_paths, shot_secs, WORK)
    music, credit = video.pick_music(WORK, "film_tracks") if cfg.get("music", True) else (None, "")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    subs = WORK / "subs_en.ass"
    video.build_ass_events(events, "en", subs)
    out = WORK / f"film-{stamp}-ep{scene['n']:02d}-en.mp4"
    video.mix_and_burn(base, voice_wav, music, subs, duration, out, WORK)
    print(f"   built {out.name} ({out.stat().st_size / 1e6:.1f} MB)")

    if dry:
        print("DRY_RUN: stopping before publishing. Video is in", WORK)
        return

    print("5/6 Publishing (GitHub Releases + Buffer)...")
    tag = f"film-{stamp}-ep{scene['n']:02d}"
    title = f"{bible['title']} | Ep {scene['n']}: {ep.get('episode_title', scene['title'])}"[:100]
    urls = publish.upload_release(tag, [out], title, ep.get("description", "") + "\n\nAI-generated film.")
    url = urls[out.name]
    tags = " ".join("#" + t for t in bible["hashtags"])
    desc = ep.get("description", "")
    channels = publish.get_channels()
    due = publish.next_due_time(cfg["post_time_utc"], state.get("last_due", ""))
    ok_count = 0
    for service in cfg["channels"]:
        channel = channels.get(service)
        if not channel:
            print(f"   {service}: no such channel connected in Buffer, skipped")
            continue
        if service == "tiktok":
            caption = f"{title}\n{tags}"[:2000]
        elif service == "youtube":
            caption = f"{desc}\n\nEpisode {scene['n']} of {total}. {tags} #Shorts\n\nAI-generated film. {credit}".strip()
        else:
            caption = f"{title}\n\n{desc}\n\n{tags}\n\nAI-generated film. {credit}".strip()[:2000]
        try:
            ok, msg = publish.schedule_post(channel, service, url, caption, title, due)
        except Exception as e:
            ok, msg = False, str(e)
        print(f"   {service}: {'OK' if ok else 'FAILED'} - {msg}")
        ok_count += ok

    if ok_count:
        print("6/6 Saving continuity...")
        story.apply_continuity(bible, film, ep.get("continuity_update"))
        film["summaries"].append(str(ep.get("summary", scene["beat"]))[:400])
        film["scene_index"] = idx + 1
        state["last_due"] = due.isoformat()
        save_state(state)
        publish.cleanup_old_releases()
    else:
        print("Nothing was scheduled; the episode will be retried next run.")
        sys.exit(1)


def main():
    cfg = load_config()
    state = load_state()
    dry = bool(os.getenv("DRY_RUN"))
    if cfg.get("mode") == "film":
        return run_film(cfg, state, dry)

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
