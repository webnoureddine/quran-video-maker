"""
watermark.py — logo / channel WATERMARK (moved unchanged from viral_fx.py;
the rule-card part of that module was removed with the other non-Quran features).

apply_watermark(video_in, cfg, log, frame=None) burns the logo into the video in place.
cfg keys: see DEF_WM (position tl|tc|tr|bl|bc|br|c|custom, size_pct, opacity, blend, tint,
shadow, glow, fade, show always|intro_outro|interval ...).
"""
import json, shutil, subprocess
from pathlib import Path
import numpy as np
from PIL import Image


def _hex(c):
    c = (c or "#000000").lstrip("#")
    if len(c) == 3: c = "".join(x * 2 for x in c)
    try: return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception: return (0, 0, 0)

def _clamp(x, a=0.0, b=1.0): return a if x < a else b if x > b else x

def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                        "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return dict(w=int(v.get("width") or 0), h=int(v.get("height") or 0),
                dur=float((j.get("format") or {}).get("duration") or 0),
                audio=any(s.get("codec_type") == "audio" for s in j.get("streams", [])))

# ───────────────────────── public: watermark ─────────────────────────
DEF_WM = dict(enabled=False, path="", position="br", margin_pct=3.0, x_pct=50.0, y_pct=50.0, size_pct=14.0,
              opacity=0.85, blend="normal",           # normal|screen|multiply|softlight|overlay|lighten|addition
              tint="none", tint_color="#FFFFFF", tint_strength=0.4,   # none|auto|color
              shadow=True, glow=False, fade=0.6, show="always",       # always|intro_outro|interval
              show_secs=6.0, hide_secs=14.0, on_long=True, on_shorts=True)
_NEUTRAL = {"normal": None, "screen": 0, "addition": 0, "lighten": 0, "multiply": 255, "softlight": 128, "overlay": 128}

def _logo_layer(cfg, W, H, vid_color, box=None, inset=0):
    im = Image.open(cfg["path"]).convert("RGBA")
    bx0, by0, bx1, by1 = box or (0, 0, W, H); bw, bh = bx1 - bx0, by1 - by0
    w = max(8, int(bw * float(cfg["size_pct"]) / 100)); h = max(8, int(im.height * w / im.width))
    im = im.resize((w, h), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32)
    tint = cfg["tint"]; ts = float(cfg["tint_strength"])
    if tint in ("auto", "color") and ts > 0:
        tc = np.array(vid_color if tint == "auto" else _hex(cfg["tint_color"]), np.float32)
        if tint == "auto":                      # lift the average video colour so the logo stays readable
            tc = tc + (255 - tc) * 0.45
        arr[..., :3] = arr[..., :3] * (1 - ts) + tc * ts
    im = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")
    pos = cfg["position"]; m = int(min(bw, bh) * float(cfg["margin_pct"]) / 100)
    mc = m + (inset if pos in ("tl", "tr", "bl", "br") else 0)       # clear the rounded corner
    mt = m + (inset // 2 if pos in ("tc", "bc") else 0)
    x = {"tl": bx0 + mc, "bl": bx0 + mc, "tr": bx1 - w - mc, "br": bx1 - w - mc,
         "tc": bx0 + (bw - w) // 2, "bc": bx0 + (bw - w) // 2, "c": bx0 + (bw - w) // 2}.get(pos)
    y = {"tl": by0 + mc, "tr": by0 + mc, "tc": by0 + mt, "bl": by1 - h - mc, "br": by1 - h - mc, "bc": by1 - h - mt,
         "c": by0 + (bh - h) // 2}.get(pos)
    if x is None: x = int(bx0 + bw * float(cfg["x_pct"]) / 100 - w / 2); y = int(by0 + bh * float(cfg["y_pct"]) / 100 - h / 2)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    from PIL import ImageFilter
    if cfg["shadow"] and cfg["blend"] == "normal":
        sh = Image.new("RGBA", im.size, (0, 0, 0, 255)); sh.putalpha(im.getchannel("A").point(lambda v: int(v * 0.55)))
        big = Image.new("RGBA", (W, H), (0, 0, 0, 0)); big.paste(sh, (x + max(2, w // 40), y + max(2, w // 40)), sh)
        layer = Image.alpha_composite(layer, big.filter(ImageFilter.GaussianBlur(max(2, w // 45))))
    if cfg["glow"]:
        gl = Image.new("RGBA", im.size, (255, 255, 255, 255)); gl.putalpha(im.getchannel("A").point(lambda v: int(v * 0.6)))
        big = Image.new("RGBA", (W, H), (0, 0, 0, 0)); big.paste(gl, (x, y), gl)
        layer = Image.alpha_composite(layer, big.filter(ImageFilter.GaussianBlur(max(3, w // 18))))
    top = Image.new("RGBA", (W, H), (0, 0, 0, 0)); top.paste(im, (x, y), im)
    return Image.alpha_composite(layer, top)

def apply_watermark(video_in, cfg, log=print, is_short=False, frame=None):
    """Burn the logo into video_in (in place). Returns the path. No-op when disabled / missing."""
    cfg = {**DEF_WM, **(cfg or {})}
    if not cfg["enabled"] or not cfg["path"] or not Path(cfg["path"]).exists(): return video_in
    if is_short and not cfg["on_shorts"]: return video_in
    if (not is_short) and not cfg["on_long"]: return video_in
    vp = Path(video_in); info = _probe(vp); W, H, dur = info["w"], info["h"], info["dur"]
    tmp = vp.with_name(vp.stem + "_wm_tmp.mp4"); work = vp.parent
    try:
        # average colour of the video (one frame from the middle) for auto-tint
        fr = work / "_wm_frame.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{dur / 2:.2f}", "-i", str(vp), "-frames:v", "1",
                        "-vf", "scale=32:32", str(fr)], check=True)
        vc = tuple(np.asarray(Image.open(fr).convert("RGB")).reshape(-1, 3).mean(0)); fr.unlink()
        box, inset = None, 0
        if frame:                                   # rounded-frame mode: position inside the video box, not the canvas
            pad = max(0, int(frame.get("padding", 30))); pady = frame.get("padding_y"); pady = pad if pady is None else max(0, int(pady))
            box = (pad, pady, W - pad, H - pady); inset = int(float(frame.get("radius", 40)) * 0.29)
        layer = _logo_layer(cfg, W, H, vc, box, inset); lp = work / "_wm_layer.png"
        blend = cfg["blend"] if cfg["blend"] in _NEUTRAL else "normal"; neutral = _NEUTRAL[blend]
        if neutral is not None:
            bg = Image.new("RGBA", (W, H), (neutral, neutral, neutral, 255)); layer = Image.alpha_composite(bg, layer)
        layer.save(lp)
        f = float(cfg["fade"]); op = _clamp(float(cfg["opacity"]))
        en = {"always": "1",
              "intro_outro": f"lt(t,{cfg['show_secs']})+gt(t,{max(0.0, dur - float(cfg['show_secs']))})",
              "interval": f"lt(mod(t,{float(cfg['show_secs']) + float(cfg['hide_secs'])}),{cfg['show_secs']})"}.get(cfg["show"], "1")
        en = f"enable='{en}'"
        if neutral is None:
            chain = "format=rgba" + (f",fade=t=in:st=0:d={f}:alpha=1,fade=t=out:st={max(0, dur - f):.2f}:d={f}:alpha=1" if f > 0 else "") \
                    + f",colorchannelmixer=aa={op}"
            fc = f"[1:v]{chain}[wm];[0:v][wm]overlay=0:0:{en}:shortest=1,format=yuv420p[v]"
        else:
            col = "0x%02x%02x%02x" % (neutral, neutral, neutral)
            chain = "format=gbrp" + (f",fade=t=in:st=0:d={f}:color={col},fade=t=out:st={max(0, dur - f):.2f}:d={f}:color={col}" if f > 0 else "")
            fc = f"[0:v]format=gbrp[b];[1:v]{chain}[wm];[b][wm]blend=all_mode={blend}:all_opacity={op}:{en}:shortest=1,format=yuv420p[v]"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vp), "-loop", "1", "-framerate", "30", "-i", str(lp),
                            "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(tmp)],
                           capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError((r.stderr or "")[-400:])
        shutil.move(str(tmp), str(vp)); log(f"  Watermark applied ({blend}, {cfg['position']}) -> {vp.name}")
    except Exception as e:
        log(f"  Watermark skipped: {e}")
        try: tmp.unlink()
        except Exception: pass
    finally:
        for f in (work / "_wm_layer.png", work / "_wm_frame.png"):
            try: f.unlink()
            except Exception: pass
    return video_in
