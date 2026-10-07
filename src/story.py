"""Story engine for film mode: bible, continuity tracker, locked character prompts, voices."""
import json

from util import ROOT

BIBLE_PATH = ROOT / "story" / "bible.json"


def load_bible():
    return json.loads(BIBLE_PATH.read_text(encoding="utf-8"))


def get_film_state(state, bible):
    """Return the film section of state.json, creating it from the bible on first use."""
    film = state.setdefault("film", {})
    film.setdefault("scene_index", 0)
    film.setdefault("summaries", [])
    chars = film.setdefault("chars", {})
    for cid, start in bible["initial_continuity"].items():
        chars.setdefault(cid, dict(start))
    return film


def entity(bible, cid):
    return bible["characters"].get(cid) or bible["infected"].get(cid)


def is_known(bible, cid):
    return cid in bible["characters"] or cid in bible["infected"]


def locked_look(bible, film, cid):
    """The permanent description of a character, plus any visible changes (injuries, costume) so far."""
    e = entity(bible, cid)
    if not e or not e.get("look"):
        return ""
    look = e["look"]
    visible = film["chars"].get(cid, {}).get("visible", "")
    if visible:
        look += f". Currently visible: {visible}"
    return look


def shot_seed(bible, shot):
    """Same character => same seed, which helps keep faces similar between shots."""
    for cid in shot["characters"]:
        e = entity(bible, cid)
        if e and e.get("seed"):
            return e["seed"]
    return None


def shot_image_prompt(bible, film, scene, shot):
    st = bible["style"]
    chars = [locked_look(bible, film, c) for c in shot["characters"]]
    parts = [
        st["image_prefix"],
        f"{shot['camera']}.",
        *[c + "." for c in chars if c],
        f"{shot['visual']}.",
        f"Setting: {scene['loc']}, {scene['time']}, {scene['weather']}.",
        st["image_suffix"],
    ]
    return " ".join(p.strip() for p in parts if p)


def voice_map(bible, speakers):
    """speaker id -> (kokoro voice, speed). Characters sharing a voice get different speeds."""
    narrator = bible["characters"]["NARRATOR"]
    vm, used = {"NARRATOR": (narrator["voice"], narrator.get("speed", 1.0))}, {}
    used[narrator["voice"]] = narrator.get("speed", 1.0)
    for sp in speakers:
        if sp in vm:
            continue
        c = bible["characters"].get(sp)
        if not c or "voice" not in c:
            vm[sp] = vm["NARRATOR"]
            continue
        voice, speed = c["voice"], c.get("speed", 1.0)
        if voice in used and abs(used[voice] - speed) < 0.06:
            speed = round(speed + (0.08 if speed < 1.0 else -0.08), 2)
        used.setdefault(voice, speed)
        vm[sp] = (voice, speed)
    return vm


def apply_continuity(bible, film, update):
    """Merge Gemini's continuity update into the tracker (only known characters)."""
    for cid, change in (update or {}).items():
        if cid not in film["chars"] or not isinstance(change, dict):
            continue
        for key in ("status", "visible", "carries", "knows"):
            if key in change and isinstance(change[key], str):
                film["chars"][cid][key] = change[key][:300]
