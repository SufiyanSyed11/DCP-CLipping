"""Finds the exact clip in the transcript, cuts it in true silence, removes pauses."""
import json
import math

import numpy as np

from . import ff, words as W

FPS = ff.FPS


def auto_keep(words, clip, win_start):
    """Marks which words belong to the clip. Times in the slate are episode times."""
    keep = [False] * len(words)
    segs = [[a - win_start, b - win_start] for a, b in clip["segments"]]
    info = {"start_match": 0.0, "end_match": 0.0}
    if not segs or not words:
        return keep, info
    ranges = []
    for a, b in segs:
        i = next((k for k, w in enumerate(words) if w[1] >= a - 0.3), len(words))
        j = next((k for k, w in enumerate(words) if w[2] > b + 0.3), len(words))
        ranges.append([i, j])
    if clip.get("start_phrase"):
        first = " ".join(clip["start_phrase"].split()[:7])
        score, hit = W.find_phrase(words, first, segs[0][0])
        info["start_match"] = round(score, 2)
        if hit and score >= 0.6:
            ranges[0][0] = hit[0]
    if clip.get("payoff"):
        last = " ".join(clip["payoff"].split()[-7:])
        score, hit = W.find_phrase(words, last, segs[-1][1] - 2)
        info["end_match"] = round(score, 2)
        if hit and score >= 0.6 and abs(words[hit[1] - 1][2] - segs[-1][1]) < 8:
            ranges[-1][1] = hit[1]
    for i, j in ranges:
        for k in range(max(0, i), min(len(words), j)):
            keep[k] = True
    return keep, info


def _smooth(x, n=3):
    return np.convolve(x, np.ones(n) / n, mode="same")


def silence_threshold(rms):
    floor = float(np.percentile(rms, 10))
    return max(120.0, min(floor * 2.5, 450.0))


def snap_start(rms, thr, t_word, t_prev_end):
    """Cut point just before a word: the latest quiet 10 ms step ahead of it."""
    lo = max(t_prev_end - 0.05, t_word - 0.40, 0)
    a, b = int(lo * 100), min(len(rms) - 1, int((t_word + 0.03) * 100))
    if b <= a:
        return max(0.0, t_word - 0.05)
    s = _smooth(rms[a:b + 1])
    quiet = np.where(s < thr)[0]
    k = quiet[-1] if len(quiet) else int(np.argmin(s))
    return max(0.0, (a + k) / 100 - 0.03)


def snap_end(rms, thr, t_word_end, t_next):
    """Cut point after the last word: first quiet stretch once the word has finished."""
    hi = min(t_next + 0.08, t_word_end + 0.7)
    a, b = max(0, int((t_word_end - 0.06) * 100)), min(len(rms) - 1, int(hi * 100))
    if b <= a:
        return t_word_end + 0.1
    s = _smooth(rms[a:b + 1])
    for k in range(len(s) - 4):
        if (s[k:k + 5] < thr).all():
            return (a + k) / 100 + 0.05
    return (a + int(np.argmin(s))) / 100 + 0.02


def segments(words, keep, rms, adj=None):
    """Kept word runs -> [(start, end)] in file time, snapped to silence."""
    adj = adj or {}
    thr = silence_threshold(rms)
    runs, i = [], 0
    while i < len(words):
        if keep[i]:
            j = i
            while j + 1 < len(words) and keep[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    out = []
    for n, (i, j) in enumerate(runs):
        prev_end = words[i - 1][2] if i > 0 else 0.0
        nxt = words[j + 1][1] if j + 1 < len(words) else words[j][2] + 0.7
        a = snap_start(rms, thr, words[i][1], prev_end)
        b = snap_end(rms, thr, words[j][2], nxt)
        if n == 0:
            a += float(adj.get("start", 0))
        if n == len(runs) - 1:
            b += float(adj.get("end", 0))
        if b - a > 0.2:
            out.append((max(0.0, a), b))
    return out


def build_p0(src, segs, out):
    """Joins the segments (time-based, any source frame rate) into a 29.97 fps file."""
    snap = lambda t: round(t * FPS) / FPS
    args, fc, labs = [], [], ""
    for i, (a, b) in enumerate(segs):
        a, b = snap(a), snap(b)
        pre = min(2.0, a)
        d = b - a
        n = round(d * FPS)
        args += ["-ss", f"{a - pre:.6f}", "-i", src]
        fc.append(f"[{i}:v]trim=start={pre:.6f}:end={pre + d + 0.2:.6f},setpts=PTS-STARTPTS,"
                  f"fps={ff.FPSS},trim=end_frame={n},setpts=PTS-STARTPTS[v{i}]")
        fc.append(f"[{i}:a]atrim=start={pre:.6f}:end={pre + n / FPS:.6f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.005,afade=t=out:st={n / FPS - 0.008:.6f}:d=0.008[a{i}]")
        labs += f"[v{i}][a{i}]"
    fc.append(f"{labs}concat=n={len(segs)}:v=1:a=1[v][a]")
    ff.ffmpeg(args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                      "-r", ff.FPSS, "-c:v", "libx264", "-preset", "faster", "-crf", "16",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])


def remove_pauses(p0, out, thr=150, mind=0.22, marg=0.08):
    """Drops silent stretches (never speech). Returns seconds removed."""
    rms = ff.rms_trace(p0)
    k = len(rms)
    nf = ff.frame_count(p0)
    sil = rms < thr
    cuts, i = [], 0
    while i < k:
        if sil[i]:
            j = i
            while j < k and sil[j]:
                j += 1
            s, e = i * 0.01, j * 0.01
            i = j
            if e - s < mind or e > k * 0.01 - 0.02:
                continue          # short pause, or the tail after the last word
            a = math.ceil((s + marg) * FPS)
            b = math.floor((e - marg) * FPS)
            if s < 0.02:
                a = 0
            if b - a >= 2:
                cuts.append((a, b))
        else:
            i += 1
    keep, p = [], 0
    for a, b in cuts:
        if a > p:
            keep.append((p, a))
        p = b
    if p < nf:
        keep.append((p, nf))
    fc, lab = [], ""
    for q, (a, b) in enumerate(keep):
        fc.append(f"[0:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS[v{q}]")
        fc.append(f"[0:a]atrim=start={a / FPS:.6f}:end={b / FPS:.6f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.004,afade=t=out:st={(b - a) / FPS - 0.006:.6f}:d=0.006[a{q}]")
        lab += f"[v{q}][a{q}]"
    fc.append(f"{lab}concat=n={len(keep)}:v=1:a=1[v][a]")
    ff.ffmpeg(["-i", p0, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
               "-r", ff.FPSS, "-c:v", "libx264", "-preset", "faster", "-crf", "16",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])
    with open(out + ".keep.json", "w") as f:
        json.dump({"keep": keep}, f)
    return sum(b - a for a, b in cuts) / FPS
