"""Gets the stretch of the episode a clip needs (yt-dlp, or a local episode file)."""
import glob
import os
import sys

from . import ff

EP_FORMAT = ("bv*[height<=1080][ext=mp4][protocol=https]+ba[ext=m4a][protocol=https][language^=en]"
             "/bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b")


def hms(t):
    t = max(0, int(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def ytdlp(args, timeout=1200):
    return ff.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings",
                   "--socket-timeout", "30"] + args, timeout=timeout)


def fetch_window(episode, a, b, out, local_file=""):
    """Writes out (mp4) covering episode time a..b. `episode` is a YouTube id."""
    a = max(0, a)
    if local_file:
        ff.ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", local_file,
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
                   "-c:a", "aac", "-b:a", "192k", out])
        return out
    base = out[:-4]
    ytdlp(["-f", EP_FORMAT, "--download-sections", f"*{hms(a)}-{hms(b)}",
           "--merge-output-format", "mp4", "-o", base + ".%(ext)s",
           f"https://www.youtube.com/watch?v={episode}"])
    if not os.path.exists(out):
        got = [p for p in glob.glob(base + ".*") if not p.endswith(".part")]
        if not got:
            raise RuntimeError("yt-dlp downloaded nothing")
        os.replace(got[0], out)
    return out
