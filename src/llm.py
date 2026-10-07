"""Google Gemini (free tier) helpers. All calls return parsed JSON."""
import json
import os
import re
import time

import requests


# Google retires Gemini models often, so we try several current ones in order.
DEFAULT_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
]
_working_model = None  # remembers the model that worked, so later calls skip failures


def _model_list(cfg_model):
    models = []
    if os.getenv("GEMINI_MODEL"):
        models.append(os.environ["GEMINI_MODEL"])
    models += DEFAULT_MODELS
    if _working_model:
        models.insert(0, _working_model)
    seen, out = set(), []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _extract_text(resp_json):
    parts = resp_json["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _call(cfg_model, prompt, retries=3):
    global _working_model
    last_error = "unknown"
    for model in _model_list(cfg_model):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(retries):
            r = requests.post(
                url,
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=180,
            )
            if r.status_code in (404, 400, 403):  # model retired / not allowed: try the next one
                last_error = f"{model}: HTTP {r.status_code} {r.text[:150]}"
                print(f"  model {model} unavailable ({r.status_code}), trying the next one")
                break
            if r.status_code in (429, 500, 503):  # rate limit or busy server
                last_error = f"{model}: HTTP {r.status_code} {r.text[:150]}"
                if attempt < retries - 1:
                    wait = 20 * (attempt + 1)
                    print(f"  {model} busy ({r.status_code}), retrying in {wait}s")
                    time.sleep(wait)
                    continue
                print(f"  {model} still busy, trying the next model")
                break
            r.raise_for_status()
            text = _extract_text(r.json())
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
            _working_model = model
            print(f"  (Gemini model used: {model})")
            return json.loads(text)
    raise RuntimeError(f"No Gemini model worked. Last problem: {last_error}")


def write_film(cfg, candidates, used_topics):
    listing = "\n".join(
        f"- [{c['source']}] {c['title']}: {c['summary']}" for c in candidates
    ) or "(no feeds available: choose a timeless, interesting topic)"
    n = cfg["scenes"]
    prompt = f"""You write short films for TikTok, YouTube Shorts and Facebook Reels, narrated in British English.
Channel niche: {cfg['niche']}

Today's trending items:
{listing}

Already used topics (do NOT repeat): {used_topics[-40:]}

Choose ONE topic from the trending items that suits a 60-80 second mini documentary: curious, positive,
explanatory or inspiring. Avoid deaths, crime, graphic events, partisan politics and anything cruel.
If nothing suits, pick a timeless fascinating topic instead.

Return ONLY JSON:
{{
  "topic": "short topic name",
  "title": "catchy title under 70 characters, no hashtags",
  "description": "2 short sentences for the video description",
  "hashtags": ["5 to 7 hashtags without the # sign"],
  "scenes": [
    {{
      "narration": "1-2 short spoken sentences",
      "image_prompt": "vivid cinematic still description for an AI image model, no text in the image"
    }}
  ]
}}

Rules:
- Exactly {n} scenes, about 150-190 words of narration in total.
- Scene 1 is a strong hook. The last scene is a memorable closing line.
- Only state facts that are supported by the trending items above or are well-established common knowledge.
- Never invent quotes, statistics or events. Never put words in a real person's mouth.
- Image prompts must not name or depict real, identifiable people, logos or brands: use symbolic,
  scenic or illustrative imagery. Consistent style across scenes: cinematic, moody, photographic.
- Narration is plain spoken text: no emojis, no stage directions, no scene numbers."""
    return _call(cfg["gemini_model"], prompt)


def fact_check(cfg, film, candidates):
    sources = "\n".join(f"- {c['title']}: {c['summary']}" for c in candidates[:30])
    prompt = f"""You are a careful fact-checker for a short documentary script.

Script JSON:
{json.dumps(film, ensure_ascii=False)}

Source headlines that may support it:
{sources}

Check every factual claim in each scene's "narration". Keep claims that are supported by the sources or are
well-established common knowledge. Rewrite or remove anything uncertain, exaggerated, or likely wrong,
keeping the same number of scenes and a similar length. Do not add new facts.

Return ONLY JSON with the SAME structure as the script (topic, title, description, hashtags, scenes with
narration and image_prompt), plus a field "changes" listing in short strings what you corrected."""
    return _call(cfg["gemini_model"], prompt)


def translate_zh(cfg, film):
    narrations = [s["narration"] for s in film["scenes"]]
    prompt = f"""Translate each of these narration lines into natural Simplified Chinese suitable for subtitles.
Keep the same number of lines, in the same order. Keep each line concise.

Lines: {json.dumps(narrations, ensure_ascii=False)}

Return ONLY JSON: {{"lines": ["...", "..."], "title": "Chinese title", "description": "Chinese description"}}"""
    return _call(cfg["gemini_model"], prompt)


# ---------------- film mode ----------------
def write_episode(cfg, bible, film, scene, next_scene):
    """Expand one scene beat from the bible into shots with dialogue, keeping continuity."""
    cast_ids = list(scene["cast"])
    humans = [c for c in cast_ids if c in bible["characters"]]
    cast_info = "\n".join(
        f"- {c}: {bible['characters'][c]['name']} | style: {bible['characters'][c].get('speaking_style', 'plain')}"
        f" | personality: {bible['characters'][c].get('personality', '')}"
        for c in humans
    )
    infected_ids = [c for c in cast_ids if c in bible["infected"]]
    state_now = {c: film["chars"][c] for c in cast_ids if c in film["chars"]}
    dead = [c for c, v in film["chars"].items() if str(v.get("status", "")).lower().startswith("dead")]
    recap = " ".join(film["summaries"][-3:]) or "This is the first episode."
    nxt = f"{next_scene['title']}: {next_scene['beat']}" if next_scene else "This is the final episode."
    prompt = f"""You are the screenwriter and director of a realistic British survival-horror film called "{bible['title']}".
You are writing EPISODE {scene['n']} of {len(bible['scenes'])} (about 75 seconds when performed).

FILM RULES: {bible['dialogue_rules']}
WORLD: {json.dumps(bible['world'], ensure_ascii=False)}
INFECTION RULES (never break them): {json.dumps(bible['infection'], ensure_ascii=False)}

THIS EPISODE (follow the beat faithfully, do not add major events):
Title: {scene['title']}
Location: {scene['loc']} | Time: {scene['time']} | Weather: {scene['weather']}
Beat: {scene['beat']}
Main emotion: {scene['emotion']}
Continuity notes: {scene['notes']}

CAST (use ONLY these ids as characters and speakers): {cast_ids}
{cast_info}
Infected ids available as characters (never speakers): {infected_ids}
Speakers may also be NARRATOR (use at most once, only for a short place-and-time title line).
Characters who are DEAD and must not appear: {dead}

CONTINUITY TRACKER NOW: {json.dumps(state_now, ensure_ascii=False)}
PREVIOUSLY: {recap}
NEXT EPISODE (lead into it, do not show it): {nxt}

Return ONLY JSON:
{{
  "episode_title": "short title",
  "description": "2 teaser sentences, no spoilers beyond this episode",
  "shots": [
    {{
      "characters": ["MARCUS"],
      "camera": "shot size, lens and camera movement",
      "visual": "exactly what the image shows: action, facial expression, emotion, body language, key props",
      "lines": [{{"speaker": "MARCUS", "text": "spoken words"}}]
    }}
  ],
  "continuity_update": {{"MARCUS": {{"status": "alive", "visible": "ALL currently visible injuries or costume changes", "carries": "objects held", "knows": "key facts learned"}}}},
  "summary": "two sentences recapping what happened, for the next episode"
}}

RULES:
- 8 to 10 shots. Each shot lists at most TWO named cast ids in "characters" (plus at most one infected id). Keep the same faces and costumes by never describing them in "visual": describe only action, expression, emotion, and props.
- A shot may have 0, 1 or 2 lines. Total spoken words across the episode: 150 to 190. Each line under 20 words. Natural British speech, interruptions and silences allowed.
- Show fear, anger, grief and relief through expression and body language. Violence is never shown; cut away.
- Respect continuity: injuries, lost or held objects, who knows what, who is alive. In "continuity_update" include every cast character whose appearance, objects, knowledge or status changed.
- Open with a strong hook image and end on a small cliffhanger or emotional beat that leads into the next episode.
- No gore, no blood close-ups, no real people, no brand names."""
    return _call(cfg["gemini_model"], prompt)
