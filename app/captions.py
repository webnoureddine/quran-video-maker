"""
captions.py — Quran caption styles, fonts and the ASS subtitle generator.

A caption STYLE is a plain dict of options. Built-in styles are JSON files
in caption_styles/ (file name = style id); more can be added as rows of the
Supabase `caption_styles` table. Any key left out falls back to DEFAULTS.

Display rule: each ayah is cut into lines of exactly `max_words_per_line`
words and ONE line is on screen at a time; app/sync.py times each line to the
reciter. Word animations (karaoke, highlight, word reveal, glow) follow the
recitation word by word (app/align.py word times, or recitation length).

The Arabic is the exact published text (Uthmani, or the standard "simple"
script for display fonts without Uthmani marks), only framed with ﴿ ﴾.
Rendering: Encoding -1 (automatic right-to-left paragraphs) + libass complex
shaping (HarfBuzz), so per-word override tags keep the right word order.
"""
import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from app import sync

ROOT = Path(__file__).resolve().parent.parent
STYLES_DIR = ROOT / "caption_styles"

DEFAULTS = {
    "label": "Custom", "label_ar": "", "description": "", "description_ar": "", "sort": 99,
    "ar_font": "Amiri", "tr_font": "DejaVu Sans",
    "ar_color": "#FFFFFF", "tr_color": "#FFFFFF", "ref_color": "#D9D9D9",
    "outline_color": "#000000", "shadow_color": "#000000", "shadow_alpha": "80",
    "ar_size": 0.10,                 # Arabic letter size, fraction of min(width, height)
    "tr_ratio": 0.42,                # translation size relative to the Arabic
    "max_words_per_line": 7,
    "break_at_waqf": False,          # end a line at a pause mark (ۚ ۖ ۗ …) when one is near
    "center_y": 0.55,                # vertical centre of the caption (0 top … 1 bottom)
    "outline": 3, "shadow": 2, "bold": False, "fade_ms": 250,
    "show_translation": False, "show_reference": True, "ref_y": 0.07,
    "box": False, "box_color": "#000000", "box_opacity": 0.5, "box_radius": 0.03,
    "sync_offset": 0.0,              # seconds; negative shows captions earlier
    # ── look & motion ──
    "anim": "fade",                  # see ANIMS
    "hl_color": "#FFD54A",           # recited / active word (karaoke, highlight, glow_word)
    "upcoming_alpha": 0.45,          # karaoke: opacity of words not recited yet
    "glow": False, "glow_color": "", "glow_size": 1.0,   # soft light behind the letters ("" = hl_color)
    "band": False, "band_color": "#000000", "band_opacity": 0.7,   # cinematic gradient band
    "card_border": False, "border_color": "#B8860B",    # mushaf-page double border on the box
    "ornament": False, "ornament_color": "#D4AF37",     # thin lines with a diamond above/below
    "brackets": "full",              # full: ﴿ … ٢﴾ | number: … ﴿٢﴾ | none
    "tr_italic": False,
}

# line animations (the whole line) and word animations (follow the recitation)
ANIMS = ("fade", "slide_up", "zoom_in", "blur_in", "karaoke", "highlight", "word_reveal", "glow_word")
WORD_ANIMS = ("karaoke", "highlight", "word_reveal", "glow_word")
BRACKETS = ("full", "number", "none")

USER_OPTIONS = ("ar_font", "tr_font", "ar_color", "tr_color", "ref_color", "outline_color",
                "ar_size", "tr_ratio", "center_y", "max_words_per_line", "break_at_waqf",
                "show_translation", "show_reference", "box", "box_color", "box_opacity", "box_radius",
                "sync_offset", "anim", "hl_color", "glow", "band", "ornament", "brackets", "outline")

PUBLIC_KEYS = ("label", "label_ar", "description", "description_ar")


# ───────────────────────────── styles ─────────────────────────────
def _load_style_files() -> dict:
    out = {}
    for f in sorted(STYLES_DIR.glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue                    # a broken file must never take the app down
    return out


def all_styles(extra: dict = None) -> dict:
    out = {k: {**DEFAULTS, **v} for k, v in _load_style_files().items()}
    for k, v in (extra or {}).items():
        out[k] = {**DEFAULTS, **out.get(k, {}), **(v or {})}
    if not out:
        out["classic"] = dict(DEFAULTS, label="Classic", label_ar="كلاسيكي")
    return dict(sorted(out.items(), key=lambda kv: (kv[1].get("sort", 99), kv[0])))


# extra look keys sent to the browser so the style cards and preview match the video
PREVIEW_KEYS = ("glow_color", "upcoming_alpha", "card_border", "border_color", "ornament_color", "tr_italic", "shadow")


def list_styles(extra: dict = None) -> list:
    return [{"id": k, **{p: v.get(p, "") for p in PUBLIC_KEYS},
             "options": {o: v.get(o) for o in USER_OPTIONS + PREVIEW_KEYS}} for k, v in all_styles(extra).items()]


def _b(v) -> bool:
    return v in (True, "true", "1", 1, "on")


def resolve_style(style_id: str, overrides: dict = None, extra: dict = None, fonts: list = None) -> dict:
    styles = all_styles(extra)
    st = dict(styles.get(style_id) or styles.get("classic") or next(iter(styles.values())))
    for k, v in (overrides or {}).items():
        if k in USER_OPTIONS and v is not None and v != "":
            st[k] = v
    clamp = lambda k, lo, hi: min(max(float(st[k]), lo), hi)
    st["ar_size"] = clamp("ar_size", 0.04, 0.18)
    st["tr_ratio"] = clamp("tr_ratio", 0.25, 0.8)
    st["center_y"] = clamp("center_y", 0.15, 0.85)
    st["box_opacity"] = clamp("box_opacity", 0.0, 1.0)
    st["box_radius"] = clamp("box_radius", 0.0, 0.1)
    st["max_words_per_line"] = int(min(max(int(st["max_words_per_line"]), 1), 15))
    st["sync_offset"] = clamp("sync_offset", -1.5, 1.5)
    st["outline"] = clamp("outline", 0, 10)
    st["glow_size"] = clamp("glow_size", 0.2, 3.0)
    st["upcoming_alpha"] = clamp("upcoming_alpha", 0.0, 1.0)
    st["band_opacity"] = clamp("band_opacity", 0.0, 1.0)
    if st["anim"] not in ANIMS:
        st["anim"] = "fade"
    if st["brackets"] not in BRACKETS:
        st["brackets"] = "full"
    for k in ("show_translation", "show_reference", "box", "break_at_waqf", "bold", "glow", "band",
              "card_border", "ornament", "tr_italic"):
        st[k] = _b(st[k])
    if fonts is not None:              # only fonts that really exist and render
        ar = [f["family"] for f in fonts if f["script"] == "arabic"]
        la = [f["family"] for f in fonts if f["script"] == "latin" or f.get("latin")]
        if st["ar_font"] not in ar and ar:
            st["ar_font"] = "Amiri" if "Amiri" in ar else ar[0]
        if st["tr_font"] not in la and la:
            st["tr_font"] = "DejaVu Sans" if "DejaVu Sans" in la else la[0]
    return st


# ───────────────────────────── fonts ─────────────────────────────
def _family(path) -> str:
    from fontTools.ttLib import TTFont
    return TTFont(str(path), lazy=True)["name"].getDebugName(1)


@lru_cache(maxsize=64)
def font_file(family: str, fonts_dir: str):
    """Regular file of a family in fonts_dir (shortest name wins: X-Regular over X-Bold)."""
    hits = []
    for f in Path(fonts_dir).glob("*.[ot]tf"):
        try:
            if _family(f) == family:
                hits.append(f)
        except Exception:
            continue
    hits.sort(key=lambda p: (("bold" in p.name.lower()), len(p.name)))
    return str(hits[0]) if hits else None


def _libass_renders(family: str, fonts_dir: str) -> bool:
    """The font must really draw Arabic in ffmpeg's subtitle renderer: isolated
    letters (nominal glyphs) and joined ones. A broken font draws every letter as
    the same box, so two different texts come out (almost) identical."""
    tmp = Path(tempfile.mkdtemp(prefix="fontchk_"))
    try:
        imgs = []
        for i, txt in enumerate(("ب ر ا ببب", "ح ز و ححح")):
            ass = tmp / f"{i}.ass"
            ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 600\nPlayResY: 160\n\n[V4+ Styles]\n"
                           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                           "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                           "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                           f"Style: A,{family},100,&H00FFFFFF&,&H000000FF&,&H00000000&,&H00000000&,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,-1\n\n"
                           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                           f"Dialogue: 0,0:00:00.00,0:00:01.00,A,,0,0,0,,{txt}\n", encoding="utf-8-sig")
            out = tmp / f"{i}.gray"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=600x160:d=1",
                            "-vf", f"ass={ass.name}:fontsdir='{Path(fonts_dir).resolve().as_posix()}':shaping=complex",
                            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", out.name],
                           cwd=str(tmp), capture_output=True, timeout=60)
            imgs.append(out.read_bytes() if out.exists() else b"")
        a, b = imgs
        if not a or not b:
            return False
        lit = sum(1 for x in a if x > 128)
        diff = sum(1 for x, y in zip(a, b) if (x > 128) != (y > 128))
        return lit > 30 and diff > 0.25 * lit
    except Exception:
        return False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# Uthmani (Mushaf) script: alef wasla, small high marks, rounded sukun, pause marks
QURAN_MARKS = [0x0671, 0x0670, 0x06E1, 0x06E2, 0x0653, 0x06DF, 0x06E5, 0x06E6, 0x06D6, 0x06D7, 0x06DA]
# standard ("simple") Quran script: ordinary tashkeel + dagger alef + madda + hamza
SIMPLE_MARKS = list(range(0x064B, 0x0653)) + [0x0670, 0x0653, 0x0654]

# Arabic names / kind shown in the font picker (any other font shows its own name)
FONT_INFO = {
    "Amiri Quran": ("أميري قرآن", "naskh"), "Amiri": ("أميري", "naskh"),
    "Scheherazade New": ("شهرزاد", "naskh"), "Noto Naskh Arabic": ("نوتو نسخ", "naskh"),
    "Noto Sans Arabic": ("نوتو سانس", "sans"), "Noto Kufi Arabic": ("نوتو كوفي", "kufi"),
    "Jomhuria": ("جمهورية", "display"), "Aref Ruqaa": ("عارف رقعة", "ruqaa"),
    "Reem Kufi": ("ريم كوفي", "kufi"), "Kufam": ("كوفام", "kufi"), "Changa": ("تشانجا", "kufi"),
    "Lalezar": ("لاله زار", "display"), "Rakkas": ("رقّاص", "display"), "Lemonada": ("ليمونادة", "display"),
    "Marhey": ("مرحي", "display"), "Cairo": ("القاهرة", "sans"), "Tajawal": ("تجوّل", "sans"),
    "Readex Pro": ("ريدكس", "sans"), "El Messiri": ("المسيري", "naskh"), "Markazi Text": ("مركزي", "naskh"),
    "Mirza": ("ميرزا", "naskh"), "Katibeh": ("كاتبة", "display"), "Vibes": ("فايبز", "display"),
}


def _font_info(path, fam: str, cm: dict, fonts_dir: str) -> dict:
    latin = 0x41 in cm and 0x7A in cm
    if fam not in ("DejaVu Sans",) and 0x0627 in cm and all(c in cm for c in SIMPLE_MARKS) and _libass_renders(fam, fonts_dir):
        name_ar, kind = FONT_INFO.get(fam, (fam, "other"))
        return {"family": fam, "script": "arabic", "quran_ok": all(c in cm for c in QURAN_MARKS),
                "name_ar": name_ar, "kind": kind, "latin": latin}
    return {"family": fam, "script": "latin" if latin else "none", "quran_ok": False, "latin": latin}


def text_script(font: dict) -> str:
    """Which published Quran text a font can show: the full Uthmani script, or
    the standard ("simple") script for display fonts without the Uthmani marks."""
    return "uthmani" if (font or {}).get("quran_ok") else "simple"


def check_font_file(path) -> dict:
    """{family, script: arabic|latin|none, quran_ok, ...} for one uploaded font file."""
    import shutil
    from fontTools.ttLib import TTFont
    tt = TTFont(str(path), lazy=True)
    fam = tt["name"].getDebugName(1) or Path(path).stem
    cm = tt.getBestCmap() or {}
    tmp = Path(tempfile.mkdtemp(prefix="fontone_"))
    try:
        shutil.copy(path, tmp / Path(path).name)
        return _font_info(path, fam, cm, str(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def available_fonts(fonts_dir, cache_dir=None) -> list:
    """[{family, script: arabic|latin, quran_ok, name_ar, kind, file}] — Arabic fonts
    are kept only if they render in libass. Results are cached per file."""
    from fontTools.ttLib import TTFont
    fonts_dir = Path(fonts_dir)
    cache_f = Path(cache_dir) / "fonts2.json" if cache_dir else None
    cache = {}
    if cache_f and cache_f.exists():
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    out, seen, changed = [], set(), False
    for f in sorted(fonts_dir.glob("*.[ot]tf")):
        key = f"{f.name}:{f.stat().st_size}:{int(f.stat().st_mtime)}"
        info = cache.get(key)
        if info is None:
            try:
                tt = TTFont(str(f), lazy=True)
                fam = tt["name"].getDebugName(1)
                info = _font_info(f, fam, tt.getBestCmap() or {}, str(fonts_dir))
            except Exception:
                info = {"family": f.stem, "script": "none"}
            cache[key] = info
            changed = True
        if info["script"] != "none" and info["family"] not in seen:
            seen.add(info["family"])
            out.append({**info, "file": f.name})
    if changed and cache_f:
        try:
            cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    order = list(FONT_INFO)
    out.sort(key=lambda x: (x["script"] != "arabic", not x.get("quran_ok"),
                            order.index(x["family"]) if x["family"] in order else 99, x["family"]))
    for x in out:
        x["file"] = Path(font_file(x["family"], str(fonts_dir)) or x["file"]).name
    return out


@lru_cache(maxsize=32)
def cell_factor(family: str, fonts_dir: str) -> float:
    """libass sizes text by the font's cell height (win ascent+descent), not the
    em — Amiri's cell is ~2.76 em, DejaVu's ~1.16. Convert so every font gets the
    same visual size for the same setting."""
    f = font_file(family, fonts_dir)
    if f:
        try:
            from fontTools.ttLib import TTFont
            t = TTFont(f, lazy=True)
            o, upm = t["OS/2"], t["head"].unitsPerEm
            return max(1.0, (o.usWinAscent + o.usWinDescent) / upm)
        except Exception:
            pass
    return 1.2


@lru_cache(maxsize=16)
def _hb_font(path: str):
    import uharfbuzz as hb
    face = hb.Face(hb.Blob.from_file_path(path))
    return hb.Font(face), face.upem


@lru_cache(maxsize=8192)
def width_em(text: str, family: str, fonts_dir: str) -> float:
    """Width of one line in em, shaped exactly as libass will shape it (HarfBuzz)."""
    f = font_file(family, fonts_dir)
    if f:
        try:
            import uharfbuzz as hb
            font, upem = _hb_font(f)
            buf = hb.Buffer()
            buf.add_str(text)
            buf.guess_segment_properties()
            hb.shape(font, buf, {})
            return sum(p.x_advance for p in buf.glyph_positions) / upem
        except Exception:
            pass
        try:
            from PIL import ImageFont, features
            if features.check("raqm"):
                pf = ImageFont.truetype(f, 200, layout_engine=ImageFont.Layout.RAQM)
                return pf.getlength(text, direction="rtl") / 200.0
        except Exception:
            pass
    return len(text) * 0.45


# ───────────────────────────── ASS helpers ─────────────────────────────
def _hex_to_ass(hex_color: str, alpha: str = "00") -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        h = "FFFFFF"
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}&"


def _t2a(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ").strip()


def _rounded_rect(x0, y0, x1, y1, r) -> str:
    r = max(0, min(int(r), (x1 - x0) // 2, (y1 - y0) // 2))
    if r == 0:
        return f"m {x0} {y0} l {x1} {y0} {x1} {y1} {x0} {y1}"
    return (f"m {x0 + r} {y0} l {x1 - r} {y0} b {x1} {y0} {x1} {y0} {x1} {y0 + r} "
            f"l {x1} {y1 - r} b {x1} {y1} {x1} {y1} {x1 - r} {y1} "
            f"l {x0 + r} {y1} b {x0} {y1} {x0} {y1} {x0} {y1 - r} "
            f"l {x0} {y0 + r} b {x0} {y0} {x0} {y0} {x0 + r} {y0}")


def _digits(n: int) -> str:
    return "".join("٠١٢٣٤٥٦٧٨٩"[int(d)] for d in str(n))


def _frame(words: list, ayah: int, last: bool) -> str:
    """One display line, framed with the ornate brackets; the ayah number sits in the last one."""
    body = " ".join(words) + (f" {_digits(ayah)}" if last and ayah else "")
    return f"\uFD3F{body}\uFD3E"


def split_lines(words: list, ayah: int, max_words: int, fits=None, break_at_waqf: bool = False) -> list:
    """Exactly max_words per line (the last line gets the rest); an ayah with
    max_words words or fewer is one line. Width never removes words — the font
    is scaled for that ayah instead. Optional: end a line early at a pause mark
    (only when that line still keeps at least half of max_words)."""
    lines, i, n = [], 0, len(words)
    max_words = max(1, int(max_words))
    while i < n:
        j = min(i + max_words, n)
        if break_at_waqf and j < n:
            for k in range(j - 1, i, -1):            # last pause mark in the line
                if sync.has_waqf(words[k]) and (k - i + 1) >= max(2, (max_words + 1) // 2):
                    j = k + 1
                    break
        lines.append(words[i:j])
        i = j
    return lines


# ───────────────────────────── generator ─────────────────────────────
def _alpha_hex(opacity: float) -> str:
    return f"{int(round(255 * (1 - min(max(opacity, 0.0), 1.0)))):02X}"


def _line_tokens(words: list, ayah: int, last: bool, brackets: str) -> list:
    """Display tokens of one line (one per Quran word); the ornate brackets and
    the ayah number are attached to the first/last word so they move with them."""
    toks = list(words)
    num = _digits(ayah) if ayah else ""
    if brackets == "full":
        toks[0] = "﴿" + toks[0]
        if last and num:
            toks[-1] = toks[-1] + " " + num
        toks[-1] = toks[-1] + "﴾"
    elif brackets == "number" and last and num:
        toks[-1] = toks[-1] + " ﴿" + num + "﴾"
    return toks


def _word_starts(words: list, t_on: float, t_off: float, voice_on: float, given: list = None) -> list:
    """Recitation time of every word of one line: from word alignment when known,
    else spread over the line by how long each word takes to recite."""
    if given and len(given) == len(words):
        out = [min(max(t, t_on), t_off - 0.05) for t in given]
        for i in range(1, len(out)):
            out[i] = max(out[i], out[i - 1] + 0.04)
        return out
    a = min(max(voice_on, t_on), t_off - 0.1)
    span = max(0.1, (t_off - 0.15) - a)
    wts = [sync.word_weight(w) for w in words]
    tot = sum(wts) or 1.0
    out, acc = [], 0.0
    for w in wts:
        out.append(a + span * acc / tot)
        acc += w
    return out


def _markup(tokens: list, rel: list, end_ms: int, st: dict, layer: str, c: dict) -> str:
    """ASS text of one line with per-word animation tags (rel = word start, ms
    from the event start). layer "text" = the letters, "glow" = the light behind them."""
    anim = st["anim"]
    out = []
    for i, tok in enumerate(tokens):
        a = max(0, int(rel[i]))
        b = int(rel[i + 1]) if i + 1 < len(rel) else end_ms + 10_000   # the last word stays lit
        txt = _esc(tok)
        if layer == "glow":
            if anim in ("karaoke", "word_reveal"):
                tag = f"\\alpha&HFF&\\t({a},{a + 160},\\alpha&H{c['glow_a']}&)"
            elif anim in ("highlight", "glow_word"):
                tag = f"\\alpha&HFF&\\t({a},{a + 120},\\alpha&H{c['glow_a']}&)\\t({b},{b + 160},\\alpha&HFF&)"
            else:
                tag = ""
        elif anim == "karaoke":
            tag = (f"\\1c{c['ar']}\\1a&H{c['up_a']}&\\3a&H{c['up_a']}&"
                   f"\\t({a},{a + 120},\\1c{c['hl']}\\1a&H00&\\3a&H00&)")
        elif anim == "highlight":
            tag = f"\\1c{c['ar']}\\t({a},{a + 100},\\1c{c['hl']})\\t({b},{b + 140},\\1c{c['ar']})"
        elif anim == "word_reveal":
            tag = (f"\\alpha&HFF&\\blur6\\t({a},{a + 220},\\1a&H00&\\3a&H00&"
                   f"\\4a&H{c['sh_a']}&\\blur0)")
        elif anim == "glow_word":
            big, bl = c["out"] + c["halo"], max(2, c["halo"] * 0.8)
            tag = (f"\\1c{c['ar']}\\t({a},{a + 110},\\1c{c['hl']}\\3c{c['hl3']}\\bord{big}\\blur{bl:.0f})"
                   f"\\t({b},{b + 160},\\1c{c['ar']}\\3c{c['outc']}\\bord{c['out']}\\blur0)")
        else:
            tag = ""
        out.append(f"{{{tag}}}{txt}" if tag else txt)
    return " ".join(out)


def _ornament(cx: int, y: int, half: int, size: int) -> str:
    """Two thin lines with a diamond in the middle (vector drawing)."""
    d, g, h = size, size * 2, max(1, size // 4)
    return (f"m {cx} {y - d} l {cx + d} {y} {cx} {y + d} {cx - d} {y} "
            f"m {cx + g} {y - h} l {cx + half} {y - h} {cx + half} {y + h} {cx + g} {y + h} "
            f"m {cx - g} {y - h} l {cx - g} {y + h} {cx - half} {y + h} {cx - half} {y - h}")


def generate_quran_ass(timed_ayahs: list, out_path, W: int, H: int, style: dict, fonts_dir) -> Path:
    st = {**DEFAULTS, **style}
    fonts_dir = str(fonts_dir)
    unit = min(W, H)
    AF, TF = st["ar_font"], st["tr_font"]
    cf_ar, cf_tr = cell_factor(AF, fonts_dir), cell_factor(TF, fonts_dir)
    ar_em = unit * float(st["ar_size"])
    avail = W * 0.92
    OUT, SHA, FADE = int(round(float(st["outline"]))), int(st["shadow"]), int(st["fade_ms"])
    AR_C, TR_C, REF_C = (_hex_to_ass(st[k]) for k in ("ar_color", "tr_color", "ref_color"))
    OUT_C = _hex_to_ass(st["outline_color"])
    SHAD_C = _hex_to_ass(st["shadow_color"], st["shadow_alpha"])
    HL_C = _hex_to_ass(st["hl_color"])
    GLOW_C = _hex_to_ass(st["glow_color"] or st["hl_color"])
    BOLD = 1 if st["bold"] else 0
    CX, CY = W // 2, int(H * float(st["center_y"]))
    REF_Y = int(H * float(st["ref_y"]))
    MARGIN = int(W * 0.06)
    ref_fs = round(max(unit * 0.03, 20) * cf_tr)
    MWL = int(st["max_words_per_line"])
    ANIM = st["anim"]
    colors = {"ar": AR_C, "hl": HL_C, "hl3": GLOW_C, "outc": OUT_C, "out": OUT,
              "up_a": _alpha_hex(float(st["upcoming_alpha"])), "glow_a": "50",
              "sh_a": str(st["shadow_alpha"]).upper()[:2], "halo": max(3, int(ar_em * 0.06))}
    fits = lambda line: width_em(line, AF, fonts_dir) * ar_em <= avail

    events = []
    spans = []
    for p in timed_ayahs:
        start, end = p.get("start"), p.get("end")
        if start is None or end is None or end <= start:
            continue
        ayah = int(p.get("ayah") or 0)
        plain = sync.quran_words(p.get("ar_plain") or (p.get("ar") or "").replace("﴿", " ").replace("﴾", " "))
        if not plain:
            continue
        spans.append((start, end))
        lines = split_lines(plain, ayah, MWL, fits, st["break_at_waqf"])
        toks = [_line_tokens(ln, ayah, i == len(lines) - 1, st["brackets"]) for i, ln in enumerate(lines)]
        texts = [" ".join(t) for t in toks]
        wt = p.get("word_times")
        wt = wt if wt and len(wt) == len(plain) else None
        times = sync.line_times(lines, start, end, p.get("speech"), wt)

        # one font size for the whole ayah: the user's size, smaller only if a
        # line is wider than the frame
        widest = max(width_em(tx, AF, fonts_dir) for tx in texts)
        em = min(ar_em, avail / widest) if widest else ar_em
        ar_fs = round(em * cf_ar)

        tr_text = (p.get("translation") or "").strip() if st["show_translation"] else ""
        tr_em = ar_em * float(st["tr_ratio"])
        tr_n = 0
        if tr_text:
            tr_w = width_em(tr_text, TF, fonts_dir)
            while True:                                  # at most 3 translation lines
                tr_n = max(1, -(-int(tr_w * tr_em * 1.15) // int(W - 2 * MARGIN)))
                if tr_n <= 3 or tr_em < unit * 0.018:
                    break
                tr_em *= 0.92
        tr_fs = round(tr_em * cf_tr)
        ar_h = em * 1.75
        gap = tr_em * 0.8 if tr_text else 0
        tr_h = tr_n * tr_em * 1.35
        top = CY - (ar_h + gap + tr_h) / 2
        ar_bottom = int(top + ar_h)
        tr_top = int(ar_bottom + gap)
        content_w = max(widest * em, min(width_em(tr_text, TF, fonts_dir) * tr_em, W - 2 * MARGIN) if tr_text else 0)

        if st["box"]:
            pad_x, pad_y = int(unit * 0.045), int(unit * 0.03 + em * 0.25)
            bw = min(W * 0.96, content_w + 2 * pad_x)
            bx0, bx1 = int(CX - bw / 2), int(CX + bw / 2)
            by0, by1 = int(top - pad_y), int(top + ar_h + gap + tr_h + pad_y)
            box_a = _alpha_hex(float(st["box_opacity"]))
            rad = unit * st["box_radius"]
            events.append(f"Dialogue: 0,{_t2a(start)},{_t2a(end)},QAR,,0,0,0,,"
                          f"{{\\an7\\pos(0,0)\\1c{_hex_to_ass(st['box_color'])}\\1a&H{box_a}&\\bord0\\shad0\\blur1"
                          f"\\fad({FADE},{FADE})\\p1}}{_rounded_rect(bx0, by0, bx1, by1, rad)}{{\\p0}}")
            if st["card_border"]:                       # mushaf page: thick + thin inner frame
                bc = _hex_to_ass(st["border_color"])
                for inset, th in ((int(unit * 0.012), max(2, unit // 300)), (int(unit * 0.022), 1)):
                    events.append(f"Dialogue: 0,{_t2a(start)},{_t2a(end)},QAR,,0,0,0,,"
                                  f"{{\\an7\\pos(0,0)\\1a&HFF&\\3c{bc}\\bord{th}\\shad0\\fad({FADE},{FADE})\\p1}}"
                                  f"{_rounded_rect(bx0 + inset, by0 + inset, bx1 - inset, by1 - inset, max(0, rad - inset))}{{\\p0}}")

        if st["ornament"]:
            oc = _hex_to_ass(st["ornament_color"])
            half = int(min(W * 0.42, max(content_w * 0.55, unit * 0.18)))
            size = max(4, int(unit * 0.009))
            for y in (int(top - em * 0.45), int(top + ar_h + gap + tr_h + em * 0.35)):
                events.append(f"Dialogue: 0,{_t2a(start)},{_t2a(end)},QAR,,0,0,0,,"
                              f"{{\\an7\\pos(0,0)\\1c{oc}\\bord0\\shad0\\blur0.6\\fad({FADE},{FADE})\\p1}}"
                              f"{_ornament(CX, y, half, size)}{{\\p0}}")

        last = len(texts) - 1
        k = 0
        voice0 = float((p.get("speech") or {}).get("start", start))
        for i, (tk, (t_on, t_off)) in enumerate(zip(toks, times)):
            n = len(tk)
            given = wt[k:k + n] if wt else None
            k += n
            # never still fading in when the voice starts
            v0 = voice0 if i == 0 else t_on + sync.LEAD
            fi = int(min(FADE, max(40, (v0 - t_on) * 1000 - 40))) if i == 0 else 90
            fo = FADE if i == last else 110
            t_end = t_off if i == last else t_off + 0.11      # short cross-fade into the next line
            dur_ms = int((t_end - t_on) * 1000)
            rel = [(t - t_on) * 1000 for t in _word_starts(lines[i], t_on, t_off, v0, given)] \
                if ANIM in WORD_ANIMS or st["glow"] else [0] * n
            # whole-line entrance
            ent, pos = "", f"\\pos({CX},{ar_bottom})"
            if ANIM == "slide_up":
                dy = int(em * 0.45)
                pos = f"\\move({CX},{ar_bottom + dy},{CX},{ar_bottom},0,{max(fi, 260)})"
            elif ANIM == "zoom_in":
                ent = f"\\fscx82\\fscy82\\t(0,{max(fi, 280)},0.6,\\fscx100\\fscy100)"
            elif ANIM == "blur_in":
                ent = f"\\blur14\\t(0,{max(fi, 320)},\\blur0)"
            base = (f"\\an2{pos}\\fn{AF}\\fs{ar_fs}\\b{BOLD}\\q2\\fad({fi},{fo}){ent}")
            if st["glow"]:
                gb = max(4, int(em * 0.10 * float(st["glow_size"])))
                events.append(f"Dialogue: 1,{_t2a(t_on)},{_t2a(t_end)},QAR,,{MARGIN},{MARGIN},0,,"
                              f"{{{base}\\1c{GLOW_C}\\3c{GLOW_C}\\1a&H{colors['glow_a']}&\\3a&H{colors['glow_a']}&"
                              f"\\bord{gb}\\shad0\\blur{gb}}}"
                              f"{_markup(tk, rel, dur_ms, st, 'glow', colors)}")
            events.append(f"Dialogue: 2,{_t2a(t_on)},{_t2a(t_end)},QAR,,{MARGIN},{MARGIN},0,,"
                          f"{{{base}\\1c{AR_C}\\3c{OUT_C}\\4c{SHAD_C}\\bord{OUT}\\shad{SHA}}}"
                          f"{_markup(tk, rel, dur_ms, st, 'text', colors)}")

        if tr_text:
            ital = 1 if st["tr_italic"] else 0
            ovr = (f"{{\\an8\\pos({CX},{tr_top})\\fn{TF}\\fs{tr_fs}\\b0\\i{ital}\\1c{TR_C}\\3c{OUT_C}\\4c{SHAD_C}"
                   f"\\bord{max(OUT - 1, 0)}\\shad{SHA}\\fad({FADE},{FADE})}}")
            events.append(f"Dialogue: 2,{_t2a(start)},{_t2a(end)},QTR,,{MARGIN},{MARGIN},0,,{ovr}{_esc(tr_text)}")

        ref = (p.get("ref") or "").strip()
        if st["show_reference"] and ref:
            ovr = (f"{{\\an8\\pos({CX},{REF_Y})\\fn{TF}\\fs{ref_fs}\\b0\\1c{REF_C}\\3c{OUT_C}\\4c{SHAD_C}"
                   f"\\bord2\\shad1\\fad({FADE},{FADE})}}")
            events.append(f"Dialogue: 2,{_t2a(start)},{_t2a(end)},QREF,,{MARGIN},{MARGIN},0,,{ovr}{_esc(ref)}")

    if st["band"] and spans:                           # cinematic band: soft dark gradient, whole video
        t0, t1 = min(a for a, _ in spans), max(b for _, b in spans)
        bh = int(min(H * 0.6, ar_em * (4.2 if st["show_translation"] else 3.0)))
        y0, N = CY - bh // 2, 36
        bc = _hex_to_ass(st["band_color"])
        import math
        for j in range(N):
            a = float(st["band_opacity"]) * math.sin(math.pi * (j + 0.5) / N) ** 1.2
            ya, yb = y0 + bh * j // N, y0 + bh * (j + 1) // N + 1
            events.append(f"Dialogue: 0,{_t2a(t0)},{_t2a(t1)},QAR,,0,0,0,,"
                          f"{{\\an7\\pos(0,0)\\1c{bc}\\1a&H{_alpha_hex(a)}&\\bord0\\shad0\\fad(400,400)\\p1}}"
                          f"m 0 {ya} l {W} {ya} {W} {yb} 0 {yb}{{\\p0}}")

    base = round(ar_em * cf_ar)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: QAR,{AF},{base},{AR_C},&H000000FF&,{OUT_C},{SHAD_C},{BOLD},0,0,0,100,100,0,0,1,{OUT},{SHA},5,10,10,10,-1
Style: QTR,{TF},{round(base * 0.4)},{TR_C},&H000000FF&,{OUT_C},{SHAD_C},0,0,0,0,100,100,0,0,1,{max(OUT - 1, 0)},{SHA},5,10,10,10,-1
Style: QREF,{TF},{ref_fs},{REF_C},&H000000FF&,{OUT_C},{SHAD_C},0,0,0,0,100,100,0,0,1,2,1,8,10,10,10,-1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    out_path = Path(out_path)
    out_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out_path


if os.getenv("CAPTION_RESHAPE") == "1":    # very old ffmpeg builds without HarfBuzz
    try:
        import arabic_reshaper as _ar
        _rs = _ar.ArabicReshaper(configuration={"delete_harakat": False, "support_ligatures": True})
        _orig_esc = _esc
        _esc = lambda text: _orig_esc(_rs.reshape(text))  # noqa: E731
    except ImportError:
        pass
