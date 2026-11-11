"""Speech-to-text with word times, and fuzzy phrase lookup in the result."""
import re
import subprocess
from difflib import SequenceMatcher

import numpy as np

_model = None


def transcribe(path, cfg, start=None, dur=None):
    """Returns [[word, start, end], ...] in the file's own time.
    With start/dur only that stretch is transcribed (times are then relative to `start`)."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        dev = cfg.get("whisper_device", "cpu")
        _model = WhisperModel(cfg.get("whisper_model", "small.en"), device=dev,
                              compute_type="int8" if dev == "cpu" else "float16")
    # Decode with ffmpeg ourselves and hand whisper the samples. (Passing a file makes
    # faster-whisper open it with PyAV, which breaks on some PyAV versions.)
    part = ([] if start is None else ["-ss", f"{max(0, start):.3f}"]) + \
           ([] if dur is None else ["-t", f"{dur:.3f}"])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin"] + part + ["-i", path, "-vn",
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if len(audio) < 1600:
        return []
    segs, _ = _model.transcribe(audio, word_timestamps=True, language="en", beam_size=1,
                                condition_on_previous_text=False)
    out = [[w.word.strip(), round(w.start, 2), round(w.end, 2)]
           for s in segs for w in (s.words or [])]
    return [w for w in out if re.search(r"\w", w[0])]


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def find_phrase(words, phrase, t_expect=None):
    """Best match of `phrase` in words. Returns (score 0..1, (first_idx, last_idx_exclusive))."""
    p = [norm(x) for x in phrase.split()]
    p = [x for x in p if x]
    if not p or not words:
        return 0.0, None
    target = " ".join(p)
    W = [norm(w[0]) for w in words]
    best = (0.0, None)
    for i in range(len(W)):
        for m in (len(p) - 1, len(p), len(p) + 1, len(p) + 2):
            if m < 1 or i + m > len(W):
                continue
            r = SequenceMatcher(None, target, " ".join(W[i:i + m])).ratio()
            if t_expect is not None:
                r -= min(abs(words[i][1] - t_expect), 30) * 0.004
            if r > best[0]:
                best = (r, (i, i + m))
    return best
