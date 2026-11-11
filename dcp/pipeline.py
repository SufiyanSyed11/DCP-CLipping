"""Project/clip state on disk and the build steps."""
import json
import os
import re
import threading
import time
from difflib import SequenceMatcher

from . import broll, captions, cut, ff, pack as packer, render, slate, source, words

STEPS = ["find", "cut", "broll", "render", "pack"]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "slate"


def pdir(cfg, s):
    return os.path.join(cfg["work_dir"], s)


def cdir(cfg, s, n):
    return os.path.join(pdir(cfg, s), f"clip{int(n):02d}")


_io = threading.RLock()        # the web threads read these files while the worker writes them


def _read(path):
    with _io:
        for attempt in range(20):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)


def _write(path, data):
    tmp = path + ".tmp"
    with _io:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(40):          # Windows refuses the swap while anything has the
            try:                           # file open (antivirus, search indexer): wait and retry
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.1)


def load_project(cfg, s):
    return _read(os.path.join(pdir(cfg, s), "project.json"))


def save_project(cfg, proj):
    _write(os.path.join(pdir(cfg, proj["slug"]), "project.json"), proj)


def load_clip(cfg, s, n):
    return _read(os.path.join(cdir(cfg, s, n), "clip.json"))


def save_clip(cfg, s, clip):
    _write(os.path.join(cdir(cfg, s, clip["n"]), "clip.json"), clip)


def list_projects(cfg):
    out = []
    for s in sorted(os.listdir(cfg["work_dir"])):
        p = os.path.join(cfg["work_dir"], s, "project.json")
        if os.path.exists(p):
            proj = _read(p)
            proj["clips"] = []
            for n in proj["clip_numbers"]:
                c = load_clip(cfg, s, n)
                proj["clips"].append({"n": n, "title": c["title"], "status": c["status"],
                                      "error": c.get("error", "")})
            out.append(proj)
    return out


def create_project(cfg, docx_path):
    sl = slate.parse_docx(docx_path)
    if not sl["clips"]:
        raise RuntimeError("No clips found in that document. Each clip needs a numbered heading "
                           "and Source / Hook box / B-roll lines.")
    s = slug(sl["title"])
    os.makedirs(pdir(cfg, s), exist_ok=True)
    proj = {"slug": s, "title": sl["title"], "episode": sl["episode"], "intro": sl["intro"],
            "show": slate.guest_name(sl["title"]), "local_file": "", "fixes": "",
            "clip_numbers": [c["n"] for c in sl["clips"]]}
    old = os.path.join(pdir(cfg, s), "project.json")
    if os.path.exists(old):                       # re-upload keeps your settings
        prev = _read(old)
        for k in ("local_file", "fixes", "show"):
            proj[k] = prev.get(k) or proj[k]
        proj["episode"] = proj["episode"] or prev.get("episode", "")
    save_project(cfg, proj)
    for c in sl["clips"]:
        os.makedirs(cdir(cfg, s, c["n"]), exist_ok=True)
        if os.path.exists(os.path.join(cdir(cfg, s, c["n"]), "clip.json")):
            continue                              # never overwrite work already done
        c.update({"status": "new", "words": [], "keep": [], "adj": {"start": 0, "end": 0},
                  "tokens": [], "cands": [[] for _ in c["broll"]],
                  "picks": [0 for _ in c["broll"]], "slots": [], "zach_time": "", "qa": {}})
        save_clip(cfg, s, c)
    return proj


# ------------------------------------------------------------------ steps
def step_find(cfg, proj, clip, log):
    d = cdir(cfg, proj["slug"], clip["n"])
    if not clip["segments"]:
        raise RuntimeError("The slate gives no timestamps for this clip.")
    if not proj["episode"] and not proj["local_file"]:
        raise RuntimeError("Set the episode's YouTube ID (or a local episode file) first.")
    a = max(0, min(s[0] for s in clip["segments"]) - 10)
    b = max(s[1] for s in clip["segments"]) + 10
    src = os.path.join(d, "src.mp4")
    if not os.path.exists(src) or clip.get("win") != [a, b]:
        log(f"  downloading episode {source.hms(a)}-{source.hms(b)}")
        source.fetch_window(proj["episode"], a, b, src, proj["local_file"])
        clip["win"] = [a, b]
    log("  transcribing")
    clip["words"] = words.transcribe(src, cfg)
    clip["keep"], clip["match"] = cut.auto_keep(clip["words"], clip, a)
    if not any(clip["keep"]):
        raise RuntimeError("Couldn't find the clip's words in the downloaded window.")
    said = " ".join(w[0] for w, k in zip(clip["words"], clip["keep"]) if k)
    log(f"  found: {said[:90]}...")
    clip["status"] = "found"


def step_cut(cfg, proj, clip, log):
    d = cdir(cfg, proj["slug"], clip["n"])
    src = os.path.join(d, "src.mp4")
    if not os.path.exists(src) or not any(clip["keep"]):
        step_find(cfg, proj, clip, log)
    segs = cut.segments(clip["words"], clip["keep"], ff.rms_trace(src), clip.get("adj"))
    if not segs:
        raise RuntimeError("Nothing selected to cut.")
    log(f"  cutting {len(segs)} part(s): " + ", ".join(f"{a:.2f}-{b:.2f}" for a, b in segs))
    cut.build_p0(src, segs, os.path.join(d, "P0.mp4"))
    removed = cut.remove_pauses(os.path.join(d, "P0.mp4"), os.path.join(d, "P1.mp4"),
                                cfg["pause_threshold"], cfg["pause_min"], cfg["pause_margin"])
    clip["frames"] = ff.frame_count(os.path.join(d, "P1.mp4"))
    clip["dur"] = round(clip["frames"] / ff.FPS, 3)
    log(f"  removed {removed:.2f}s of pauses, clip is {clip['dur']:.1f}s")
    raw = words.transcribe(os.path.join(d, "P1.mp4"), cfg)
    toks = captions.apply_fixes(raw, captions.parse_fixes(proj.get("fixes", "")))
    clip["tokens"] = captions.smooth(toks, clip["dur"])
    retime(cfg, clip)
    clip["status"] = "cut"


def retime(cfg, clip):
    """Lays out the B-roll shots so each lands on the words it illustrates."""
    if clip.get("tokens") and clip.get("dur"):
        clip["slots"] = broll.build_timeline(clip["broll"], clip["tokens"], clip["dur"],
                                             float(cfg["shot_seconds"]))


def step_broll(cfg, proj, clip, log):
    d = cdir(cfg, proj["slug"], clip["n"])
    while len(clip["cands"]) < len(clip["broll"]):
        clip["cands"].append([])
        clip["picks"].append(0)
    for i, item in enumerate(clip["broll"]):
        manual = [c for c in clip["cands"][i] if c.get("manual")]
        log(f"  B-roll {i + 1}/{len(clip['broll'])}: {item['search']}")
        found = broll.candidates(item, cfg, d, f"cand{i}", log)
        for k, c in enumerate(manual):
            c["thumb"] = f"cand{i}_m{k}.jpg"
            broll.thumb(c["path"], c["t"] + 1, c["fx"], os.path.join(d, c["thumb"]))
        clip["cands"][i] = manual + found
        clip["picks"][i] = 0
    if clip["status"] in ("new", "found", "cut"):
        clip["status"] = "broll" if clip.get("tokens") else clip["status"]


def add_manual(cfg, proj, clip, i, ref, t, log):
    """Adds a hand-picked source (YouTube link/id or a file path) as the first choice."""
    d = cdir(cfg, proj["slug"], clip["n"])
    if os.path.exists(ref):
        path, vid = ref, os.path.basename(ref)
    else:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", ref) or \
            re.fullmatch(r"\s*([A-Za-z0-9_-]{11})\s*", ref)
        if not m:
            raise RuntimeError("Give a YouTube link, a video ID or a file path.")
        vid = m.group(1)
        log(f"  downloading {vid}")
        path = broll.download(vid, cfg)
    fr = broll.frame_at(path, t + 1)
    fx = broll.face_fx(fr) if fr is not None else None
    c = {"vid": vid, "path": path, "title": "added by hand", "channel": "", "t": float(t),
         "fx": fx if fx is not None else 0.5, "score": 1.0, "flags": [], "manual": True}
    clip["cands"][i].insert(0, c)
    for k, c in enumerate(clip["cands"][i]):
        c["thumb"] = f"cand{i}_h{k}_{len(clip['cands'][i])}.jpg"
        broll.thumb(c["path"], c["t"] + 1, c["fx"], os.path.join(d, c["thumb"]))
    clip["picks"][i] = 0


def step_render(cfg, proj, clip, log):
    d = cdir(cfg, proj["slug"], clip["n"])
    if not clip.get("tokens") or not os.path.exists(os.path.join(d, "P1.mp4")):
        step_cut(cfg, proj, clip, log)
    if not any(clip["cands"]):
        step_broll(cfg, proj, clip, log)
    if not clip.get("slots"):
        retime(cfg, clip)
    bad = cfg["profanity"]
    captions.write_ass(clip["tokens"], os.path.join(d, "captions.ass"), bad)
    shots = render.resolve_shots(clip["slots"], dict(enumerate(clip["cands"])),
                                 dict(enumerate(clip["picks"])))
    zach = None
    if clip.get("zach_time"):
        zt = slate.seconds(clip["zach_time"])
        zach = os.path.join(d, "zach.mp4")
        if clip.get("zach_done") != clip["zach_time"] or not os.path.exists(zach):
            log("  fetching the Zach cutaway")
            source.fetch_window(proj["episode"], zt - 0.5, zt + 4, zach, proj["local_file"])
            clip["zach_done"] = clip["zach_time"]
    final = render.compose(d, shots, clip["frames"], cfg, clip["hook_text"], clip["emoji"],
                           captions.bleeps(clip["tokens"], bad), zach, log)
    clip["shots"] = shots
    log("  checking the result")
    render.contact_sheet(d)
    heard = " ".join(words.norm(w[0]) for w in words.transcribe(final, cfg))
    want = " ".join(words.norm(w[0]) for w in clip["tokens"]
                    if not captions.is_profane(w[0], bad))
    dur = ff.duration(final)
    clip["qa"] = {"seconds": round(dur, 2), "lufs": ff.loudness(final),
                  "words_intact": round(SequenceMatcher(None, want, heard).ratio(), 3),
                  "bleeps": len(captions.bleeps(clip["tokens"], bad)),
                  "under_30s": dur <= 30.0}
    log(f"  done: {clip['qa']}")
    clip["status"] = "rendered"


def step_pack(cfg, proj, clip, log):
    d = cdir(cfg, proj["slug"], clip["n"])
    if not os.path.exists(os.path.join(d, "final.mp4")):
        step_render(cfg, proj, clip, log)
    clip["pack"] = packer.pack(clip, d, proj["show"], cfg)
    log("  packed to " + clip["pack"])
    clip["status"] = "packed"


RUN = {"find": step_find, "cut": step_cut, "broll": step_broll, "render": step_render,
       "pack": step_pack}


def run_steps(cfg, s, n, steps, log):
    proj = load_project(cfg, s)
    clip = load_clip(cfg, s, n)
    clip["error"] = ""
    try:
        for st in steps:
            log(f"Clip {n} - {st}")
            RUN[st](cfg, proj, clip, log)
            save_clip(cfg, s, clip)
    except Exception as ex:
        clip["error"] = str(ex)
        save_clip(cfg, s, clip)
        log(f"Clip {n} FAILED: {ex}")
        return False
    return True
