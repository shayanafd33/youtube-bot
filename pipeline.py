"""Multi-platform content engine (TikTok + YouTube Shorts + Facebook Reels + Bilibili).

ONE film is generated per day (script, voice, images, music). From it we render platform-specific versions
(framing, subtitle safe zones, copy) and each platform module publishes independently via an official API.
A failure in one platform never blocks the others. TikTok behaviour is unchanged.
"""
import os, json, random, re, subprocess, base64, datetime, pathlib, sys, time, urllib.parse, textwrap
from concurrent.futures import ThreadPoolExecutor
import requests

from platforms import tiktok, youtube, facebook, bilibili
from platforms.common import LONDON, host_files

ROOT = pathlib.Path(__file__).parent
WORK = ROOT / "work"; WORK.mkdir(exist_ok=True)
OUT = ROOT / "out"; OUT.mkdir(exist_ok=True)
STATE_F = ROOT / "state.json"
MODULES = {m.NAME: m for m in (tiktok, youtube, facebook, bilibili)}
TODAY = datetime.datetime.now(LONDON).date().isoformat()

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
VOICE_BACKEND = os.getenv("VOICE_BACKEND", "kokoro")      # kokoro (free) | elevenlabs
VISUAL_MODE = os.getenv("VISUAL_MODE", "images")          # images (free) | video (paid, fal.ai)
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "fal-ai/kling-video/v2.1/standard/text-to-video")
POST_TIME_UK = os.getenv("POST_TIME_UK", "19:30")          # UK local time, DST handled automatically
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
LOOKAHEAD = int(os.getenv("LOOKAHEAD_DAYS") or 9)       # Buffer free plan: max 10 queued posts per channel
MAX_FILMS = int(os.getenv("MAX_FILMS_PER_RUN") or 4)       # films built per run (each takes ~15-30 min)
STYLE = ("Cinematic still, photorealistic, dramatic lighting, shallow depth of field, 35mm film look, "
         "vertical 9:16 composition, no text, no logos, no watermarks, no recognisable real people. ")
BLOCKED = re.compile(r"marvel|disney|pixar|star wars|harry potter|pokemon|nintendo|netflix|"
                     r"trump|biden|musk|king charles|taylor swift", re.I)



def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def run(cmd): subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def load_state():
    s = json.loads(STATE_F.read_text())
    s.setdefault("posted", {}); s.setdefault("topics", []); s.setdefault("platforms", {})
    return s


def save_state(s): STATE_F.write_text(json.dumps(s, indent=1))


GEMINI_MODELS = os.getenv("GEMINI_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite")  # fallback list only
_MODEL_CACHE = []


def _gemini_models():
    """Ask Google which Flash models this key can use today (names change; old ones 404), best first."""
    if _MODEL_CACHE: return list(_MODEL_CACHE)
    found = []
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                         headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=60)
        for m in r.json().get("models", []):
            n = m["name"].split("/")[-1]
            if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                    and not any(x in n for x in ("image", "tts", "live", "audio", "embed", "robot", "computer", "native"))):
                v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
                found.append((1 if "lite" in n else 0, -(float(v.group(1)) if v else 0), n))
    except Exception as ex:
        log("model discovery failed, using fallback list:", str(ex)[:120])
    names = [n for _, _, n in sorted(found)][:6]
    for m in [x.strip() for x in GEMINI_MODELS.split(",") if x.strip()]:
        if not found and m not in names: names.append(m)
    log("gemini models:", names)
    _MODEL_CACHE.extend(names)
    return list(names)


def _parse(t):
    return json.loads(t[t.index("{"): t.rindex("}") + 1])


def _ask_gemini(prompt):
    """Free: Google AI Studio key (no card). Rotates through models and keeps retrying for ~10 min,
    because free-tier models are sometimes briefly overloaded (HTTP 503) or rate limited (429)."""
    models = _gemini_models()
    errors = []
    for attempt in range(6):
        for model in list(models):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json",
                                               "temperature": 0.9, "maxOutputTokens": 8000}},
                    timeout=180)
            except Exception as ex:
                errors.append(f"{model}: {ex}"); continue
            if r.status_code == 200:
                try:
                    out = _parse(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    time.sleep(13)  # stay under free-tier requests-per-minute
                    return out
                except Exception as ex:
                    errors.append(f"{model}: unusable reply ({ex})"); continue
            errors.append(f"{model}: HTTP {r.status_code}")
            log("gemini", errors[-1])
            if r.status_code in (400, 403, 404):  # wrong model name / bad key: don't retry this model
                models.remove(model)
        if not models: break
        wait = 30 * (attempt + 1)
        log(f"all models busy, waiting {wait}s (attempt {attempt + 1}/6)"); time.sleep(wait)
    sys.exit("Gemini failed after retries: " + "; ".join(errors[-8:]))


def ask_json(prompt, max_tokens=4000):
    if os.getenv("GEMINI_API_KEY"):
        return _ask_gemini(prompt)
    import anthropic  # paid fallback, only used if no Gemini key is set
    r = anthropic.Anthropic().messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens,
                                              messages=[{"role": "user", "content": prompt}])
    return _parse(r.content[0].text)


# ---------- 1. trends ----------
def candidates():
    import feedparser
    feeds = ["https://trends.google.com/trending/rss?geo=GB",
             "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
             "https://feeds.bbci.co.uk/news/technology/rss.xml"]
    items = []
    for f in feeds:
        try:
            for e in feedparser.parse(f).entries[:15]:
                items.append(f"- {e.get('title','')} :: {e.get('summary','')[:160]}")
        except Exception as ex:
            log("feed failed", f, ex)
    return "\n".join(items)


# ---------- 2. script (+ independent fact/safety review) ----------
def review(d):
    r = ask_json(f"""You are a strict fact-checker and TikTok policy reviewer. Review this script for a UK
science/future/mystery channel. Fail it (ok=false) if it: states uncertain things as fact, invents statistics,
quotes or studies, makes medical/financial/safety claims, promotes conspiracy theories, names or depicts real
people in invented scenarios, mentions brands/IP, or could mislead viewers about real events.
Speculation clearly framed as "what if"/"scientists think" is fine.
Script: {json.dumps(d['scenes'])}
Return ONLY JSON: {{"ok": bool, "issues": [str]}}""", 800)
    return r


def make_script(state, ahead=0):
    trends = candidates()
    feedback = ""
    timing = (f"This video will be published in {ahead} days, so choose an angle that will still feel fresh then "
              f"(an evergreen what-if / explainer linked to the news item), not breaking news.\n" if ahead > 1 else "")
    timing += "If none of the items is suitable or all are already used, invent an original evergreen 'What if' science idea.\n"
    for attempt in range(4):
        d = ask_json(f"""You write original TikTok scripts for a UK channel in the niche "What If, Future, Science & Mystery".
Today's UK trending/news items:
{trends}

Recently used topics (do NOT repeat): {state['topics'][-30:]}
{feedback}
{timing}Pick the ONE item that best fits the niche and will interest UK viewers (or a clearly connected science/future angle).
Rules:
- UK English, fully original wording, 150-185 words of narration (about 65-85 seconds spoken).
- Strong 1-sentence hook first; end with a question that invites comments.
- Say the main topic keyword naturally in the first sentence (TikTok search reads spoken words and on-screen text).
- Factually careful; frame speculation as speculation. No invented stats/quotes, no real named people in invented scenarios,
  no brands or copyrighted characters.
- 11-15 scenes, each ~12-16 words of narration plus a visual prompt (subject, setting, camera feel, lighting; no text, no real people).
Return ONLY JSON: {{"topic": str, "keyword": str, "scenes": [{{"narration": str, "visual": str}}]}}""")
        words = sum(len(s["narration"].split()) for s in d["scenes"])
        if not (135 <= words <= 195 and len(d["scenes"]) >= 8):
            feedback = f"Previous attempt had {words} words; keep 150-185."; continue
        if any(BLOCKED.search(s["visual"] + s["narration"]) for s in d["scenes"]):
            feedback = "Previous attempt mentioned a blocked brand/person; avoid all brands and real people."; continue
        rv = review(d)
        if rv.get("ok"):
            return d
        log("review failed:", rv.get("issues"))
        feedback = "Previous attempt was rejected by a fact-checker for: " + "; ".join(rv.get("issues", []))
    sys.exit("no script passed review - skipping today rather than posting something doubtful")



# ---------- 3. SEO post copy ----------
def make_copy(d):
    c = ask_json(f"""Write TikTok post copy for this video (UK audience, niche: What If / Future / Science / Mystery).
Topic: {d['topic']}. Main keyword: {d['keyword']}.
Narration: {' '.join(s['narration'] for s in d['scenes'])}
Rules:
- title: max 80 chars, main keyword in the first words, curiosity-driven but NOT misleading or clickbait-false.
- caption: 1-2 natural sentences (max 200 chars) using the keyword and 1-2 related search phrases people really type,
  ending with a question that invites comments. No keyword stuffing, no "like/follow for" engagement bait.
- hashtags: 4 or 5, lowercase, all genuinely relevant: 1-2 niche (e.g. whatif, science, futuretech, mystery),
  1-2 specific to this topic, optionally 1 UK one (e.g. uk) only if truly relevant. No #fyp/#viral spam, no brand tags.
Return ONLY JSON: {{"title": str, "caption": str, "hashtags": [str]}}""", 800)
    tags, seen = [], set()
    for h in c["hashtags"]:
        h = re.sub(r"[^a-z0-9]", "", h.lower())
        if h and h not in seen and h not in ("fyp", "foryou", "foryoupage", "viral"):
            seen.add(h); tags.append("#" + h)
    title = c["title"].strip()[:90]
    caption = c["caption"].strip()[:230]
    text = f"{title}\n\n{caption}\n\n\U0001F916 AI-generated visuals & voiceover\n{' '.join(tags[:5])}"
    return {"title": title, "text": text, "caption": caption, "tags": tags[:5]}


# ---------- 4. voice (returns words, scene start times, end time, file) ----------
def _spread(words, t0, t1):
    tot = sum(len(w) for w in words) or 1
    out, t = [], t0
    for w in words:
        dt = (t1 - t0) * len(w) / tot
        out.append((w, t, t + dt)); t += dt
    return out


def voice_kokoro(scenes):
    import numpy as np, soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="b")  # British English
    voice = os.getenv("KOKORO_VOICE", "bm_george")
    sr, gap = 24000, int(0.18 * 24000)
    audio, starts, words, pos = [], [], [], 0
    for s in scenes:
        chunks = [np.asarray(a.numpy() if hasattr(a, "numpy") else a, dtype="float32")
                  for _, _, a in pipe(s["narration"], voice=voice, speed=0.98)]
        a = np.concatenate(chunks)
        t0, t1 = pos / sr, (pos + len(a)) / sr
        starts.append(t0); words += _spread(s["narration"].split(), t0, t1)
        audio += [a, np.zeros(gap, dtype="float32")]; pos += len(a) + gap
    path = WORK / "voice.wav"
    sf.write(path, np.concatenate(audio), sr)
    return words, starts, pos / sr, path


def voice_eleven(scenes):
    parts = [s["narration"].strip() for s in scenes]
    text, offs, p = " ".join(parts), [], 0
    for x in parts:
        offs.append(p); p += len(x) + 1
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{os.getenv('ELEVEN_VOICE_ID','JBFqnCBsd6RMkjVDRZzb')}/with-timestamps",
        headers={"xi-api-key": os.environ["ELEVEN_API_KEY"]},
        json={"text": text, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3}}, timeout=300)
    r.raise_for_status(); j = r.json()
    path = WORK / "voice.mp3"; path.write_bytes(base64.b64decode(j["audio_base64"]))
    al = j["alignment"]; words, cur, s0, e0 = [], "", 0, 0
    for c, a, b in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if c.isspace():
            if cur: words.append((cur, s0, e0)); cur = ""
        else:
            if not cur: s0 = a
            cur += c; e0 = b
    if cur: words.append((cur, s0, e0))
    starts = [al["character_start_times_seconds"][o] for o in offs]
    return words, starts, al["character_end_times_seconds"][-1], path


def fit_voice(words, starts, end, path, limit=86.0):
    """If the narration is longer than `limit` seconds, speed it up (max 1.25x) and rescale all timings."""
    if end <= limit: return words, starts, end, path
    f = max(limit / end, 0.8)                      # time factor (<1 = faster)
    out = WORK / "voice_fit.wav"
    run(["ffmpeg", "-y", "-i", str(path), "-filter:a", f"atempo={1 / f:.4f}", str(out)])
    log(f"narration was {end:.0f}s: sped up x{1 / f:.2f} to fit")
    return [(w, s * f, e * f) for w, s, e in words], [s * f for s in starts], end * f, out


def ass_time(t):
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"



# ---------- 5. visuals ----------
def gen_image(i, visual):
    q = urllib.parse.quote((STYLE + visual)[:900]); seed = random.randint(1, 999999)
    key = (os.getenv("POLLINATIONS_KEY") or "").strip()
    tries = []
    if key:   # free key from enter.pollinations.ai - the supported route
        tries.append((f"https://gen.pollinations.ai/image/{q}?model=flux&width=1080&height=1920&seed={seed}&nologo=true",
                      {"Authorization": f"Bearer {key}"}))
    tries.append((f"https://image.pollinations.ai/prompt/{q}?model=flux&width=1080&height=1920&seed={seed}&nologo=true", {}))
    for attempt in range(3):
        for url, hdr in tries:
            try:
                r = requests.get(url, headers=hdr, timeout=90)
                ct = r.headers.get("content-type", "")
                if r.ok and ct.startswith("image") and len(r.content) > 20000:
                    p = WORK / f"img_{i}.jpg"; p.write_bytes(r.content); time.sleep(4 if key else 16); return p
                log(f"image {i}: {url.split('/')[2]} -> HTTP {r.status_code} {ct}", "" if ct.startswith("image") else r.text[:120].replace("\n", " "))
            except Exception as ex:
                log(f"image {i}: {url.split('/')[2]} failed: {str(ex)[:120]}")
        time.sleep(15)
    return None


def gen_clip(i, visual):
    import fal_client
    for attempt in range(3):
        try:
            res = fal_client.subscribe(VIDEO_MODEL, arguments={"prompt": STYLE + visual, "aspect_ratio": "9:16", "duration": "5"})
            p = WORK / f"clip_{i}.mp4"; p.write_bytes(requests.get(res["video"]["url"], timeout=300).content); return p
        except Exception as ex:
            log("clip", i, "failed", ex); time.sleep(5)
    return None


# ---------- music: your own licensed tracks, else auto-download Kevin MacLeod (CC BY 4.0, credit added to caption) ----------
MUSIC_TRACKS = ["Long Note Four", "Ice Flow", "Dreamlike",
                "Echoes of Time v2", "Cipher", "Ossuary 1 - A Beginning", "Ossuary 6 - Air", "Mesmerize"]


def pick_music():
    """Returns (file or None, credit line or None). Never stops the run: worst case = voice only."""
    mdir = ROOT / "music"
    if (mdir / "LICENCES.md").exists():
        local = [x for x in mdir.glob("*") if x.suffix.lower() in (".mp3", ".wav", ".m4a")]
        if local: return random.choice(local), None
    if os.getenv("MUSIC_AUTO", "1") != "1": return None, None
    titles = MUSIC_TRACKS[:]; random.shuffle(titles)
    for t in titles:
        url = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/" + urllib.parse.quote(t) + ".mp3"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
            if r.status_code == 200 and len(r.content) > 300_000:
                f = WORK / "music_auto.mp3"; f.write_bytes(r.content)
                d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                   capture_output=True, text=True)
                if d.returncode == 0 and float(d.stdout.strip() or 0) > 20:
                    log("music:", t)
                    return f, f'Music: "{t}" by Kevin MacLeod (incompetech.com), CC BY 4.0'
            log("music not usable:", t, r.status_code)
        except Exception as ex:
            log("music failed", t, ex)
    log("no music could be downloaded")
    return None, None



# ---------- platform variants (framing, subtitle safe zones, size caps) ----------
VARIANTS = {
    #            canvas        subtitle baseline / size   hook title            bitrate cap  layout       max length
    "tiktok":   dict(w=1080, h=1920, margin=520, font=88, hook_size=96, hook_margin=260, maxrate="6M", landscape=False, max_s=None),
    "youtube":  dict(w=1080, h=1920, margin=420, font=88, hook_size=96, hook_margin=260, maxrate="6M", landscape=False, max_s=179),
    "facebook": dict(w=1080, h=1920, margin=430, font=86, hook_size=96, hook_margin=260, maxrate="6M", landscape=False, max_s=89.5),
    "bilibili": dict(w=1920, h=1080, margin=170, font=62, hook_size=70, hook_margin=70, maxrate="8M", landscape=True, max_s=None),
}


def _clean(t):
    return t.replace("{", "").replace("}", "").replace("\\", "")


def make_subs(words, hook, spec, out, zh=None):
    """Bottom: 3-word captions with the spoken word highlighted. Top: hook title for ~3 s.
    zh: optional list of (start, end, text) Chinese lines shown under the English captions (Bilibili)."""
    W, H = spec["w"], spec["h"]
    outline = 5 if spec["landscape"] else 7
    st = ("Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,"
          "StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n")
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n" + st +
            f"Style: Default,Liberation Sans,{spec['font']},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,2,60,60,{spec['margin']},1\n"
            f"Style: Hook,Liberation Sans,{spec['hook_size']},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,3,8,70,70,{spec['hook_margin']},1\n"
            f"Style: ZH,Noto Sans CJK SC,{int(spec['font'] * 0.85)},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,40,1\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    if hook:
        h = "\\N".join(textwrap.wrap(_clean(hook).upper(), 28 if spec["landscape"] else 20)[:4])
        lines.append(f"Dialogue: 1,{ass_time(0.1)},{ass_time(3.2)},Hook,,0,0,0,,{{\\fad(200,350)}}{h}")
    for i in range(0, len(words), 3):
        g = words[i:i + 3]
        group_end = words[i + 3][1] if i + 3 < len(words) else g[-1][2] + 0.3
        for j, w in enumerate(g):
            s = w[1]; e = g[j + 1][1] if j + 1 < len(g) else group_end
            txt = " ".join(("{\\c&H0000FFFF&}" + _clean(x[0]).upper() + "{\\c&H00FFFFFF&}") if k == j else _clean(x[0]).upper()
                           for k, x in enumerate(g))
            lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Default,,0,0,0,,{txt}")
    for s, e, t in (zh or []):
        t = "\\N".join(textwrap.wrap(_clean(t), 26)[:2])
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},ZH,,0,0,0,,{t}")
    pathlib.Path(out).write_text(head + "\n".join(lines))


# ---------- 6. render: ONE clean master, then a version per platform ----------
def probe_duration(p):
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    return float(d.stdout.strip())


def build_master(starts, end, voice_path, media, music=None):
    """Concatenate the visuals, mix voice + music. No subtitles yet. Returns (master_path, total_seconds)."""
    total = end + 0.6
    seg_starts = [0.0] + starts[1:]; seg_ends = seg_starts[1:] + [total]
    good, segs = None, []
    for i, m in enumerate(media):
        m = m or good
        if m is None: sys.exit("no visuals generated")
        good = m; d = max(seg_ends[i] - seg_starts[i], 1.0); seg = WORK / f"seg_{i}.mp4"
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
        if m.suffix == ".jpg":
            n = int(d * 30) + 3
            z = f"1+0.22*on/{n}" if i % 2 == 0 else f"1.22-0.22*on/{n}"
            vf = (f"scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps=30")
            run(["ffmpeg", "-y", "-i", str(m), "-vf", vf, "-t", f"{d:.3f}"] + enc + [str(seg)])
        else:
            vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,"
                  "tpad=stop_mode=clone:stop_duration=15")
            run(["ffmpeg", "-y", "-i", str(m), "-an", "-t", f"{d:.3f}", "-vf", vf] + enc + [str(seg)])
        segs.append(seg)
    (WORK / "list.txt").write_text("".join(f"file '{s.resolve()}'\n" for s in segs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(WORK / "list.txt"), "-c", "copy", str(WORK / "video.mp4")])
    master = WORK / "master.mp4"
    base = ["ffmpeg", "-y", "-i", str(WORK / "video.mp4"), "-i", str(voice_path)]
    if music:
        base += ["-stream_loop", "-1", "-i", str(music)]
        fc = (f"[1:a]asplit=2[v1][v2];[2:a]volume=0.4[m];"
              f"[m][v1]sidechaincompress=threshold=0.03:ratio=10:attack=20:release=400[md];"
              f"[v2][md]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={total-2:.2f}:d=2[a]")
    else:
        log("no music - voice only"); fc = "[1:a]anull[a]"
    run(base + ["-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", str(master)])
    return master, total


def render_variant(name, master, ass, out):
    sp = VARIANTS[name]
    if sp["landscape"]:   # 16:9: blurred full-frame background with the vertical film centred on top
        fc = ("[0:v]split[a][b];[b]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=40:5[bg];"
              f"[a]scale=-2:1080[fg];[bg][fg]overlay=(W-w)/2:0,ass={ass}[v]")
    else:
        fc = f"[0:v]ass={ass}[v]"
    run(["ffmpeg", "-y", "-i", str(master), "-filter_complex", fc, "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", sp["maxrate"], "-bufsize", f'{int(sp["maxrate"][:-1]) * 2}M',
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)])
    return out


def make_cover(video, out):
    run(["ffmpeg", "-y", "-ss", "3", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=1280:800:force_original_aspect_ratio=increase,crop=1280:800", "-q:v", "3", str(out)])
    return out


# ---------- extra copy for the other platforms (one free-tier call; falls back to plain copy) ----------
def _fallback_copy(base, enabled, scenes):
    tags = " ".join(base["tags"][:3])
    out = {}
    if "youtube" in enabled:
        out["youtube"] = {"title": base["title"][:91] + " #Shorts",
                          "description": f"{base['caption']}\n\nAI-generated visuals and voiceover.\n{tags} #shorts",
                          "tags": [t.lstrip("#") for t in base["tags"]]}
    if "facebook" in enabled:
        out["facebook"] = {"title": base["title"], "text": f"{base['caption']}\n\nAI-generated visuals and voiceover.\n{tags}"}
    if "bilibili" in enabled:
        out["bilibili"] = {"title": base["title"][:79], "desc": base["caption"][:200] + " (AI-generated)",
                           "tags": "science,future,what if", "scenes": None}
    return out


def make_extra_copy(d, base, enabled):
    scenes = d["scenes"]
    parts = []
    if "youtube" in enabled:
        parts.append('"youtube": {"title": max 90 chars, main keyword first, honest (no clickbait lies); "description": 3-4 short lines: '
                     '1-2 natural sentences using the keyword and related search phrases, then a question, then the line '
                     '"AI-generated visuals and voiceover.", then exactly 3 relevant lowercase hashtags; "tags": 8-12 search tags without #}')
    if "facebook" in enabled:
        parts.append('"facebook": {"title": max 80 chars; "text": 2-3 short conversational sentences ending with a question, then the line '
                     '"AI-generated visuals and voiceover.", then 2-3 relevant hashtags}')
    if "bilibili" in enabled:
        parts.append(f'"bilibili": {{"title": Simplified Chinese, max 40 characters, honest; "desc": Simplified Chinese, max 180 characters, '
                     f'ending with 本视频画面与配音由AI生成。; "tags": 6-8 Simplified Chinese tags as an array; '
                     f'"scenes": array of exactly {len(scenes)} Simplified Chinese translations of the narration lines below, in order}}')
    narr = "\n".join(f"{i+1}. {s['narration']}" for i, s in enumerate(scenes))
    try:
        raw = ask_json(f"""Write platform-specific post copy for this short video (science / future / what-if niche).
Topic: {d['topic']}. Main keyword: {d['keyword']}. Be factually careful and do not exaggerate.
Narration lines:
{narr}
Return ONLY JSON with exactly these keys: {{ {', '.join(parts)} }}""", 4000)
    except (Exception, SystemExit) as ex:
        log("extra copy failed, using plain fallback:", str(ex)[:150]); return _fallback_copy(base, enabled, scenes)
    out = _fallback_copy(base, enabled, scenes)
    try:
        if "youtube" in enabled and "youtube" in raw:
            y = raw["youtube"]; t = y["title"].replace("#Shorts", "").strip()[:91].rstrip()
            out["youtube"] = {"title": t + " #Shorts", "description": y["description"][:4500] + "\n#shorts",
                              "tags": [str(x).lstrip("#")[:30] for x in y.get("tags", [])][:12]}
        if "facebook" in enabled and "facebook" in raw:
            f = raw["facebook"]; out["facebook"] = {"title": f.get("title", base["title"])[:100], "text": f["text"][:1500]}
        if "bilibili" in enabled and "bilibili" in raw:
            b = raw["bilibili"]; sc = b.get("scenes")
            tags = ",".join(str(x).strip() for x in b.get("tags", []))[:199]
            out["bilibili"] = {"title": b["title"][:79], "desc": b["desc"][:249], "tags": tags or "科学,未来",
                               "scenes": sc if isinstance(sc, list) and len(sc) == len(scenes) else None}
    except Exception as ex:
        log("extra copy unusable, partly using fallback:", ex)
    return out


# ---------- engine ----------
def add_credit(copies, credit):
    if not credit: return
    for k, key in (("tiktok", "text"), ("youtube", "description"), ("facebook", "text")):
        if k in copies:
            c = copies[k]; head, _, tags = c[key].rpartition("\n")
            c[key] = f"{head}\n{credit}\n{tags}" if head else f"{c[key]}\n{credit}"
    if "bilibili" in copies:
        copies["bilibili"]["desc"] = (copies["bilibili"]["desc"] + " " + credit)[:249]


def plan_queue(state, enabled):
    """[(day, [platforms that still need a post that day])] for the next LOOKAHEAD days, oldest first."""
    missing = {}
    for n in enabled:
        m = MODULES[n]
        if not m.HAS_SLOT: continue
        first = m.slot().date()
        for i in range(LOOKAHEAD):
            d = (first + datetime.timedelta(days=i)).isoformat()
            done = state["platforms"].get(n, {}).get(d) or (n == "tiktok" and state["posted"].get(d))
            if DRY_RUN or not done: missing.setdefault(d, []).append(n)
    queue = [(d, missing[d]) for d in sorted(missing)]
    # platforms with no schedule field (Bilibili) ride along with the first film of each run, once per day
    extra = [n for n in enabled if not MODULES[n].HAS_SLOT and (DRY_RUN or not state["platforms"].get(n, {}).get(TODAY))]
    if extra and queue: queue[0] = (queue[0][0], queue[0][1] + extra)
    return queue


def produce_film(state, day, todo):
    """Build ONE film for publishing day `day`, render every platform's version, publish each independently.
    Returns the number of platforms that failed."""
    day_date = datetime.date.fromisoformat(day)
    ahead = max((day_date - datetime.datetime.now(LONDON).date()).days, 0)
    for f in list(WORK.glob("img_*.jpg")) + list(WORK.glob("clip_*.mp4")) + list(WORK.glob("seg_*.mp4")): f.unlink()
    plan = {}
    for n in todo:
        m = MODULES[n]; slot = m.slot(day_date) if m.HAS_SLOT else None
        plan[n] = dict(mod=m, mode=m.resolve(), slot=slot, pkey=day if slot else TODAY)
    log(f"=== film for {day} (+{ahead} days) -> {', '.join(f'{n}:{plan[n]['mode']}' for n in todo)} ===")

    # --- generate the film ONCE ---
    d = make_script(state, ahead); log("topic:", d["topic"])
    base = make_copy(d); log("post copy:\n" + base["text"])
    copies = {"tiktok": {"title": base["title"], "text": base["text"]}}
    if any(n != "tiktok" for n in todo):
        copies.update(make_extra_copy(d, base, [n for n in todo if n != "tiktok"]))
    scenes = d["scenes"]
    words, starts, end, vpath = fit_voice(*(voice_eleven if VOICE_BACKEND == "elevenlabs" else voice_kokoro)(scenes))
    if VISUAL_MODE == "video":
        with ThreadPoolExecutor(4) as ex: media = list(ex.map(lambda x: gen_clip(*x), enumerate(s["visual"] for s in scenes)))
    else:
        media = []   # sequential: free tier is throttled
        for i, s in enumerate(scenes):
            media.append(gen_image(i, s["visual"]))
            if i == 2 and not any(media):
                sys.exit("The image service refused the first 3 images (see the 'image' log lines above). "
                         "Add a free POLLINATIONS_KEY secret (enter.pollinations.ai) and run again.")
    music, credit = pick_music()
    add_credit(copies, credit)
    master, total = build_master(starts, end, vpath, media, music)
    log(f"master ready ({total:.0f}s)")

    # --- platform-specific versions ---
    variants, covers = {}, {}
    for n in todo:
        sp = VARIANTS[n]; zh = None
        if n == "bilibili" and copies.get("bilibili", {}).get("scenes"):
            ss = starts + [total]
            zh = [(ss[i], ss[i + 1], t) for i, t in enumerate(copies["bilibili"]["scenes"])]
        ass = WORK / f"subs_{n}.ass"
        make_subs(words, base["title"], sp, ass, zh)
        variants[n] = render_variant(n, master, ass, OUT / f"{day}-{n}.mp4")
        if n == "bilibili": covers[n] = make_cover(variants[n], OUT / f"{day}-bilibili-cover.jpg")
        log(f"version ready: {n} ({probe_duration(variants[n]):.0f}s)")
    (OUT / f"{day}.json").write_text(json.dumps({"script": d, "copy": copies}, indent=1, ensure_ascii=False))
    if DRY_RUN:
        log("dry run - nothing published"); return 0

    # --- publish: every platform independently ---
    urls, host_err = {}, None
    need_host = [n for n in todo if plan[n]["mode"] == "buffer"]
    if need_host:
        try: urls = host_files({n: variants[n] for n in need_host}, day)
        except Exception as ex: host_err = f"media hosting failed: {ex}"
    results, any_ok = {}, False
    for n in todo:
        p = plan[n]; m = p["mod"]
        ctx = dict(video=variants[n], url=urls.get(n), slot=p["slot"], copy=copies.get(n, {}), mode=p["mode"],
                   key=day, out=OUT, cover=covers.get(n))
        try:
            mx = VARIANTS[n]["max_s"]
            if mx and probe_duration(variants[n]) > mx and p["mode"] != "package":
                raise RuntimeError(f"video is {probe_duration(variants[n]):.0f}s, over the {mx:.0f}s limit for {n}")
            if p["mode"] == "buffer" and host_err: raise RuntimeError(host_err)
            if p["mode"] == "package" and not hasattr(m, "package"):
                (OUT / f"{day}-{n}.txt").write_text(json.dumps(copies.get(n, {}), indent=1, ensure_ascii=False))
                res = f"packaged:{variants[n].name}"
            else:
                res = m.publish(ctx)
                if p["mode"] != "package": variants[n].unlink(missing_ok=True)   # delivered: keep Actions storage small
            results[n] = ("OK", p["mode"], str(res)); any_ok = True
            state["platforms"].setdefault(n, {})[p["pkey"]] = str(res)
            if n == "tiktok": state["posted"][p["pkey"]] = str(res)
            save_state(state)           # saved immediately so a later crash can't cause a duplicate post
        except (Exception, SystemExit) as ex:
            results[n] = ("FAILED", p["mode"], str(ex)[:400])
    if any_ok:
        state["topics"].append(d["topic"]); save_state(state)
    for n, (s, mode, info) in results.items():
        log(f"  {day} {n:9} {s:7} via {mode:8} {info}")
    return sum(1 for s, _, _ in results.values() if s == "FAILED")


def main():
    state = load_state()
    enabled = [p.strip().lower() for p in (os.getenv("PLATFORMS") or "tiktok").split(",") if p.strip().lower() in MODULES]
    queue = plan_queue(state, enabled)
    log("platforms:", {n: MODULES[n].resolve() for n in enabled}, "| lookahead days:", LOOKAHEAD)
    if not queue:
        log(f"queue is full: every platform already has its next {LOOKAHEAD} days scheduled. Nothing to do."); return
    batch = queue[:1] if DRY_RUN else queue[:MAX_FILMS]
    log(f"{len(queue)} day(s) still to schedule; building {len(batch)} film(s) this run:", [d for d, _ in batch])
    failed = 0
    for day, todo in batch:
        try:
            failed += produce_film(state, day, todo)
        except (Exception, SystemExit) as ex:
            log(f"!! film for {day} could not be built: {str(ex)[:300]}")
            failed += 1
            break   # same cause (images, Gemini) would hit the next film too; the next daily run retries
    today = datetime.datetime.now(LONDON).date().isoformat()
    log("---- scheduled days per platform ----")
    for n in enabled:
        ds = sorted(d for d in state["platforms"].get(n, {}) if d >= today)
        log(f"{n:9} {len(ds)} day(s): {ds[0] if ds else '-'} .. {ds[-1] if ds else '-'}")
    if failed:
        sys.exit(f"{failed} problem(s) this run - posts already scheduled are unaffected; see the log above")


if __name__ == "__main__":
    main()
