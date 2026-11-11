"""One-word-at-a-time captions (ASS), name fixes and profanity masking."""
import os
import re

from .config import ASSETS


def parse_fixes(text):
    """'sir gone = Gane' per line -> [(['sir','gone'], 'Gane')], longest first."""
    out = []
    for line in (text or "").splitlines():
        if "=" in line:
            a, b = line.split("=", 1)
            src = [re.sub(r"[^a-z0-9']", "", x.lower()) for x in a.split()]
            if src and b.strip():
                out.append((src, b.strip()))
    return sorted(out, key=lambda f: -len(f[0]))


def apply_fixes(tokens, fixes):
    key = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())
    out, i = [], 0
    while i < len(tokens):
        for src, dst in fixes:
            n = len(src)
            if [key(t[0]) for t in tokens[i:i + n]] == src:
                out.append([dst, tokens[i][1], tokens[i + n - 1][2]])
                i += n
                break
        else:
            out.append(list(tokens[i]))
            i += 1
    return out


def smooth(tokens, total):
    """Spreads words that start closer than 0.13 s; end = next start, capped."""
    t = sorted(([w, float(s), float(e)] for w, s, e in tokens), key=lambda x: x[1])
    for i in range(1, len(t)):
        if t[i][1] - t[i - 1][1] < 0.13:
            t[i][1] = t[i - 1][1] + 0.13
    for i, w in enumerate(t):
        nxt = t[i + 1][1] if i + 1 < len(t) else total
        e = min(nxt, total)
        if e - w[1] > 0.7:
            e = w[1] + 0.5
        if e - w[1] < 0.05:
            e = w[1] + 0.08
        w[1], w[2] = round(w[1], 2), round(e, 2)
    return t


def is_profane(word, bad):
    k = re.sub(r"[^a-z]", "", word.lower())
    return any(b in k for b in bad)


def mask(word):
    w = re.sub(r"[^A-Za-z']", "", word)
    return w if len(w) < 3 else w[0] + "**" + w[3:]


def bleeps(tokens, bad):
    return [[max(0, s - 0.03), e + 0.03] for w, s, e in tokens if is_profane(w, bad)]


def display(word, bad):
    w = mask(word) if is_profane(word, bad) else word
    return re.sub(r"[.,!?;:\"]+", "", w).lower()


def write_ass(tokens, out, bad):
    with open(os.path.join(ASSETS, "caption_style.ass"), encoding="utf-8") as f:
        hdr = f.read()
    ts = lambda x: f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"
    lines = [hdr.rstrip("\n"), "", "[Events]",
             "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    for w, s, e in tokens:
        text = display(w, bad)
        if text:
            lines.append(f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\pos(540,962)}}{text}")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
