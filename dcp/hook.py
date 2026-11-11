"""The white rounded hook box with bold black text and an Apple emoji."""
import os
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS

FONTS = ["C:/Windows/Fonts/arialbd.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
EMOJI_URL = "https://cdn.jsdelivr.net/npm/emoji-datasource-apple@15.0.1/img/apple/64/{}.png"


def wrap(text, max_chars=24):
    """Balanced 2-3 line wrap, like the reference hook boxes."""
    ws = text.split()
    if not ws:
        return [""]
    n = 1 if len(text) <= 16 else min(3, max(2, -(-len(text) // max_chars)))
    best = None

    def rec(i, left, cur):
        nonlocal best
        if left == 1:
            lines = cur + [" ".join(ws[i:])]
            cost = max(len(x) for x in lines) - min(len(x) for x in lines)
            if best is None or cost < best[0]:
                best = (cost, lines)
            return
        for j in range(i + 1, len(ws) - left + 2):
            rec(j, left - 1, cur + [" ".join(ws[i:j])])

    rec(0, min(n, len(ws)), [])
    return best[1]


def emoji_png(emoji):
    """Path of the Apple emoji image (downloaded once), or None."""
    if not emoji:
        return None
    cps = [f"{ord(c):x}" for c in emoji]
    for code in ("-".join(cps), "-".join(c for c in cps if c != "fe0f"), cps[0]):
        path = os.path.join(ASSETS, "emoji", code + ".png")
        if os.path.exists(path):
            return path
        try:
            req = urllib.request.Request(EMOJI_URL.format(code), headers={"User-Agent": "dcp"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            return path
        except Exception:
            continue
    return None


def make(text, emoji, out):
    lines = wrap(text)
    fpath = next((p for p in FONTS if os.path.exists(p)), None)
    font = ImageFont.truetype(fpath, 66) if fpath else ImageFont.load_default(66)
    big = ImageFont.truetype(fpath, 132) if fpath else ImageFont.load_default(132)
    ep = emoji_png(emoji)
    extra = 14 + 84 if ep else 0
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    ws = [d.textlength(l, font=font) for l in lines]
    pw, ph, lh, s = 60, 36, 86, 2
    W = int(max(ws[:-1] + [ws[-1] + extra]) + 2 * pw)
    H = int(len(lines) * lh + 2 * ph)
    im = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, W * s - 1, H * s - 1], radius=34 * s, fill=(255, 255, 255, 255))
    for i, l in enumerate(lines):
        last = i == len(lines) - 1
        x = (W - ws[i] - (extra if last else 0)) / 2
        y = ph + i * lh + 6
        dr.text((x * s, y * s), l, font=big, fill=(0, 0, 0, 255))
        if last and ep:
            em = Image.open(ep).convert("RGBA").resize((84 * s, 84 * s), Image.LANCZOS)
            im.alpha_composite(em, (int((x + ws[i] + 14) * s), int((y - 4) * s)))
    im = im.resize((W, H), Image.LANCZOS)
    im.save(out)
    return out
