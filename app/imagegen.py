"""
imagegen.py — background images made by the app (no AI, no web): solid colours,
gradients, soft light, Islamic geometric pattern, night sky, bokeh, a
mihrab arch and an ornate frame. DESIGNS is the ready-made set users pick from. Pure Pillow + numpy, rendered at the video's own resolution.
"""
import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

KINDS = ("solid", "gradient", "radial", "aurora", "pattern", "stars", "bokeh", "arch", "arch_stars", "frame")


def _rgb(hex_color: str) -> np.ndarray:
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)
    except ValueError:
        return np.zeros(3, np.float32)


def _mix(a, b, t):
    return a + (b - a) * t


def _grid(W, H):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    return x / max(W - 1, 1), y / max(H - 1, 1)


def _to_img(arr) -> Image.Image:
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _vignette(img: Image.Image, strength: float = 0.45) -> Image.Image:
    W, H = img.size
    x, y = _grid(W, H)
    d = np.sqrt(((x - 0.5) * 1.15) ** 2 + ((y - 0.5) * 1.15) ** 2)
    f = 1 - strength * np.clip(d / 0.75, 0, 1) ** 2
    return _to_img(np.asarray(img, np.float32) * f[..., None])


def _grain(img: Image.Image, rng, amount: float = 3.0) -> Image.Image:
    """A little noise so gradients do not band in the video encoder."""
    a = np.asarray(img, np.float32)
    a += np.random.default_rng(rng.randrange(1 << 30)).normal(0, amount, a.shape[:2])[..., None]
    return _to_img(a)


def _gradient(W, H, c1, c2, angle=135):
    x, y = _grid(W, H)
    r = math.radians(angle)
    t = (x - 0.5) * math.cos(r) * (W / max(W, H)) + (y - 0.5) * math.sin(r) * (H / max(W, H))
    t = (t - t.min()) / (t.max() - t.min() + 1e-6)
    t = t * t * (3 - 2 * t)                                   # smooth step
    return _mix(c1, c2, t[..., None])


def _radial(W, H, c1, c2, cx=0.5, cy=0.42, size=0.75):
    x, y = _grid(W, H)
    asp = W / H
    d = np.sqrt(((x - cx) * asp) ** 2 + (y - cy) ** 2) / (size * max(asp, 1))
    t = np.clip(1 - d, 0, 1) ** 1.6
    return _mix(c1, c2, t[..., None])


def _star_pattern(W, H, color, alpha, cell):
    """Interlaced 8-point stars (two squares at 45°) on a square grid, with connecting lines."""
    S = 2                                                         # supersample for clean lines
    layer = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(layer)
    c = cell * S
    lw = max(2, int(c * 0.03))
    r = c * 0.36
    for gy in range(-1, H * S // int(c) + 2):
        for gx in range(-1, W * S // int(c) + 2):
            cx, cy = gx * c + (c / 2 if gy % 2 else 0), gy * c
            for rot in (0, 45):
                pts = [(cx + r * math.cos(math.radians(rot + 45 + 90 * k)), cy + r * math.sin(math.radians(rot + 45 + 90 * k)))
                       for k in range(4)]
                d.line(pts + [pts[0]], fill=255, width=lw)
            d.ellipse([cx - r * 0.28, cy - r * 0.28, cx + r * 0.28, cy + r * 0.28], outline=255, width=lw)
    layer = layer.resize((W, H), Image.LANCZOS)
    m = np.asarray(layer, np.float32)[..., None] / 255.0 * alpha
    return m, color


def _arch_mask(W, H):
    """A mihrab arch (pointed arch) centred, as a soft mask."""
    S = 2
    m = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(m)
    aw = min(W, H) * 0.62 * S
    x0, x1 = W * S / 2 - aw / 2, W * S / 2 + aw / 2
    top_y = H * S * 0.14
    spring = top_y + aw * 0.62
    bottom = H * S * 1.05
    pts = []
    for k in range(41):                                           # left half of the pointed arch
        a = math.radians(180 - 60 * k / 40)
        cxl = x0 + aw * 0.86
        pts.append((cxl + aw * 0.86 * math.cos(a), spring - aw * 0.86 * math.sin(a) * 0.72))
    right = [(W * S - x, y) for x, y in reversed(pts)]
    poly = [(x0, bottom)] + pts + right[1:] + [(x1, bottom)]
    d.polygon(poly, fill=255)
    m = m.resize((W, H), Image.LANCZOS)
    return m


def generate(kind: str, c1: str, c2: str, W: int, H: int, seed: int = 0) -> Image.Image:
    rng = random.Random(seed)
    a, b = _rgb(c1), _rgb(c2)
    dark = a * 0.35
    if kind == "solid":
        img = _to_img(np.broadcast_to(a, (H, W, 3)).copy())
        return _grain(img, rng, 1.5)
    if kind == "gradient":
        img = _to_img(_gradient(W, H, a, b, rng.choice((90, 120, 135, 160, 200, 225, 315))))
        return _grain(_vignette(img, 0.25), rng)
    if kind == "radial":
        img = _to_img(_radial(W, H, dark, b, 0.5, rng.uniform(0.32, 0.5), rng.uniform(0.55, 0.85)) * 0.6
                      + _radial(W, H, a, a * 1.1, 0.5, 0.5, 1.4) * 0.4)
        return _grain(_vignette(img, 0.35), rng)
    if kind == "aurora":
        base = _gradient(W, H, dark, a * 0.8, 160)
        lay = Image.new("RGB", (W // 4, H // 4))
        lay.paste(_to_img(base).resize((W // 4, H // 4)))
        d = ImageDraw.Draw(lay)
        for _ in range(7):
            col = tuple(int(v) for v in _mix(a, b, rng.random()))
            cx, cy, r = rng.uniform(0, W / 4), rng.uniform(0, H / 4), rng.uniform(0.15, 0.35) * max(W, H) / 4
            d.ellipse([cx - r, cy - r * 0.7, cx + r, cy + r * 0.7], fill=col)
        img = lay.filter(ImageFilter.GaussianBlur(max(W, H) / 4 * 0.09)).resize((W, H), Image.BICUBIC)
        return _grain(_vignette(img, 0.3), rng)
    if kind == "pattern":
        base = _gradient(W, H, a, dark, 135)
        m, col = _star_pattern(W, H, b, 0.28, min(W, H) / rng.choice((5, 6, 7)))
        img = _to_img(base * (1 - m) + b * m)
        img = _to_img(np.asarray(img, np.float32) * 0.75 + _radial(W, H, dark, a, 0.5, 0.5, 0.9) * 0.25)
        return _grain(_vignette(img, 0.5), rng)
    if kind == "stars":
        x, y = _grid(W, H)
        base = _mix(dark * 0.5, a, (y ** 1.6)[..., None])
        glow = _radial(W, H, np.zeros(3), b, 0.5, 1.05, 0.9)
        img = _to_img(base + glow * 0.55)
        d = ImageDraw.Draw(img)
        for _ in range(int(W * H / 2600)):
            sx, sy = rng.uniform(0, W), rng.uniform(0, H) * rng.uniform(0.2, 1) ** 0.7
            r = rng.choice((0.6, 0.8, 1.0, 1.0, 1.4, 2.0)) * max(W, H) / 1920
            v = int(rng.uniform(150, 255) * (1 - sy / H * 0.6))
            d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(v, v, min(255, v + 10)))
        img = Image.blend(img, img.filter(ImageFilter.GaussianBlur(1.2)), 0.35)
        return _grain(img, rng, 2.0)
    if kind == "bokeh":
        img = _to_img(_gradient(W, H, dark, a, rng.choice((120, 160, 200))))
        for blur, n, alpha in ((max(W, H) * 0.012, 14, 0.30), (max(W, H) * 0.004, 10, 0.40)):
            lay = Image.new("RGB", (W, H), (0, 0, 0))
            d = ImageDraw.Draw(lay)
            for _ in range(n):
                r = rng.uniform(0.02, 0.07) * max(W, H)
                cx, cy = rng.uniform(0, W), rng.uniform(0, H)
                col = tuple(int(v) for v in _mix(b, np.array([255, 255, 255.0]), rng.uniform(0, 0.35)))
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
            lay = lay.filter(ImageFilter.GaussianBlur(blur))
            img = _to_img(np.asarray(img, np.float32) + np.asarray(lay, np.float32) * alpha)
        return _grain(_vignette(img, 0.35), rng)
    if kind == "arch":
        base = _gradient(W, H, dark, a * 0.7, 90)
        mask = np.asarray(_arch_mask(W, H), np.float32)[..., None] / 255
        inner = _radial(W, H, a, b, 0.5, 0.45, 0.6)
        edge = np.asarray(_arch_mask(W, H).filter(ImageFilter.GaussianBlur(min(W, H) * 0.03)), np.float32)[..., None] / 255
        img = base * (1 - mask) + inner * mask + b * np.clip(edge - mask, 0, 1) * 0.9
        return _grain(_vignette(_to_img(img), 0.45), rng)
    if kind == "arch_stars":
        sky = np.asarray(generate("stars", c1, c2, W, H, seed), np.float32)
        mask = np.asarray(_arch_mask(W, H), np.float32)[..., None] / 255
        edge = np.asarray(_arch_mask(W, H).filter(ImageFilter.GaussianBlur(min(W, H) * 0.025)), np.float32)[..., None] / 255
        wall = _gradient(W, H, dark * 0.6, a * 0.45, 90)
        img = sky * mask + wall * (1 - mask) + b * np.clip(edge - mask, 0, 1) * 1.1
        return _grain(_vignette(_to_img(img), 0.4), rng)
    if kind == "frame":
        base = _radial(W, H, dark, a, 0.5, 0.5, 1.0)
        m, _ = _star_pattern(W, H, b, 0.10, min(W, H) / 6)
        img = _to_img(base * (1 - m) + b * m)
        S = 2
        lay = Image.new("L", (W * S, H * S), 0)
        d = ImageDraw.Draw(lay)
        u = min(W, H) * S
        for inset, lw in ((0.045, 0.006), (0.062, 0.0025)):
            i = int(u * inset)
            d.rectangle([i, i, W * S - i, H * S - i], outline=255, width=max(2, int(u * lw)))
        r = u * 0.022
        for cx, cy in ((u * 0.045, u * 0.045), (W * S - u * 0.045, u * 0.045),
                       (u * 0.045, H * S - u * 0.045), (W * S - u * 0.045, H * S - u * 0.045)):
            d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=255)
        lay = lay.resize((W, H), Image.LANCZOS)
        fm = np.asarray(lay, np.float32)[..., None] / 255 * 0.9
        img = _to_img(np.asarray(img, np.float32) * (1 - fm) + b * fm)
        return _grain(_vignette(img, 0.35), rng)
    raise ValueError(kind)


# ── ready-made designs: users just pick one ──
PALETTES = {
    "emerald": ("#0F3D2E", "#E8C068", "Emerald & gold", "زمردي وذهبي"),
    "night": ("#141A38", "#7FA7FF", "Night blue", "أزرق ليلي"),
    "onyx": ("#121212", "#D4AF37", "Black & gold", "أسود وذهبي"),
    "dusk": ("#2A1A3A", "#FF8FB1", "Dusk", "غروب"),
    "lagoon": ("#0B2A3A", "#5FE1D0", "Lagoon", "بحيرة"),
    "amber": ("#3A1F12", "#FFB35C", "Amber", "كهرماني"),
    "sage": ("#1E2A22", "#C8E6C9", "Sage", "مريمية"),
    "ruby": ("#3A0F16", "#F2B880", "Ruby", "ياقوتي"),
}
KIND_NAMES = {
    "gradient": ("Gradient", "تدرّج"), "radial": ("Soft light", "ضوء ناعم"), "aurora": ("Aurora", "شفق"),
    "pattern": ("Islamic pattern", "زخرفة إسلامية"), "stars": ("Night sky", "سماء ليلية"), "bokeh": ("Bokeh", "بوكيه"),
    "arch": ("Mihrab", "محراب"), "arch_stars": ("Mihrab & stars", "محراب ونجوم"), "frame": ("Ornate frame", "إطار مزخرف"),
}
_DESIGN_LIST = [
    ("emerald", "pattern"), ("emerald", "arch"), ("emerald", "frame"), ("emerald", "radial"),
    ("night", "arch_stars"), ("night", "stars"), ("night", "aurora"), ("night", "pattern"),
    ("onyx", "frame"), ("onyx", "pattern"), ("onyx", "radial"), ("onyx", "bokeh"),
    ("dusk", "aurora"), ("dusk", "bokeh"), ("dusk", "arch_stars"),
    ("lagoon", "aurora"), ("lagoon", "stars"), ("lagoon", "pattern"),
    ("amber", "radial"), ("amber", "arch"), ("amber", "bokeh"),
    ("sage", "pattern"), ("sage", "frame"),
    ("ruby", "arch"), ("ruby", "pattern"), ("ruby", "frame"),
]
DESIGNS = {f"{p}-{k}": {"palette": p, "kind": k} for p, k in _DESIGN_LIST}


def design_info(design_id: str) -> dict:
    d = DESIGNS[design_id]
    pal, kn = PALETTES[d["palette"]], KIND_NAMES[d["kind"]]
    return {"id": design_id, "name": f"{kn[0]} · {pal[2]}", "name_ar": f"{kn[1]} · {pal[3]}"}


def design_image(design_id: str, W: int, H: int) -> Image.Image:
    d = DESIGNS[design_id]
    c1, c2 = PALETTES[d["palette"]][:2]
    return generate(d["kind"], c1, c2, W, H, seed=sum(map(ord, design_id)))


def design_file(design_id: str, W: int, H: int, cache_dir) -> "Path":
    """The design as a JPEG of exactly W x H (made once, then cached)."""
    from pathlib import Path
    out = Path(cache_dir) / "designs" / f"{design_id}-{W}x{H}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part.jpg")
        design_image(design_id, W, H).save(tmp, "JPEG", quality=92 if W >= 720 else 82, subsampling=0)
        tmp.replace(out)
    return out
