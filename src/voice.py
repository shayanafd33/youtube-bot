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
