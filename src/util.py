import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
STATE_FILE = ROOT / "state" / "state.json"


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg["gemini_model"] = os.getenv("GEMINI_MODEL", cfg.get("gemini_model", "gemini-3.5-flash"))
    return cfg


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"used_topics": [], "last_due": ""}


def save_state(state):
    state["used_topics"] = state["used_topics"][-200:]
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(cmd, cwd=None):
    subprocess.run([str(c) for c in cmd], check=True, cwd=cwd)


def probe_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)]
    )
    return float(out)
