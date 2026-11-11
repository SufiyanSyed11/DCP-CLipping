"""Writes the finished pack folder and the tracker line."""
import json
import os
import re
import shutil
import time


def pack(clip, cdir, show, cfg):
    name = re.sub(r"[^A-Za-z0-9]+", "_", clip["title"]).strip("_")[:40]
    folder = os.path.join(cfg["output_dir"], f"{show}_{clip['n']:02d}_{name}")
    os.makedirs(folder, exist_ok=True)
    for src, dst in (("final.mp4", "FINAL_EDIT_splitscreen.mp4"),
                     ("P1.mp4", "PODCAST_EDITED_no_pauses.mp4"),
                     ("captions.ass", "captions.ass"), ("hook.png", "hook_overlay.png")):
        p = os.path.join(cdir, src)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(folder, dst))
    shots = clip.get("shots", [])
    with open(os.path.join(folder, "shots.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in s.items() if k != "path"} for s in shots], f, indent=1)
    notes = [f"{show} {clip['n']:02d}: {clip['title']}", "",
             f"Episode times: {clip.get('source_text', '')}",
             f"Hook box: {clip.get('hook_text', '')} {clip.get('emoji', '')}", "", "B-ROLL SHOTS"]
    for s in shots:
        line = clip["broll"][s["item"]]["match"] if s["item"] < len(clip["broll"]) else ""
        said = f' (on the word "{s["word"]}")' if s.get("word") else ""
        notes.append(f"- {s['start']:.2f}-{s['end']:.2f}s  {line}{said}\n"
                     f"    https://www.youtube.com/watch?v={s['vid']}  from {s['ss']:.1f}s  {s.get('title', '')}")
    notes += ["", f"Zach: {'cutaway from episode ' + str(clip['zach_time']) if clip.get('zach_time') else 'as in the podcast cut'}",
              "", f"Weak spots (from the slate): {clip.get('weak', '')}",
              f"QA: {json.dumps(clip.get('qa', {}))}"]
    with open(os.path.join(folder, "BROLL_NOTES.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")
    tracker = os.path.join(cfg["output_dir"], "CLIP_TRACKER.txt")
    done = os.path.exists(tracker) and os.path.basename(folder) in open(tracker, encoding="utf-8", errors="replace").read()
    with open(tracker, "a", encoding="utf-8") as f:
        f.write("" if done else f"{time.strftime('%Y-%m-%d')} | {show}_{clip['n']:02d} | {clip['title']} | "
                f"{clip.get('source_text', '')[:40]} | {os.path.basename(folder)}\n")
    return folder
