"""Finds B-roll: YouTube search, download, picking clean matching moments, shot timing."""
import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np

from . import ff, vision
from .config import ASSETS

FULL_MAX = 720               # videos up to 12 minutes are downloaded whole
CW, CH = 1216, 1080          # 9:8 crop taken from footage scaled to cover this box
STOP = set("""a an the of and or in on at to for with from his her their vs then no
footage shots shot close ups closeup clip clips official moments moment style video
real best men only people showing if clean prep""".split())


# ---------------------------------------------------------------- search / download
def search(query, cfg):
    """YouTube results for a B-roll line, best candidates first. If the full wording finds
    nothing, shorter versions of it are tried ("Hokit vs Blades bloody exchanges" ->
    "Hokit vs Blades")."""
    n = int(cfg["broll_search_results"])
    bad = [c.lower() for c in cfg["rejected_channels"]]
    weak = cfg.get("rejected_title_words", [])
    ws = query.split()
    tries = [query] + [" ".join(ws[:k]) for k in range(len(ws) - 1, 2, -1)]
    for q in tries:
        try:
            r = ff.run([sys.executable, "-m", "yt_dlp", "--no-warnings", "--flat-playlist", "-J",
                        "--socket-timeout", "30", f"ytsearch{n}:{q}"], check=False, timeout=120)
            entries = json.loads(r.stdout).get("entries") or []
        except Exception:
            entries = []
        out = []
        for e in entries:
            if not e or not e.get("id"):
                continue
            ch = (e.get("channel") or e.get("uploader") or "")
            dur = e.get("duration") or 0
            if any(b in ch.lower() for b in bad) or dur and dur < 6:
                continue
            title = e.get("title") or ""
            out.append({"vid": e["id"], "title": title, "channel": ch, "duration": dur,
                        "weak": any(w in title.lower() for w in weak)})
        if out:
            # talking-head style titles (reaction, podcast...) last; then short videos first,
            # because they download whole and fast
            out.sort(key=lambda v: (v["weak"], not (0 < v["duration"] <= FULL_MAX)))
            return out
    return []


def download(vid, cfg, duration=0, full=False):
    """Video-only download, cached by id. Short videos (or full=True) are fetched whole, which
    is fast; for long ones only the first few minutes are fetched, which is slow."""
    cache = os.path.join(cfg["work_dir"], "_broll_cache")
    os.makedirs(cache, exist_ok=True)
    out = os.path.join(cache, vid + ".mp4")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        return out
    from .source import hms, ytdlp
    args = ["-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]/b",
            "--concurrent-fragments", "4", "--merge-output-format", "mp4",
            "-o", os.path.join(cache, vid + ".%(ext)s")]
    if not full and not (0 < duration <= FULL_MAX):
        args += ["--download-sections", f"*0:00:00-{hms(cfg['broll_max_seconds'])}"]
    ytdlp(args + [f"https://www.youtube.com/watch?v={vid}"], timeout=900)
    if not os.path.exists(out):
        raise RuntimeError(f"could not download {vid}")
    return out


# ---------------------------------------------------------------- frames
def cover(frame):
    """Scales a frame so it covers the 1216x1080 crop box."""
    h, w = frame.shape[:2]
    s = max(CW / w, CH / h)
    if abs(s - 1) > 1e-3:
        frame = cv2.resize(frame, (max(CW, round(w * s)), max(CH, round(h * s))),
                           interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LANCZOS4)
    return frame


def crop98(frame, fx=0.5):
    f = cover(frame)
    h, w = f.shape[:2]
    x = int(round((w - CW) * min(max(fx, 0), 1)))
    y = (h - CH) // 2
    return f[y:y + CH, x:x + CW]


def frame_at(path, t):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None


def thumb(path, t, fx, out):
    fr = frame_at(path, t)
    if fr is None:
        return False
    cv2.imwrite(out, cv2.resize(crop98(fr, fx), (304, 270), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 82])
    return True


_det = None


def face_fx(frame):
    """Crop position (0..1) that centres the biggest face, or None."""
    global _det
    if _det is None:
        _det = cv2.FaceDetectorYN.create(os.path.join(ASSETS, "models", "yunet.onnx"), "", (640, 360))
    f = cover(frame)
    h, w = f.shape[:2]
    s = 640.0 / w
    sm = cv2.resize(f, (640, int(h * s)))
    _det.setInputSize((sm.shape[1], sm.shape[0]))
    _, faces = _det.detect(sm)
    if faces is None:
        return None
    faces = [r for r in faces if r[14] > 0.75]
    if not faces or w <= CW:
        return None
    r = max(faces, key=lambda r: r[2] * r[3])
    cx = (r[0] + r[2] / 2) / s
    return float(min(max((cx - CW / 2) / (w - CW), 0), 1))


def embeddings(path, log=None):
    """One CLIP vector per second of video (cached next to the file).

    Frames come from a single ffmpeg pass. (Seeking to each second with OpenCV took about
    a second per frame on Windows, i.e. many minutes per video.)"""
    npz = path + ".clip.npz"
    if os.path.exists(npz):
        d = np.load(npz)
        return d["t"], d["e"]
    w, h = 384, 216
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-an",
         "-vf", f"fps=1,scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    size, frames, embs, n = w * h * 3, [], [], 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        frames.append(np.frombuffer(buf, np.uint8).reshape(h, w, 3))
        n += 1
        if len(frames) == 32:
            embs.append(vision.embed_images(frames))
            frames = []
        if log and n % 120 == 0:
            log(f"      scanned {n // 60} min of the video")
    proc.stdout.close()
    proc.wait()
    if frames:
        embs.append(vision.embed_images(frames))
    e = np.concatenate(embs) if embs else np.zeros((0, 512), np.float32)
    t_arr = np.arange(len(e), dtype=float)
    np.savez(npz, t=t_arr, e=e)
    return t_arr, e


def best_windows(path, text, k=3, span=3, log=None):
    """Top moments (>= `span` s inside one scene) that look most like `text`."""
    ts, e = embeddings(path, log)
    if len(ts) < span:
        return []
    tv = vision.embed_texts([f"a photo of {text}"])[0]
    sim = e @ tv
    same = np.concatenate([[True], (e[1:] * e[:-1]).sum(axis=1) > 0.80])   # no cut before frame i
    wins = []
    for i in range(len(ts) - span + 1):
        if same[i + 1:i + span].all():
            wins.append((float(sim[i:i + span].mean()), i))
    wins.sort(reverse=True)
    out = []
    for score, i in wins:
        if all(abs(ts[i] - ts[j]) >= 6 for _, j in out):
            out.append((score, i))
        if len(out) >= k:
            break
    return [{"t": max(0.0, float(ts[i]) - 0.3), "score": score, "emb": e[i + span // 2]} for score, i in out]


_people = None


def people_flags(emb):
    """Rough zero-shot guess whether a woman is in frame. Not reliable; a warning only."""
    global _people
    if _people is None:
        _people = vision.embed_texts(["a photo of a woman", "a photo of a man or men",
                                      "a photo of an object, animal or place with no people"])
    logits = 100 * (_people @ emb)
    p = np.exp(logits - logits.max())
    p /= p.sum()
    return float(p[0])


# ---------------------------------------------------------------- candidates
def candidates(item, cfg, thumb_dir, tag, log=print):
    """Proposes up to 4 moments for one B-roll line. Each: vid, path, t, fx, score, flags."""
    out = []
    ai = vision.available()
    text = (item["match"] + " " + item.get("hint", "")).strip()
    if item.get("fixed"):
        fx = item["fixed"]
        vids = [{"vid": fx["vid"], "title": "from the slate", "channel": "", "fixed_t": fx["t"]}]
    else:
        log("    searching YouTube")
        vids = search(item["search"], cfg)
        if not vids:
            log(f"  no search results for: {item['search']}")
    got = 0
    for v in vids:
        if got >= int(cfg["broll_downloads"]):
            break
        try:
            mins = f" ({int(v['duration']) // 60}:{int(v['duration']) % 60:02d})" if v.get("duration") else ""
            log(f"    downloading: {v['title'][:60]}{mins}")
            path = download(v["vid"], cfg, v.get("duration") or 0, full="fixed_t" in v)
        except Exception as ex:
            log(f"  skip {v['vid']}: {str(ex).splitlines()[-1][:120]}")
            continue
        got += 1
        if "fixed_t" in v:
            wins = [{"t": v["fixed_t"], "score": 1.0}]
        elif ai:
            log("    picking the best moments")
            wins = best_windows(path, text, log=log)
        else:
            d = ff.duration(path)
            wins = [{"t": d * f, "score": 0.0} for f in (0.2, 0.45, 0.7)]
        for w in wins:
            fr = frame_at(path, w["t"] + 1.0)
            if fr is None:
                continue
            flags = []
            fx = face_fx(fr)
            score = w["score"]
            if ai and "emb" in w and "fixed_t" not in v:
                if people_flags(w["emb"]) > 0.45:
                    flags.append("woman?")
                    score -= 0.06
                tf = vision.text_fraction(crop98(fr, fx if fx is not None else 0.5))
                if tf is not None and tf > 0.012:
                    flags.append("text")
                    score -= 0.03
            elif not ai:
                flags.append("not scored")
            out.append({"vid": v["vid"], "path": path, "title": v["title"][:70],
                        "channel": v["channel"], "t": round(w["t"], 2),
                        "fx": round(fx if fx is not None else 0.5, 3),
                        "score": round(score, 4), "flags": flags})
    out.sort(key=lambda c: -c["score"])
    out = out[:4]
    for i, c in enumerate(out):
        c["thumb"] = f"{tag}_{i}.jpg"
        thumb(c["path"], c["t"] + 1.0, c["fx"], os.path.join(thumb_dir, c["thumb"]))
    return out


# ---------------------------------------------------------------- matching shots to speech
def _key(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def keywords(item):
    ws = [_key(w) for w in re.split(r"[\s/\-]+", item["match"] + " " + item.get("hint", ""))]
    return [w for w in ws if len(w) >= 3 and w not in STOP]


def same_word(a, b):
    if a == b:
        return True
    cp = 0
    for x, y in zip(a, b):
        if x != y:
            break
        cp += 1
    return cp >= 4 and cp >= 0.75 * min(len(a), len(b))


def spoken_times(item, tokens):
    """Times at which the clip's audio says one of the B-roll line's subject words."""
    kws = keywords(item)
    hits = []
    for w, s, _e in tokens:
        for part in w.split():
            k = _key(part)
            if k and any(same_word(k, kw) for kw in kws):
                if not hits or s - hits[-1][0] > 4:
                    hits.append((s, k))
                break
    return hits[:2]


def build_timeline(items, tokens, dur, shot_len=2.6):
    """Bottom-half shot list. A shot starts when its subject is spoken; gaps get the rest."""
    anchors = []
    for idx, it in enumerate(items):
        for t, word in spoken_times(it, tokens):
            anchors.append((max(0.0, t - 0.15), idx, word))
    anchors.sort()
    kept = []
    for a in anchors:
        if a[0] < dur - 0.8 and (not kept or a[0] - kept[-1][0] >= 1.2):
            kept.append(a)
    anchored_items = {a[1] for a in kept}
    fillers = [i for i in range(len(items)) if i not in anchored_items] or list(range(len(items)))
    starts = [t[1] for t in tokens]
    state = {"f": 0}
    slots = []

    def snap(t):
        near = [s for s in starts if abs(s - t) <= 0.3]
        return min(near, key=lambda s: abs(s - t)) if near else t

    def fill(a, b):
        if b - a < 0.9:
            if slots:
                slots[-1]["end"] = b
                return a
            return None            # caller pulls the next shot's start back to `a`
        n = max(1, round((b - a) / shot_len))
        cuts = [a] + [snap(a + (b - a) * k / n) for k in range(1, n)] + [b]
        for x, y in zip(cuts[:-1], cuts[1:]):
            if y - x < 0.5:
                slots[-1]["end"] = y
                continue
            slots.append({"start": x, "end": y, "item": fillers[state["f"] % len(fillers)],
                          "word": ""})
            state["f"] += 1
        return b

    cursor = 0.0
    for n, (t, idx, word) in enumerate(kept):
        if t > cursor and fill(cursor, t) is None:
            t = cursor
        nxt = kept[n + 1][0] if n + 1 < len(kept) else dur
        end = min(nxt, t + 3.2, dur)
        if dur - end < 0.9:
            end = dur
        slots.append({"start": t, "end": end, "item": idx, "word": word})
        cursor = end
    if cursor < dur and items:
        if fill(cursor, dur) is None and not slots:
            slots.append({"start": 0.0, "end": dur, "item": 0, "word": ""})
    if slots:
        slots[-1]["end"] = dur
    uses = {}
    for s in slots:
        s["start"], s["end"] = round(s["start"], 3), round(s["end"], 3)
        s["use"] = uses.get(s["item"], 0)
        uses[s["item"]] = s["use"] + 1
    return slots
