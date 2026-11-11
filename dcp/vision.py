"""Optional local AI (runs on the PC's GPU): image/text matching and on-screen text detection.

Everything here degrades gracefully: without torch/open_clip the tool still works,
it just can't choose B-roll moments by itself.
"""
import os

import numpy as np

_clip = None
_ocr = None


def available():
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    global _clip
    if _clip is None:
        import open_clip
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        from . import ff
        from .config import ASSETS
        # A model file dropped into assets/models is used as-is (no download).
        mdir = os.path.join(ASSETS, "models")
        local = [f for f in sorted(os.listdir(mdir))
                 if f.lower().endswith((".bin", ".safetensors", ".pt")) and "clip" in f.lower()]
        if local:
            ff.log(f"    loading the AI picker on {dev} from assets/models/{local[0]}")
            weights = os.path.join(mdir, local[0])
        else:
            ff.log(f"    loading the AI picker on {dev} (the first time downloads about 600 MB)")
            weights = "laion2b_s34b_b79k"
        model, _, pre = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained=weights, device=dev)
        model.eval()
        ff.log("    AI picker ready")
        _clip = (model, pre, open_clip.get_tokenizer("ViT-B-32"), dev)
    return _clip


def embed_images(frames):
    """frames: list of BGR arrays -> unit vectors (n, d)."""
    import torch
    from PIL import Image
    model, pre, _, dev = _load()
    out = []
    for i in range(0, len(frames), 32):
        batch = torch.stack([pre(Image.fromarray(f[:, :, ::-1])) for f in frames[i:i + 32]])
        with torch.no_grad():
            e = model.encode_image(batch.to(dev)).float()
        out.append((e / e.norm(dim=-1, keepdim=True)).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


def embed_texts(texts):
    import torch
    model, _, tok, dev = _load()
    with torch.no_grad():
        e = model.encode_text(tok(list(texts)).to(dev)).float()
    return (e / e.norm(dim=-1, keepdim=True)).cpu().numpy()


def text_fraction(frame):
    """Share of the frame covered by readable text (0..1), or None if OCR isn't installed."""
    global _ocr
    try:
        if _ocr is None:
            import easyocr
            import torch
            from . import ff
            ff.log("    loading the on-screen text checker (the first time downloads its model)")
            _ocr = easyocr.Reader(["en"], gpu=torch.cuda.is_available(), verbose=False)
        h, w = frame.shape[:2]
        area = 0.0
        for box, _text, conf in _ocr.readtext(frame):
            if conf < 0.4:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            area += (max(xs) - min(xs)) * (max(ys) - min(ys))
        return area / float(w * h)
    except Exception:
        return None
