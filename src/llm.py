"""Google Gemini (free tier) helpers. All calls return parsed JSON."""
import json
import os
import re
import time

import requests


def _call(model, prompt, retries=3):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(retries):
        r = requests.post(
            url,
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
            },
            timeout=180,
        )
        if r.status_code in (429, 500, 503):  # free-tier rate limit or busy server
            wait = 20 * (attempt + 1)
            print(f"  Gemini busy ({r.status_code}), retrying in {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        return json.loads(text)
    raise RuntimeError("Gemini kept failing; try again later")


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
