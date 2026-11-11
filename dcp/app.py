"""Local web app. Run:  python -m dcp.app   then open http://127.0.0.1:8765"""
import collections
import os
import queue
import threading
import time
import webbrowser

import cv2
from flask import Flask, Response, jsonify, request, send_from_directory

from . import broll, config, ff, pipeline, vision

cfg = config.load()
app = Flask(__name__, static_folder="static", static_url_path="/static")
jobs = queue.Queue()
logbuf = collections.deque(maxlen=400)
state = {"running": "", "version": 0}
EDITABLE = {"keep", "adj", "tokens", "hook_text", "emoji", "broll", "picks", "slots",
            "zach_time", "cands"}


def log(msg):
    logbuf.append(time.strftime("%H:%M:%S ") + str(msg))
    state["version"] += 1


ff.set_logger(log)


def worker():
    while True:
        label, fn = jobs.get()
        state["running"] = label
        try:
            fn()
        except Exception as ex:           # keep the worker alive whatever happens
            log(f"ERROR: {ex}")
        state["running"] = ""
        state["version"] += 1


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def api_state():
    return jsonify(projects=pipeline.list_projects(cfg), running=state["running"],
                   queued=jobs.qsize(), log=list(logbuf)[-120:], version=state["version"],
                   ai=vision.available(), bgm=os.path.exists(cfg["bgm"]),
                   output_dir=cfg["output_dir"])


@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".docx"):
        return jsonify(error="Please choose a .docx slate."), 400
    path = os.path.join(cfg["work_dir"], "_upload.docx")
    f.save(path)
    try:
        proj = pipeline.create_project(cfg, path)
    except Exception as ex:
        return jsonify(error=str(ex)), 400
    log(f"Loaded slate: {proj['title']} ({len(proj['clip_numbers'])} clips)")
    return jsonify(slug=proj["slug"])


@app.post("/api/project/<s>")
def api_project(s):
    proj = pipeline.load_project(cfg, s)
    for k in ("episode", "local_file", "fixes", "show"):
        if k in request.json:
            proj[k] = str(request.json[k]).strip() if k != "fixes" else request.json[k]
    pipeline.save_project(cfg, proj)
    return jsonify(ok=True)


@app.get("/api/clip/<s>/<int:n>")
def api_clip(s, n):
    return jsonify(pipeline.load_clip(cfg, s, n))


@app.post("/api/clip/<s>/<int:n>")
def api_clip_save(s, n):
    if state["running"]:
        return jsonify(error="Wait for the current job to finish before editing."), 409
    clip = pipeline.load_clip(cfg, s, n)
    data = request.json
    for k, v in data.items():
        if k in EDITABLE:
            clip[k] = v
    if "broll" in data:
        while len(clip["cands"]) < len(clip["broll"]):
            clip["cands"].append([])
            clip["picks"].append(0)
        del clip["cands"][len(clip["broll"]):], clip["picks"][len(clip["broll"]):]
    if "broll" in data or data.get("retime"):
        pipeline.retime(cfg, clip)
    pipeline.save_clip(cfg, s, clip)
    return jsonify(clip)


@app.post("/api/run")
def api_run():
    d = request.json
    s, steps = d["slug"], [x for x in d["steps"] if x in pipeline.RUN]
    proj = pipeline.load_project(cfg, s)
    ns = proj["clip_numbers"] if d["n"] == "all" else [int(d["n"])]
    for n in ns:
        jobs.put((f"clip {n}: {', '.join(steps)}",
                  lambda n=n: pipeline.run_steps(cfg, s, n, steps, log)))
    return jsonify(ok=True)


@app.post("/api/manual")
def api_manual():
    d = request.json
    s, n, i = d["slug"], int(d["n"]), int(d["item"])

    def job():
        proj = pipeline.load_project(cfg, s)
        clip = pipeline.load_clip(cfg, s, n)
        log(f"Clip {n} - adding B-roll by hand")
        pipeline.add_manual(cfg, proj, clip, i, d["ref"].strip().strip('"'), float(d["t"]), log)
        pipeline.save_clip(cfg, s, clip)

    jobs.put((f"clip {n}: add B-roll", job))
    return jsonify(ok=True)


@app.get("/api/thumb/<s>/<int:n>/<int:i>/<int:k>")
def api_thumb(s, n, i, k):
    """Live preview of a candidate at a different time / crop position."""
    c = pipeline.load_clip(cfg, s, n)["cands"][i][k]
    fr = broll.frame_at(c["path"], float(request.args.get("t", c["t"])) + 1)
    if fr is None:
        return "", 404
    img = cv2.resize(broll.crop98(fr, float(request.args.get("fx", c["fx"]))), (304, 270))
    return Response(cv2.imencode(".jpg", img)[1].tobytes(), mimetype="image/jpeg")


@app.get("/work/<path:p>")
def work_file(p):
    return send_from_directory(cfg["work_dir"], p, max_age=0)


def main():
    threading.Thread(target=worker, daemon=True).start()
    url = f"http://127.0.0.1:{cfg['port']}"
    print(f"\n  DCP Clipper is running. Open {url}\n  (close this window to stop it)\n")
    if not os.environ.get("DCP_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=cfg["port"], threaded=True)


if __name__ == "__main__":
    main()
