"""Builds FILM_BIBLE.md (the full production package) from story/bible.json.
Run:  python tools/make_film_bible.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B = json.loads((ROOT / "story" / "bible.json").read_text(encoding="utf-8"))
C, INF, ST = B["characters"], B["infected"], B["style"]
out = []


def h(t, lvl=2):
    out.append(f"\n{'#' * lvl} {t}\n")


def p(t):
    out.append(t + "\n")


def look(cid):
    e = C.get(cid) or INF.get(cid)
    return e.get("look", "") if e else ""


out.append(f"# {B['title']}: Film Bible and Production Package\n")
p("Generated from `story/bible.json`. The daily bot reads the same file, so what you read here is exactly what gets filmed.")

h("1. Film title"); p(B["title"])
h("2. Logline"); p(B["logline"])
h("3. Genre"); p(B["genre"])
h("4. Runtime"); p(B["runtime_plan"])

h("5. Main characters")
for cid in ["MARCUS", "PRIYA", "ROURKE", "TOBY", "GAZ", "FATIMA", "LINNEA", "JAMIE", "PEGGY", "OLLIE", "NAOMI", "HARGREAVES", "RHEA", "IMRAN"]:
    c = C[cid]
    p(f"**{c['name']}** ({c.get('role', '')}, age {c.get('age', '?')}). {c.get('personality', '')} "
      f"{('Background: ' + c['background']) if c.get('background') else ''} "
      f"{('Arc: ' + c['arc']) if c.get('arc') else ''}")

h("6. Villain")
r = C["ROURKE"]
p(f"**{r['name']}.** {r['personality']} {r['background']} Goal: {r['goal']} Weakness: {r['weakness']} Arc: {r['arc']}")
p("Why the audience understands him: he lost his son to the exact suffering he wants to erase, and everything he does is, to him, an act of mercy.")

h("7. Infected / zombie types")
for e in INF.values():
    p(f"**{e['name']}**: {e['look']}. {e['behaviour']}")
p("**The Sentinel (Alpha)**: Toby Wren. Keeps fragments of memory, his four-note hum draws Hollows, and he answers to Marcus's voice and the unit call-sign. Weakness: his own remaining humanity.")

h("8. Character consistency table (locked)")
for cid, c in C.items():
    if not c.get("look"):
        continue
    p(f"**{c['name']}**  \nLOCKED LOOK: {c['look']}  \n"
      f"VOICE: Kokoro `{c['voice']}` at speed {c.get('speed', 1.0)}; {c.get('speaking_style', '')}  \n"
      f"OBJECTS: {c.get('carries', 'none')}  \nSEED: {c.get('seed')}  \nPERSONALITY: {c.get('personality', '')}")

h("9. World-building bible")
for k, v in B["world"].items():
    p(f"- **{k.replace('_', ' ').title()}:** {v}")

h("10. Infection rules (never broken)")
for k, v in B["infection"].items():
    p(f"- **{k.replace('_', ' ').title()}:** {v}")

h("11. Complete story")
for a, name in [(1, "THE BEGINNING"), (2, "THE SURVIVAL"), (3, "THE ESCALATION"), (4, "THE FINAL CONFRONTATION"), (5, "THE ENDING")]:
    p(f"**ACT {a}: {name}**")
    for s in B["scenes"]:
        if s["act"] == a:
            p(f"- Ep {s['n']} *{s['title']}*: {s['beat']}")

h("12. Act structure")
p("- Act 1 (episodes 1-8): Day 1, the outbreak at the hospital and the garage; ends with Rhea's last broadcast.\n"
  "- Act 2 (9-18): the journey across the moor; the group forms; ends with Rourke recognising Priya at Haven.\n"
  "- Act 3 (19-28): Haven's secrets, betrayals and Gaz's sacrifice.\n"
  "- Act 4 (29-36): the return, the serum, the control room, Toby's last act and the broadcast.\n"
  "- Act 5 (37-40): consequences, mercy, goodbye, hope.")

h("13. Scene-by-scene breakdown")
for s in B["scenes"]:
    a = ST["acts"][str(s["act"])]
    h(f"Episode {s['n']}: {s['title']}", 3)
    p(f"- **Location:** {s['loc']}\n- **Time:** {s['time']}\n- **Weather:** {s['weather']}\n"
      f"- **Characters:** {', '.join(s['cast'])}\n- **What happens:** {s['beat']}\n- **Emotion:** {s['emotion']}\n"
      f"- **Camera / shot style:** {a['camera']}\n- **Lighting:** {a['lighting']}\n- **Sound:** {a['sound']}\n"
      f"- **Music:** {a['music']}\n- **Continuity notes:** {s['notes']}\n"
      f"- **Connects to next:** {B['scenes'][s['n']]['title'] if s['n'] < len(B['scenes']) else 'End of film'}")

h("14. Major dialogue")
p("Dialogue is written fresh for each episode by the bot within the beat above, using each character's speaking style:")
for cid in ["MARCUS", "PRIYA", "ROURKE", "GAZ", "FATIMA", "LINNEA", "JAMIE", "PEGGY", "OLLIE"]:
    p(f"- **{C[cid]['name']}:** {C[cid]['speaking_style']}")

h("15. Major twists")
for t in B["twists"]:
    p(f"- **{t['twist']}** Clues: {t['clues']} Payoff: {t['payoff']}")

h("16. Character arcs")
for cid in ["MARCUS", "PRIYA", "ROURKE", "TOBY", "GAZ", "FATIMA", "LINNEA", "JAMIE", "PEGGY", "OLLIE", "NAOMI", "HARGREAVES"]:
    p(f"- **{C[cid]['name']}:** {C[cid]['arc']}")

h("17. Deaths and consequences")
for d in B["deaths"]:
    p(f"- **{d['who']}** (episode {d['scene']}): {d['meaning']}")

h("18. Ending"); p(B["ending"])

h("19. Visual style guide"); p(ST["visual"]); p(f"Image prefix used on every shot: {ST['image_prefix']}")
h("20. Camera style guide"); p(ST["camera"])
h("21. Lighting guide"); p(ST["lighting"])
h("22. Sound and music guide"); p(f"Sound: {ST['sound']}\n\nMusic: {ST['music']}")

h("23. AI image prompts (one per episode, opening shot template)")
for s in B["scenes"]:
    chars = [c for c in s["cast"][:2]]
    looks = " ".join(look(c) + "." for c in chars if look(c))
    p(f"**Episode {s['n']}:** {ST['image_prefix']} {looks} Setting: {s['loc']}, {s['time']}, {s['weather']}. Emotion: {s['emotion']}. {ST['image_suffix']}")

h("24. AI video prompts (for use with any image-to-video tool)")
for s in B["scenes"]:
    a = ST["acts"][str(s["act"])]
    p(f"**Episode {s['n']}:** 5-second cinematic shot, {a['camera']}, {a['lighting']}, {s['weather']}. "
      f"{s['beat'].split('.')[0]}. Cast must match the locked looks. Keep the same faces, costumes, injuries and props as the previous episode.")

h("25. Continuity tracker")
p("The bot keeps a live tracker in `state/state.json` (status, visible injuries and costume changes, objects carried, knowledge) and feeds it into every episode. Key fixed continuity points:")
for s in B["scenes"]:
    if s["notes"]:
        p(f"- Ep {s['n']}: {s['notes']}")

h("26. Master prompt for keeping the entire film visually consistent")
p("Use this block at the start of any image or video prompt, then add the scene-specific action:")
p(f"> {ST['image_prefix']} {ST['image_suffix']} Always repeat the full LOCKED LOOK of every person in frame exactly as written in section 8, "
  f"in the same order, never change age, face, hair, clothing, body type, or objects unless the continuity tracker says they changed. "
  f"Palette and mood: {ST['visual']}")

(ROOT / "FILM_BIBLE.md").write_text("\n".join(out), encoding="utf-8")
print("FILM_BIBLE.md written,", len("\n".join(out).split()), "words")
