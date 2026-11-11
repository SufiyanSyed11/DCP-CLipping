"""Split-screen render: face-tracked podcast cam on top, B-roll below, captions on the seam."""
import os
import shutil
import subprocess

import cv2
import numpy as np

from . import ff, hook
from .broll import CH, CW, cover
from .config import ASSETS

FPS = ff.FPS
GRADE = "eq=contrast=1.06:saturation=1.08:gamma=1.03:brightness=0.02,unsharp=5:5:0.6:5:5:0"
ZOOM = 0.05                  # slow zoom pulse on the cam
LOGO = (240, 790, 124)       # width, x, y  (measured from the reference short)


def _gsmooth(a, sig):
    a = np.asarray(a, float)
    k = int(sig * 3) * 2 + 1
    x = np.arange(k) - k // 2
    g = np.exp(-x ** 2 / (2 * sig ** 2))
    g /= g.sum()
    return np.convolve(np.pad(a, (k // 2, k // 2), mode="edge"), g, mode="valid")


def cam_path(src, start_frame, n):
    """Per-frame horizontal face position (0..1 of frame width), smoothed within each camera cut."""
    det = cv2.FaceDetectorYN.create(os.path.join(ASSETS, "models", "yunet.onnx"), "", (640, 360))
    cap = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    xs, cuts, prev, last = [], [0], None, None
    for i in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(fr, (64, 36)), cv2.COLOR_BGR2GRAY).astype(np.int16)
        if prev is not None and np.abs(g - prev).mean() > 28:
            cuts.append(i)
            last = None
        prev = g
        x = np.nan
        if i % 2 == 0:
            h, w = fr.shape[:2]
            s = 640.0 / w
            sm = cv2.resize(fr, (640, int(h * s)))
            det.setInputSize((sm.shape[1], sm.shape[0]))
            _, faces = det.detect(sm)
            faces = [r for r in faces if r[14] > 0.75] if faces is not None else []
            if faces:
                if last is None:
                    r = max(faces, key=lambda r: r[2] * r[3])
                else:
                    r = min(faces, key=lambda r: abs((r[0] + r[2] / 2) / 640.0 - last))
                x = last = float((r[0] + r[2] / 2) / 640.0)
        xs.append(x)
    cap.release()
    xs = np.array(xs + [np.nan] * (n - len(xs)))
    out = np.full(n, 0.5)
    for a, b in zip(cuts, cuts[1:] + [n]):
        seg = xs[a:b]
        ok = ~np.isnan(seg)
        if ok.sum():
            idx = np.arange(len(seg))
            out[a:b] = _gsmooth(np.interp(idx, idx[ok], seg[ok]), 6)
    return out


def render_cam(p1, n, out, zach=None):
    """Top half (1080x960). `zach` = optional file whose frames replace the last 1.4 s."""
    K = int(round(1.4 * FPS)) if zach else 0
    path = cam_path(p1, 0, n)
    zpath = cam_path(zach, 15, K + 1) if zach else None
    cap = cv2.VideoCapture(p1)
    zcap = cv2.VideoCapture(zach) if zach else None
    if zcap:
        zcap.set(cv2.CAP_PROP_POS_FRAMES, 15)
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1080x960",
         "-r", ff.FPSS, "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
         "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    last = None
    for i in range(n):
        ok, fr = cap.read()
        cx = path[i]
        if zcap and i >= n - K:
            zok, zfr = zcap.read()
            if zok:
                ok, fr, cx = True, zfr, zpath[min(i - (n - K), len(zpath) - 1)]
        if not ok:
            fr = last
        if fr is None:
            break
        last = fr
        f = cover(fr)
        H, Wd = f.shape[:2]
        z = 1 + ZOOM * (0.5 - 0.5 * np.cos(2 * np.pi * i / 170.0))
        w, h = int(CW / z) // 2 * 2, int(CH / z) // 2 * 2
        x0 = int(round(min(max(cx * Wd - w / 2, 0), Wd - w)))
        y0 = int((H - h) * 0.3)
        enc.stdin.write(cv2.resize(f[y0:y0 + h, x0:x0 + w], (1080, 960),
                                   interpolation=cv2.INTER_LANCZOS4).tobytes())
    enc.stdin.close()
    enc.wait()
    cap.release()
    if zcap:
        zcap.release()


def render_shot(src, ss, fx, frames, out):
    """One bottom-half B-roll piece (1080x960) with a slow push-in."""
    d = frames / FPS
    vf = (f"fps={ff.FPSS},scale={CW}:{CH}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={CW}:{CH}:(iw-{CW})*{fx:.4f}:(ih-{CH})/2,"
          f"scale=w='2*trunc(540*(1+0.07*t/{d:.3f}))':h='2*trunc(480*(1+0.07*t/{d:.3f}))':eval=frame,"
          f"crop=1080:960,setsar=1,tpad=stop_mode=clone:stop_duration=6")
    ff.ffmpeg(["-ss", f"{max(0, ss):.3f}", "-i", src, "-an", "-vf", vf, "-frames:v", str(frames),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", out])


def resolve_shots(slots, cands, picks):
    """Slot -> concrete (path, start time, crop position), rotating through alternatives."""
    usable = [i for i, c in cands.items() if c]
    if not usable:
        raise RuntimeError("No B-roll chosen yet. Run 'Find B-roll' or add a source by hand.")
    shots, played, uses = [], {}, {}
    for n, s in enumerate(slots):
        item = s["item"] if cands.get(s["item"]) else usable[n % len(usable)]
        cl = cands[item]
        if "pick" in s and s["pick"] is not None and s["pick"] < len(cl):
            c = cl[s["pick"]]
        else:
            first = int(picks.get(item, 0)) % len(cl)
            c = cl[(first + uses.get(item, 0)) % len(cl)]
        uses[item] = uses.get(item, 0) + 1
        key = (c["path"], c["t"])
        off = played.get(key, 0.0)
        d = s["end"] - s["start"]
        played[key] = off + d
        shots.append({"path": c["path"], "ss": c["t"] + off, "fx": c["fx"], "start": s["start"],
                      "end": s["end"], "vid": c["vid"], "title": c.get("title", ""),
                      "item": item, "word": s.get("word", "")})
    return shots


def bleep_filter(windows):
    if not windows:
        return ""
    w = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in windows)
    tone = f"if(gt({w},0.5),0.25*sin(2*PI*1000*t),0)"
    return (f"volume=enable='gt({w},0.5)':volume=0,"
            f"aeval='val(0)+{tone}|val(1)+{tone}',aformat=channel_layouts=stereo,")


def compose(cdir, shots, n, cfg, hook_text, emoji, bleeps, zach=None, log=print):
    """Renders final.mp4 in the clip folder from P1.mp4, captions.ass and the shots."""
    p1 = os.path.join(cdir, "P1.mp4")
    dur = n / FPS
    log("  tracking the camera")
    render_cam(p1, n, os.path.join(cdir, "cam.mp4"), zach)
    inputs = ["-i", "cam.mp4"]
    labs, used = "", 0
    for k, s in enumerate(shots):
        a = used
        b = n if k == len(shots) - 1 else min(n, round(s["end"] * FPS))
        if b - a < 2:
            continue
        log(f"  shot {k + 1}/{len(shots)}: {s['vid']} @ {s['ss']:.1f}s")
        render_shot(s["path"], s["ss"], s["fx"], b - a, os.path.join(cdir, f"br_{k}.mp4"))
        inputs += ["-i", f"br_{k}.mp4"]
        labs += f"[{len(inputs) // 2 - 1}:v]"
        used = b
    nb = len(inputs) // 2 - 1
    fc = [f"{labs}concat=n={nb}:v=1:a=0[bot]", f"[0:v][bot]vstack,{GRADE}[sg]"]

    # voice at -14 LUFS, then music ~19 dB under it with ducking
    ff.ffmpeg(["-i", p1, "-vn", "-af",
               "loudnorm=I=-14:TP=-1.5:LRA=7,aformat=sample_rates=48000:channel_layouts=stereo",
               os.path.join(cdir, "voice.wav")])
    inputs += ["-i", "voice.wav"]
    vi = nb + 1
    shutil.copy(os.path.join(ASSETS, "dc_logo.png"), os.path.join(cdir, "logo.png"))
    inputs += ["-i", "logo.png"]
    li = vi + 1
    fc.append(f"[{li}:v]scale={LOGO[0]}:-1,format=rgba[lg]")
    fc.append(f"[sg][lg]overlay={LOGO[1]}:{LOGO[2]}[ov]")
    fonts = os.path.join(ASSETS, "fonts")          # optional: drop Lato-Black.ttf in assets/fonts
    fdir = ""
    if os.path.isdir(fonts) and any(f.lower().endswith((".ttf", ".otf")) for f in os.listdir(fonts)):
        shutil.copytree(fonts, os.path.join(cdir, "fonts"), dirs_exist_ok=True)
        fdir = ":fontsdir=fonts"
    fc.append(f"[ov]subtitles=captions.ass{fdir}[cap]")
    nxt, vout = li + 1, "[cap]"
    if hook_text.strip():
        hook.make(hook_text.strip(), emoji, os.path.join(cdir, "hook.png"))
        inputs += ["-loop", "1", "-t", "4.2", "-i", "hook.png"]
        fc.append(f"[{nxt}:v]scale='min(960,iw)':-1,format=rgba,fade=in:st=0:d=0.18:alpha=1,"
                  f"fade=out:st=3.4:d=0.3:alpha=1[hk]")
        fc.append("[cap][hk]overlay=(W-w)/2:960-h/2:eof_action=pass:format=auto[vh]")
        vout = "[vh]"
        nxt += 1
    extra = bleep_filter(bleeps)
    bgm = cfg["bgm"]
    if os.path.exists(bgm):
        vm = ff.mean_volume(["-i", os.path.join(cdir, "voice.wav")])
        bm = ff.mean_volume(["-ss", "10", "-t", "20", "-i", bgm])
        inputs += ["-ss", "10", "-i", bgm]
        fc.append(f"[{nxt}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                  f"volume={vm - bm - 19:.2f}dB,atrim=0:{dur:.3f},afade=t=in:d=0.8,"
                  f"afade=t=out:st={max(0, dur - 1.2):.3f}:d=1.2[bg]")
        fc.append(f"[{vi}:a]{extra}asplit[va][vs]")
        fc.append("[bg][vs]sidechaincompress=threshold=0.05:ratio=6:attack=15:release=250[bgd]")
        fc.append("[va][bgd]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.9[a]")
    else:
        log("  WARNING: background music file not found, rendering without music: " + bgm)
        fc.append(f"[{vi}:a]{extra}alimiter=limit=0.9[a]")
    ff.ffmpeg(inputs + ["-filter_complex", ";".join(fc), "-map", vout, "-map", "[a]"]
              + ff.video_codec(cfg) + ["-r", ff.FPSS, "-c:a", "aac", "-b:a", "192k",
                                       "-t", f"{dur:.3f}", "-movflags", "+faststart", "final.mp4"],
              cwd=cdir)
    for f in os.listdir(cdir):
        if f.startswith("br_") or f in ("cam.mp4", "voice.wav", "logo.png"):
            os.remove(os.path.join(cdir, f))
    return os.path.join(cdir, "final.mp4")


def contact_sheet(cdir):
    """3 fps sheet with time labels, for the eyeball check."""
    font = next((p for p in hook.FONTS if os.path.exists(p)), None)
    draw = ""
    if font:
        shutil.copy(font, os.path.join(cdir, "qa.ttf"))
        draw = ("drawtext=fontfile=qa.ttf:text='%{pts\\:flt}':fontsize=64:fontcolor=yellow:"
                "box=1:boxcolor=black@0.6:x=12:y=12,")
    d = ff.duration(os.path.join(cdir, "final.mp4"))
    rows = int(np.ceil(d * 3 / 10)) or 1
    ff.ffmpeg(["-i", "final.mp4", "-vf", f"fps=3,{draw}scale=216:-1,tile=10x{rows}",
               "-frames:v", "1", "-q:v", "4", "sheet.jpg"], cwd=cdir)
    if font:
        os.remove(os.path.join(cdir, "qa.ttf"))
