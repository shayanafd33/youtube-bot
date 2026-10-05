"""AI images from Pollinations.ai (Flux model). Works without a key, slower; a free key is faster."""
import os
import random
import time
from urllib.parse import quote

import requests

from util import run

W, H = 720, 1280  # generated size; FFmpeg scales up to 1080x1920
STYLE = "cinematic film still, moody natural lighting, shallow depth of field, vertical composition, no text, no watermark. "


def _url(prompt, model, seed, key):
    prompt = quote((STYLE + prompt)[:450])
    if key:
        return (f"https://gen.pollinations.ai/image/{prompt}"
                f"?model={model}&width={W}&height={H}&seed={seed}&key={key}")
    return (f"https://image.pollinations.ai/prompt/{prompt}"
            f"?model={model}&width={W}&height={H}&seed={seed}&nologo=true")


def _fallback(dest):
    """Plain dark gradient-ish frame so the film can still be built."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=0x16213e:s={W}x{H}", "-frames:v", "1", dest])


def fetch_images(scenes, model, workdir):
    key = os.getenv("POLLINATIONS_API_KEY", "").strip()
    pause = 2 if key else 16  # anonymous use is throttled to roughly 1 request / 15 s
    paths = []
    for i, scene in enumerate(scenes):
        dest = str(workdir / f"img{i}.jpg")
        ok = False
        for attempt in range(4):
            seed = random.randint(1, 999999)
            try:
                r = requests.get(_url(scene["image_prompt"], model, seed, key), timeout=180)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") \
                        and len(r.content) > 5000:
                    with open(dest, "wb") as f:
                        f.write(r.content)
                    ok = True
                    break
                print(f"  image {i + 1}: HTTP {r.status_code}, retrying")
            except requests.RequestException as e:
                print(f"  image {i + 1}: {e}, retrying")
            time.sleep(pause * (attempt + 1))
        if not ok:
            print(f"  image {i + 1}: using fallback frame")
            _fallback(dest)
        paths.append(dest)
        print(f"  image {i + 1}/{len(scenes)} ready")
        if i < len(scenes) - 1:
            time.sleep(pause)
    return paths
