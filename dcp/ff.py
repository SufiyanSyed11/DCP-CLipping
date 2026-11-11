"""Thin wrappers around ffmpeg / ffprobe."""
import re
import subprocess

import numpy as np

FPS = 30000 / 1001
FPSS = "30000/1001"

_log = print


def set_logger(fn):
    global _log
    _log = fn


def log(*a):
    _log(" ".join(str(x) for x in a))


def run(args, cwd=None, check=True, timeout=None):
    try:
        r = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{args[0]} took longer than {timeout}s and was stopped")
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-1500:]
        raise RuntimeError(f"{args[0]} failed:\n{tail}")
    return r


def ffmpeg(args, cwd=None):
    return run(["ffmpeg", "-y", "-v", "error", "-nostdin"] + list(args), cwd=cwd)


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path])
    return float(r.stdout.strip())


def frame_count(path):
    r = run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path])
    return int(r.stdout.strip().split(",")[0])


def rms_trace(path, start=None, dur=None):
    """RMS of the audio in 10 ms steps (16 kHz mono, int16 scale)."""
    args = ["ffmpeg", "-v", "error", "-nostdin"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    raw = subprocess.run(args, capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float64)
    n = 160
    k = len(x) // n
    if k == 0:
        return np.zeros(1)
    return np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(axis=1))


def mean_volume(args):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin"] + list(args) +
            ["-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume: (-?[\d.]+)", r.stderr)
    return float(m.group(1)) if m else -20.0


def loudness(path):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", path,
             "-af", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(m[-1]) if m else None


_nvenc = None


def video_codec(cfg, quality=20):
    """Encoder arguments; uses the NVIDIA encoder when it really works."""
    global _nvenc
    want = cfg.get("encoder", "auto")
    if want == "libx264":
        _nvenc = False
    elif _nvenc is None:
        t = run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                 "color=black:s=256x256:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
                check=False)
        _nvenc = t.returncode == 0
    if _nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(quality + 1),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(quality), "-pix_fmt", "yuv420p"]
