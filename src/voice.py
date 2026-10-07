"""British-English narration with Kokoro TTS (open source, runs on CPU)."""
import os

import numpy as np
import soundfile as sf

SAMPLE_RATE = 24000
GAP = 0.35  # seconds of silence after each scene


def _to_numpy(audio):
    if hasattr(audio, "detach"):  # torch tensor
        audio = audio.detach().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def synthesize_scenes(scenes, voice, speed, out_wav):
    """Write one combined WAV and return a list of (speech_seconds, scene_seconds)."""
    fake = bool(os.getenv("TTS_FAKE"))  # test mode: silence instead of speech
    pipeline = None
    if not fake:
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code="b")  # 'b' = British English

    gap = np.zeros(int(SAMPLE_RATE * GAP), dtype=np.float32)
    pieces, timings = [], []
    for i, scene in enumerate(scenes):
        text = scene["narration"].strip()
        if fake:
            speech = np.zeros(int(SAMPLE_RATE * 0.38 * len(text.split())), dtype=np.float32)
        else:
            chunks = [
                _to_numpy(audio)
                for _, _, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")
            ]
            if not chunks:
                raise RuntimeError(f"Kokoro produced no audio for scene {i + 1}")
            speech = np.concatenate(chunks)
        pieces.append(np.concatenate([speech, gap]))
        timings.append((len(speech) / SAMPLE_RATE, (len(speech) + len(gap)) / SAMPLE_RATE))
        print(f"  voice scene {i + 1}/{len(scenes)}: {timings[-1][0]:.1f}s")

    sf.write(str(out_wav), np.concatenate(pieces), SAMPLE_RATE)
    return timings


LINE_GAP = 0.25   # pause between two speakers
SHOT_GAP = 0.30   # pause at the end of a shot
SILENT_SHOT = 2.6  # length of a shot with no dialogue


def _speak(pipeline, text, voice, speed, fake):
    if fake:
        return np.zeros(int(SAMPLE_RATE * 0.38 * len(text.split())), dtype=np.float32)
    chunks = [
        _to_numpy(audio)
        for _, _, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")
    ]
    if not chunks:
        raise RuntimeError(f"Kokoro produced no audio for: {text[:40]}")
    return np.concatenate(chunks)


def synthesize_shots(shots, vmap, out_wav):
    """Multi-voice acting. shots: [{'lines': [{'speaker','text'}]}].
    Returns (shot_seconds, events) where events = [(start, duration, text)] for subtitles."""
    fake = bool(os.getenv("TTS_FAKE"))
    pipeline = None
    if not fake:
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code="b")

    line_gap = np.zeros(int(SAMPLE_RATE * LINE_GAP), dtype=np.float32)
    shot_gap = np.zeros(int(SAMPLE_RATE * SHOT_GAP), dtype=np.float32)
    pieces, shot_secs, events, cursor = [], [], [], 0.0
    for i, shot in enumerate(shots):
        start = cursor
        lines = shot.get("lines") or []
        if not lines:
            pieces.append(np.zeros(int(SAMPLE_RATE * SILENT_SHOT), dtype=np.float32))
            cursor += SILENT_SHOT
        for line in lines:
            voice, speed = vmap.get(line["speaker"], vmap["NARRATOR"])
            audio = _speak(pipeline, line["text"], voice, speed, fake)
            dur = len(audio) / SAMPLE_RATE
            events.append((cursor, dur, line["text"]))
            pieces += [audio, line_gap]
            cursor += dur + LINE_GAP
        if lines:
            pieces.append(shot_gap)
            cursor += SHOT_GAP
        shot_secs.append(cursor - start)
        print(f"  voice shot {i + 1}/{len(shots)}: {shot_secs[-1]:.1f}s")
    sf.write(str(out_wav), np.concatenate(pieces), SAMPLE_RATE)
    return shot_secs, events
