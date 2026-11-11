"""Reads a clip slate .docx (the format of Hokit_14_Clip_Slate.docx) into clip records."""
import re

TS = r"(\d{1,2}:\d{2}(?::\d{2})?)"
RANGE = re.compile(TS + r"\s*[-\u2013\u2014]\s*" + TS)
YT_ID = r"([A-Za-z0-9_-]{11})"
QUOTE = re.compile(r"[\"\u201c]([^\"\u201d]+)[\"\u201d]")
LABELS = {
    "hook to payoff": "hook_payoff", "source": "source", "hook box": "hook",
    "b-roll": "broll", "weak spot": "weak", "gates": "gates",
}


def seconds(ts):
    t = 0
    for p in ts.split(":"):
        t = t * 60 + int(p)
    return t


def split_emoji(text):
    """'Then he said this 🚗' -> ('Then he said this', '🚗')"""
    text = text.strip()
    m = re.search(r"[^\x00-\u024f\u2010-\u203a]+$", text)
    if not m:
        return text, ""
    return text[:m.start()].strip(), m.group(0).strip()


def split_outside_parens(text, seps=";,"):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch in seps and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def _item(part, head=""):
    """One B-roll item. It may carry the spoken words it belongs on, in quotes:
    '"locked the door": door being bolted'   or   'door being bolted ("locked the door")'."""
    part = re.sub(r"(?i)^(then|and)\s+", "", part).strip()
    cue = ""
    q = QUOTE.search(part)
    if q:
        cue = q.group(1).strip(" .,")
        part = (part[:q.start()] + " " + part[q.end():])
        part = re.sub(r"\(\s*(?:on|at|over|when)?\s*\)|\[\s*(?:on|at|over|when)?\s*\]", " ", part, flags=re.I)
        part = re.sub(r"(?i)^\s*(?:on|at|over|when)?\s*(?:->|=>|=|:|-|\u2192)\s*", "", part.strip())
        part = re.sub(r"(?i)\s*(?:->|=>|=|:|-|\u2192|\bon|\bat|\bover|\bwhen)\s*$", "", part.strip())
    fixed = None
    fm = re.search(r"(?:v=|youtu\.be/|\b)" + YT_ID + r"\b\S*\s+" + RANGE.pattern, part)
    if fm and re.search(r"[0-9_-]|[a-z][A-Z]", fm.group(1)):
        fixed = {"vid": fm.group(1), "t": seconds(fm.group(2)), "t_end": seconds(fm.group(3))}
        part = part[:fm.start()].strip(" :-,") or fm.group(1)
    hint = " ".join(re.findall(r"\(([^)]*)\)", part))
    plain = re.sub(r"\([^)]*\)", "", part)
    plain = re.sub(r"(?i)\s+if (clean|available|usable)\b.*$", "", plain).strip(" .")
    if not plain:
        plain = cue
    if not plain:
        return None
    search = plain
    if head:
        search = re.sub(r"(?i)\b(official|footage)\b", "", head).strip() + " " + plain
    return {"search": search, "match": plain, "hint": hint, "fixed": fixed, "cue": cue}


def parse_broll(text):
    """Turns the B-roll line into a list of {search, match, cue, fixed} items plus notes.

    An item may name the spoken words it goes on ('"locked the door": door being bolted')
    and/or an exact source ('Floyd belts Ck_l3DOg9iQ 0:56-1:05').
    """
    items, notes = [], []
    if QUOTE.search(text):                      # cue style: items are separated by ';' only
        keep = []
        for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
            if re.match(r"(?i)(no|avoid|never|don't|check)\b", sent) and not QUOTE.search(sent):
                notes.append(sent.strip().rstrip("."))
            else:
                keep.append(sent)
        for part in split_outside_parens(" ".join(keep).rstrip("."), ";"):
            if re.match(r"(?i)(no|avoid|never|don't|check)\b", part) and not QUOTE.search(part):
                notes.append(part.rstrip("."))
                continue
            it = _item(part)
            if it:
                items.append(it)
        return items, " ".join(notes)
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        sent = sent.strip().rstrip(".")
        if not sent:
            continue
        if re.match(r"(?i)(no|avoid|never|don't|check)\b", sent):
            notes.append(sent)
            continue
        head = ""
        m = re.match(r"([^:;(]{4,80}):\s+(.*)", sent)
        if m and "http" not in m.group(1):
            head, sent = m.group(1).strip(), m.group(2)
        seps = ";" if ";" in sent else ";,"
        for part in split_outside_parens(sent, seps):
            it = _item(part, head)
            if it:
                items.append(it)
    return items, " ".join(notes)


def parse_source(text):
    segs = [[seconds(a), seconds(b)] for a, b in RANGE.findall(text)]
    m = re.search(r"(?i)start\s+(?:host\s+)?[\"\u201c]([^\"\u201d]+)[\"\u201d]", text)
    start_phrase = m.group(1) if m else ""
    rest = text
    if m:
        rest = text[m.end():]
    else:
        last = None
        for last in RANGE.finditer(text):
            pass
        if last:
            rest = text[last.end():]
    rest = re.sub(r"^\s*\(\d+\s*s\)", "", rest).strip(" .;")
    return segs, start_phrase, rest


def parse_paragraphs(paras):
    """paras: list of (style_name, text). Returns the slate dict."""
    slate = {"title": "", "episode": "", "intro": "", "clips": []}
    clip = None
    for style, text in paras:
        text = text.strip()
        if not text:
            continue
        head = re.match(r"^(\d{1,2})[.)]\s+(.+)$", text)
        is_heading = style.lower().startswith("heading") or (head and ":" not in text[:14])
        if style.lower() == "title" and not slate["title"]:
            slate["title"] = text
            continue
        if head and is_heading:
            clip = {"n": int(head.group(1)), "title": head.group(2).strip(), "hook_payoff": "",
                    "payoff": "", "source_text": "", "segments": [], "start_phrase": "",
                    "notes": "", "hook_text": "", "emoji": "", "broll": [], "broll_notes": "",
                    "weak": "", "gates": ""}
            slate["clips"].append(clip)
            continue
        if style.lower().startswith("heading"):
            clip = None          # e.g. "Left out on purpose"
            continue
        if clip is None:
            if not slate["clips"]:
                slate["intro"] += text + "\n"
                m = (re.search(r"(?:v=|youtu\.be/)" + YT_ID, text)
                     or re.search(r"(?i)episode\s+(?:id\s+)?`?" + YT_ID + r"\b", text))
                if m and not slate["episode"]:
                    slate["episode"] = m.group(1)
            continue
        m = re.match(r"^([A-Za-z\- ]{3,16})(\s*\([^)]*\))?\s*:\s*(.*)$", text, re.S)
        key = LABELS.get(m.group(1).strip().lower()) if m else None
        if not key:
            continue
        val = m.group(3).strip()
        if key == "hook_payoff":
            clip["hook_payoff"] = val
            q = QUOTE.findall(val)
            clip["payoff"] = q[-1].strip(" .") if q else ""
        elif key == "source":
            clip["source_text"] = val
            clip["segments"], clip["start_phrase"], clip["notes"] = parse_source(val)
        elif key == "hook":
            clip["hook_text"], clip["emoji"] = split_emoji(val)
        elif key == "broll":
            clip["broll"], clip["broll_notes"] = parse_broll(val)
        else:
            clip[key] = val
    return slate


def parse_docx(path):
    import docx
    d = docx.Document(path)
    paras = [(p.style.name if p.style is not None else "", p.text) for p in d.paragraphs]
    slate = parse_paragraphs(paras)
    if not slate["title"] and paras:
        slate["title"] = paras[0][1].strip()
    return slate


def guest_name(title):
    """'Josh Hokit episode: gated slate of 14 clips' -> 'Hokit'"""
    m = re.match(r"(.+?)\s+episode", title, re.I)
    name = m.group(1) if m else title.split(":")[0]
    return re.sub(r"[^A-Za-z0-9]+", "", name.split()[-1]) if name.split() else "Clip"
