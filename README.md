# Multi-platform content engine (TikTok + YouTube Shorts + Facebook Reels + Bilibili)

One film is generated per day. From it the engine renders a version for each platform and every platform
publishes **independently** through an official API. If one fails, the others still go out.

```
trends -> script (fact-checked) -> voice -> images -> music
                         |
                  ONE clean master
        +----------+-----------+------------+
     tiktok     youtube     facebook      bilibili
     9:16       9:16        9:16 (<=90s)  16:9 blurred frame
     hook+subs  Shorts copy Reels copy    English + Chinese subs, Chinese copy, cover
        |           |           |             |
   platforms/   platforms/  platforms/    platforms/
   tiktok.py    youtube.py  facebook.py   bilibili.py   <- independent modules
```

Everything is free / open source: GitHub Actions, Kokoro voice, Pollinations images, Buffer free plan,
Gemini free tier, FFmpeg. Nothing paid is added. (Optional paid upgrades, off by default: fal.ai video, ElevenLabs.)

## Rolling queue (what makes it hands-free)
Buffer's free plan holds 10 queued posts per channel, so a 30-day queue is impossible without paying. Instead the
engine keeps the **next 9 days** scheduled on every platform and tops the queue up once a day (default: build
the missing days, up to 4 films per run). Even if a daily run fails, the queue keeps posting for days and the next run repairs
the gap. First fill: run the workflow once with `films` = 9. Settings: `LOOKAHEAD_DAYS` (max 10), `MAX_FILMS_PER_RUN`.
Videos for later days are written with an evergreen angle because they publish up to 9 days after the trend.

## Upgrading from the TikTok-only version
1. Replace the files in your repo with this project (Add file > Upload files; same names overwrite).
   Delete any leftover `pipeline (3).py`-style copies.
2. Replace `.github/workflows/daily.yml` with the new one (it now saves state even after a partial failure).
3. Do nothing else: with no new settings it behaves exactly like before (TikTok only).

## Turning platforms on
Settings > Secrets and variables > Actions > **Variables**: `PLATFORMS` = `tiktok,youtube,facebook,bilibili`
(any subset). A platform that is enabled but not configured does NOT fail: it produces a ready-to-upload file
in the run's Artifacts instead.

| Platform | Recommended route (free) | Secrets to add |
|---|---|---|
| TikTok | Buffer official API (already working) | `BUFFER_CHANNEL_ID` |
| YouTube Shorts | **Buffer** | `YT_BUFFER_CHANNEL_ID` |
| Facebook Reels | **Buffer** (or direct Graph API) | `FB_BUFFER_CHANNEL_ID` (or `FB_PAGE_ID` + `FB_PAGE_TOKEN`) |
| Bilibili | manual-upload package (no approval needed) | none |

Buffer's free plan allows 3 channels: TikTok + YouTube + Facebook fits exactly. Connect the YouTube channel and
Facebook Page in Buffer, then get each channel ID the same way you did for TikTok (the code in the address bar
when you open that channel's settings), or run `python buffer_channels.py`.

### Default posting times (UK time, GMT/BST automatic)
YouTube 18:00, TikTok 19:30, Facebook 21:00 (staggered on purpose). Change with variables `YT_TIME_UK`,
`POST_TIME_UK`, `FB_TIME_UK`. Bilibili has no schedule field in its open API.

## Official-API facts that shape this design (checked October 2026)
- **YouTube direct (`videos.insert`)**: Google locks videos uploaded by *unaudited* API projects to private.
  Direct mode (`YT_MODE=direct`, secrets `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`, scope
  `youtube.upload`) therefore only goes public after your Google Cloud project passes YouTube's API audit.
  Your OAuth consent screen must be set to **In production**, or the refresh token dies after 7 days.
  That is why Buffer (whose integration is already audited) is the recommended route. Uploads set the
  synthetic-media disclosure flag.
- **Facebook Reels API**: Page only (not personal profiles), 9:16, 3-90 seconds, `pages_manage_posts`.
  Scripts are now written to 160-205 words so Reels stay under 90 s; a longer film is refused for Facebook
  (and reported) rather than cut. Direct mode needs a Meta app and a long-lived Page token.
- **Bilibili Open Platform**: video submission exists (OAuth + HMAC-signed requests) but requires a developer
  application approved by Bilibili. `BILI_PUBLISH=1` plus `BILI_CLIENT_ID`, `BILI_APP_SECRET`,
  `BILI_ACCESS_TOKEN`, `BILI_MID` switches the module to the official API. **It is written from Bilibili's docs and
  has not been tested against a live account.** No unofficial cookie/login tools are used. Until then you get a
  package: video, cover, Chinese title/description/tags and upload instructions (tick Bilibili's AI-content declaration).

## What was tested here (and what was not)
Tested with FFmpeg and simulated APIs: the render of all four versions from one master, the TikTok Buffer request
(byte-identical to the one that works in production), failure isolation, no duplicates on re-run, package output,
Bilibili request signing. **Not** tested against live YouTube, Facebook or Bilibili accounts. Enable one platform
at a time and watch its first run.

## Rules built in
AI-content disclosure on every platform that has a flag (TikTok `isAiGenerated`, YouTube synthetic media,
caption note everywhere); no real people/brands in prompts; original script, voice, images each day; music only
Kevin MacLeod (CC BY 4.0, credit added to every caption) or your own tracks with `music/LICENCES.md`;
each platform's copy is written for that platform and nothing is posted twice.
