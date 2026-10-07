# THE FORGETTING: daily AI film bot (free, runs on GitHub Actions)

One episode a day of a 40-episode realistic zombie film (`story/bible.json`), made in the cloud and scheduled by Buffer to
**YouTube Shorts, TikTok and Facebook Reels**. Your laptop can be off. The full production package is in `FILM_BIBLE.md`.

**Film mode** (default, `"mode": "film"` in config.json) reads the next episode from the story bible, keeps characters
looking the same by repeating their locked descriptions in every image prompt, gives every character their own voice, and
tracks injuries, objects and who is alive from episode to episode. Set `"mode": "news"` for the old daily news-story mode.

```
Google Trends UK + BBC RSS -> Gemini (script + fact-check + Chinese) -> Kokoro British voice
-> Pollinations Flux images -> FFmpeg (zoom, subtitles, music) -> GitHub Release (public link)
-> Buffer API (scheduled at your chosen time)
```

## Setup (in order)

### 1. Buffer
1. Make a free account at buffer.com and connect your **YouTube**, **TikTok** and **Facebook Page** (free plan = 3 channels).
2. Open https://publish.buffer.com/settings/api and create an **API key**. Copy it.

### 2. Gemini key
https://aistudio.google.com/apikey -> Create API key.

### 3. Optional: Pollinations key (makes images faster)
Sign up at https://enter.pollinations.ai and create a key. Without it the bot still works but waits ~16 s between images.

### 4. GitHub Secrets
Repo -> Settings -> Secrets and variables -> Actions -> New repository secret:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from step 2 |
| `BUFFER_API_KEY` | from step 1 |
| `POLLINATIONS_API_KEY` | from step 3 (optional) |

### 5. Choose your post time
Edit `config.json`: `"post_time_utc": "13:00"` is the daily time in **UTC**. The bot builds each film hours early (04:00 UTC) and Buffer posts it at your time.
`channels` says which version each platform gets: `"en"` (English subtitles) or `"zh"` (Chinese subtitles).

### 6. Test without posting
Actions tab -> **Daily Short Film** -> Run workflow (leave **dry_run ticked**). When it finishes, open the run and download the **test-film** file at the bottom. Nothing is posted.

### 7. Go live
Run the workflow again with **dry_run unticked**. From then on it runs every day by itself.

## Good to know
- **Use a public repository.** Videos are hosted as GitHub Release files, and Buffer needs a public link. Your keys stay private in Secrets.
- **Buffer free plan:** 10 queued posts per channel and 3,000 API requests per 30 days. One film a day fits.
- **Music:** Kevin MacLeod (CC BY 4.0). The bot adds the required credit line to the post text. Your own MP3s placed in a `music/` folder are used instead.
- **AI disclosure:** posts are flagged as AI-generated on YouTube and TikTok.
- **Fact-check:** Gemini double-checks the script, but it is not perfect. Review early posts, and avoid news topics you would not want to be wrong about.
- **Free tiers change.** If a step fails, the log in the Actions tab says which one.

## Film mode notes
- Episode 1 goes out first. Dry runs never move the story forward; only a real post does.
- Characters are photoreal AI stills with camera moves, not moving video actors. Faces stay *similar* across shots, not identical: that is the limit of free image tools.
- To change a character, edit their `look` in `story/bible.json`, then run `python tools/make_film_bible.py` to refresh `FILM_BIBLE.md`.
- When all 40 episodes are posted the bot stops by itself.
