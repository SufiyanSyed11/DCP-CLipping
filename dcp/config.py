import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

DEFAULTS = {
    # Where scratch files go, and where finished pack folders are written.
    "work_dir": os.path.join(ROOT, "work"),
    "output_dir": os.path.join(ROOT, "output"),
    # Background music. Not shipped in the repo: copy bgm_under.mp3 into assets/.
    "bgm": os.path.join(ASSETS, "bgm_under.mp3"),
    "whisper_model": "small.en",
    "whisper_device": "cpu",       # "cuda" needs the NVIDIA cuDNN libraries installed
    "encoder": "auto",             # auto | h264_nvenc | libx264
    "pause_threshold": 150,        # RMS below this counts as silence (pause removal)
    "pause_min": 0.22,
    "pause_margin": 0.08,
    "broll_search_results": 6,     # YouTube results looked at per B-roll line
    "broll_downloads": 2,          # videos downloaded per B-roll line
    "broll_max_seconds": 480,      # only the first N seconds of each video are fetched
    "shot_seconds": 2.6,           # average length of a B-roll shot
    "rejected_channels": ["Fight Hub TV", "FightHype", "BatmanBoxing",
                          "Punsh Drunk", "GSD Boxing"],
    "profanity": ["fuck", "shit", "bitch", "motherfuck", "nigga", "pussy", "cunt"],
    "port": 8765,
}


def load():
    cfg = dict(DEFAULTS)
    path = os.environ.get("DCP_CONFIG") or os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    for k in ("work_dir", "output_dir", "bgm"):
        if not os.path.isabs(cfg[k]):
            cfg[k] = os.path.join(ROOT, cfg[k])
    os.makedirs(cfg["work_dir"], exist_ok=True)
    os.makedirs(cfg["output_dir"], exist_ok=True)
    return cfg
