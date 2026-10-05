# YouTube Auto Shorts Bot (free, runs on GitHub Actions)

Every day a GitHub Action writes a script (Gemini), records the voice (edge-tts),
picks stock footage (Pexels), assembles a vertical video with captions (FFmpeg),
and uploads it to YouTube as **private with a scheduled publish time**. YouTube
then publishes it at exactly the time you set in `schedule.json`. Your laptop can be off.

## Setup (do these in order)

### 1. Put the project on GitHub
Create a **public** repository (public repos get unlimited free Action minutes;
your keys stay private in Secrets) and push this folder to it.

### 2. Get free API keys
- **Gemini:** https://aistudio.google.com/apikey -> `GEMINI_API_KEY`
- **Pexels:** https://www.pexels.com/api/ -> `PEXELS_API_KEY`

### 3. Create YouTube API credentials
1. Go to https://console.cloud.google.com and create a project.
2. **APIs & Services -> Library**: enable **YouTube Data API v3**.
3. **OAuth consent screen**: choose External, fill the basics, add your own Google
   account under Test users.
4. **Publish the app** (set status to **In production**). If you leave it in
   "Testing", the token expires every 7 days and the bot silently stops.
   An "unverified app" warning is normal for personal use.
5. **Credentials -> Create credentials -> OAuth client ID -> Desktop app**.
   Download the JSON and save it as `client_secret.json` in the project root.

### 4. Get your refresh token (once, on your laptop)
```
pip install -r requirements.txt
python src/get_refresh_token.py
```
A browser opens. Sign in with the Google account that owns the channel and allow
access (click Advanced -> Continue past the unverified warning). The script prints
three values.

### 5. Add GitHub Secrets
Repo -> Settings -> Secrets and variables -> Actions -> New repository secret:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from step 2 |
| `PEXELS_API_KEY` | from step 2 |
| `YT_CLIENT_ID` | printed in step 4 |
| `YT_CLIENT_SECRET` | printed in step 4 |
| `YT_REFRESH_TOKEN` | printed in step 4 |

### 6. Set your schedule
Edit `schedule.json`. `publish_at` is an ISO time with your UTC offset
(for example `2026-10-07T19:00:00+05:00`) and must be in the future. Leave `topic`
empty to let Gemini choose. Change `style` to match your channel.

### 7. Test
- **Dry run on your laptop** (needs ffmpeg installed; builds the video, no upload):
  set `GEMINI_API_KEY` and `PEXELS_API_KEY`, then `DRY_RUN=1 python src/short.py`
  and check `work/final.mp4`.
- **On GitHub:** Actions tab -> **Short** -> Run workflow.

## Important: the YouTube API audit
Videos uploaded by an **unverified** API project are forced to stay private, so your
scheduled publish will not make them public. Submit Google's free
"YouTube API Services - Audit and Quota Extension" form to lift this. Until it is
approved you can publish the private videos manually in YouTube Studio.

## Notes
- Each run builds and schedules the **next unfinished slot** in `schedule.json`, so
  the bot works ahead of the publish time.
- If scheduled runs ever stop, re-enable the workflow in the Actions tab.
- Change the voice with the `TTS_VOICE` env var, for example `en-GB-RyanNeural`.
- Free-tier limits and model names change over time. If Gemini returns a 404, set
  `GEMINI_MODEL` to a model listed at https://ai.google.dev/gemini-api/docs/models.

## Next phase
Long films (up to 1 hour) get their own `film.yml` workflow, built on the same pieces
with a chapter-by-chapter script loop.
