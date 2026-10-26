"""
engine.py — Make Quran Video render engine.

Runs as its own process (python -m app.engine --job job.json) so a render
can be cancelled cleanly and never blocks the web server.

Pipeline (one aya = one caption = one background scene):
  1. recitation audio  -> voice.m4a (loudness-normalised to TARGET_LUFS)
  2. per-aya timing    -> EXACT (sidecar from the reciter download) or
                          silence-gap segmentation (uploaded recitation)
  3. background track  -> the user's chosen library/uploaded images & videos
                          (single item for the whole video, or one per aya, cycling)
  4. mux               -> background + recitation ONLY (no music, no SFX)
  5. Quran captions    -> ASS from the chosen caption style, burned in
  6. rounded frame     -> optional padded rounded-corner card
  7. watermark         -> optional logo
  8. size cap          -> re-encode under OUTPUT_LIMIT_MB if needed

The timing, Quran caption, encoder and rounded-frame functions are carried
over unchanged from the original VideoStudio engine.

Progress lines for the server:  @@PROGRESS <0-100> <stage>
A failure the user should see:   @@ERROR <message key> <json params>   (see app/i18n.py)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import captions as CAP          # noqa: E402
from app import sync                     # noqa: E402
from app import watermark as WM          # noqa: E402

# Settings the carried-over functions read (they used the old global CONFIG).
CONFIG = {
    "bilingual_hold_seconds": 0.9,
    "bilingual_end_padding": 0.18,
    "bilingual_min_phrase_base": 0.3,
    "bilingual_min_sec_per_word": 0.28,
    "quran_caption_lead": 0.0,
    "image_width": 1920,
    "image_height": 1080,
}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")


class UserError(Exception):
    """A problem the user can fix — shown translated in the UI (key from app/i18n.py)."""

    def __init__(self, key, **params):
        self.key, self.params = key, params
        super().__init__(key)


def progress(pct: int, stage: str):
    print(f"@@PROGRESS {int(pct)} {stage}", flush=True)


_VENC_CACHE = None

# ═════════════════════ carried over from the original engine ═════════════════════
def log(msg: str):
    try:
        print(f"[pipeline] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(f"[pipeline] {safe}", flush=True)


def run(cmd: list, check=True, **kwargs) -> subprocess.CompletedProcess:
    log(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if check and result.returncode != 0:
        print(result.stderr[-3000:], file=sys.stderr)
        raise RuntimeError(f"Command failed: {cmd[0]}")
    return result


def _hw_encoder():
    """Detect ONCE a working GPU H.264 encoder (NVIDIA NVENC / Intel QSV / AMD AMF); None -> CPU libx264.
    Force CPU with the env var VIDEO_HWENC=cpu."""
    global _VENC_CACHE
    if _VENC_CACHE is not None:
        return _VENC_CACHE or None
    _VENC_CACHE = ""
    if os.getenv("VIDEO_HWENC", "auto").lower() in ("0", "off", "no", "false", "cpu", "x264"):
        return None
    try:
        listing = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    for name in ("h264_nvenc", "h264_qsv", "h264_amf"):
        if name not in listing:
            continue
        try:   # an encoder that is merely compiled in may still have no GPU behind it -> test-encode 0.2 s
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2:r=24",
                                "-c:v", name, "-pix_fmt", "yuv420p", "-f", "null", "-"], capture_output=True, timeout=40)
            if r.returncode == 0:
                _VENC_CACHE = name
                log(f"[speed] GPU video encoder detected: {name} (set VIDEO_HWENC=cpu to disable)")
                return name
        except Exception:
            pass
    return None


def _venc(crf: int = 18, preset: str = "veryfast") -> list:
    """ffmpeg video-encoder arguments: GPU encoder when available, otherwise libx264 with the given preset/crf."""
    name = _hw_encoder()
    q = str(int(crf) + 2)
    if name == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", q, "-b:v", "0"]
    if name == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", q]
    if name == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", q, "-qp_p", q]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(int(crf))]


def _get_audio_duration(audio_path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)])
    return float(r.stdout.strip())


def detect_speech_segments(audio_path, silence_db: float = -35.0, min_silence: float = 0.35) -> list:
    """
    Find speech (non-silent) segments in `audio_path` using ffmpeg's
    silencedetect filter. Returns a chronologically ordered list of
    (start, end) tuples. This is used instead of ASR transcription to find
    phrase boundaries in bilingual mode — it doesn't care what language is
    spoken, only where the reader pauses, which is far more reliable for
    code-switched English/Arabic audio than trying to get Whisper to
    transcribe both languages correctly in one pass.
    """
    dur = _get_audio_duration(audio_path)
    r = run(["ffmpeg", "-i", str(audio_path), "-af",
             f"silencedetect=noise={silence_db}dB:d={min_silence}",
             "-f", "null", "-"], check=False)
    stderr = r.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", stderr)]
    ends   = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", stderr)]
    n = min(len(starts), len(ends))
    silences = list(zip(starts[:n], ends[:n]))

    speech = []
    cursor = 0.0
    for s0, s1 in silences:
        if s0 > cursor:
            speech.append((cursor, s0))
        cursor = max(cursor, s1)
    if cursor < dur:
        speech.append((cursor, dur))
    speech = [(round(a, 3), round(b, 3)) for a, b in speech if b - a >= 0.08]
    return speech


def _detect_speech_segments_auto(audio_path, target_n: int) -> list:
    """Try a few silencedetect sensitivities and keep whichever gets closest
    to the expected number of phrase segments."""
    attempts = [(-35.0, 0.35), (-30.0, 0.25), (-25.0, 0.15), (-40.0, 0.5), (-20.0, 0.12)]
    best = None
    for db, minsil in attempts:
        segs = detect_speech_segments(audio_path, silence_db=db, min_silence=minsil)
        log(f"  silencedetect(noise={db}dB, d={minsil}s) -> {len(segs)} speech segment(s)")
        if len(segs) == target_n:
            return segs
        if best is None or abs(len(segs) - target_n) < abs(len(best) - target_n):
            best = segs
    return best or [(0.0, _get_audio_duration(audio_path))]


def _force_segment_count(segments: list, target_n: int) -> list:
    """
    Best-effort reconciliation when the detected number of speech segments
    doesn't match the number of phrases expected. Merges the closest-together
    segments if there are too many (the reader's pause was too short there to
    register as a break, or there's a stray blip), or splits the longest
    segment in half if there are too few. Order is always preserved, so
    pairs can never end up out of order or overlapping.
    """
    segs = [list(s) for s in segments] or [[0.0, 1.0]]
    while len(segs) > target_n and len(segs) > 1:
        gaps = [(segs[i + 1][0] - segs[i][1], i) for i in range(len(segs) - 1)]
        _, i = min(gaps)
        segs[i][1] = segs[i + 1][1]
        del segs[i + 1]
    while len(segs) < target_n:
        durations = [(b - a, i) for i, (a, b) in enumerate(segs)]
        _, i = max(durations)
        a, b = segs[i]
        mid = (a + b) / 2
        segs[i:i + 1] = [[a, mid], [mid, b]]
    return [tuple(s) for s in segs]


def _min_phrase_seconds(text: str) -> float:
    """Rough floor on how long a phrase of this length plausibly takes to
    read aloud, used to keep bilingual captions from vanishing early if a
    detected speech segment came out too short."""
    words = len((text or "").split())
    if not words:
        return 0.0
    return CONFIG.get("bilingual_min_phrase_base", 0.3) + words * CONFIG.get("bilingual_min_sec_per_word", 0.28)


def _arabic_letter_count(text: str) -> int:
    """Number of base Arabic letters (diacritics, ornate brackets and digits
    excluded) — a far better proxy for how long an aya takes to recite than
    its word count."""
    n = sum(1 for ch in (text or "") if "\u0621" <= ch <= "\u064A" or ch == "\u0671")
    return max(n, 1)


def _group_segments_by_weight(segments: list, weights: list) -> list:
    """
    Too many speech segments were detected (reciters breathe INSIDE long
    ayat, which silencedetect reports as extra segments). Instead of
    merging the closest-together segments blindly, choose which gaps are
    the real aya boundaries: the n-1 cuts whose position in the speech
    best matches the cumulative length of the ayat (letter count), with a
    bonus for longer pauses. Order is preserved.
    """
    m, n = len(segments), len(weights)
    if n <= 1:
        return [(segments[0][0], segments[-1][1])]
    if m <= n:
        return segments
    cs, acc = [], 0.0
    for a, b in segments:
        acc += (b - a)
        cs.append(acc)
    total = cs[-1]
    W = float(sum(weights))
    targets, cw = [], 0.0
    for w in weights[:-1]:
        cw += w
        targets.append(total * cw / W)
    gap_len = [segments[g + 1][0] - segments[g][1] for g in range(m - 1)]
    GAP_BONUS = 2.0
    INF = float("inf")

    def cost(j, g):
        return abs(cs[g] - targets[j]) - GAP_BONUS * min(gap_len[g], 1.5)

    G = m - 1
    prev_cost = [cost(0, g) for g in range(G)]
    back = []
    for j in range(1, n - 1):
        cur = [INF] * G
        ptr = [-1] * G
        best, best_i = INF, -1
        for g in range(G):
            if g > 0 and prev_cost[g - 1] < best:
                best, best_i = prev_cost[g - 1], g - 1
            if best_i >= 0:
                cur[g] = best + cost(j, g)
                ptr[g] = best_i
        back.append(ptr)
        prev_cost = cur
    g = min(range(G), key=lambda x: prev_cost[x])
    cuts = [g]
    for ptr in reversed(back):
        g = ptr[g]
        cuts.append(g)
    cuts.reverse()
    out, start_idx = [], 0
    for g in cuts:
        out.append((segments[start_idx][0], segments[g][1]))
        start_idx = g + 1
    out.append((segments[start_idx][0], segments[-1][1]))
    return out


def compute_quran_ayah_timings_exact(pairs: list, timings_file, total_duration: float) -> list:
    """
    Exact aya timing from the sidecar written by quran_api.download_and_concat_reciter_audio
    (the per-aya speech onset/offset inside the assembled audio is known
    precisely — no silence guessing). Each caption appears slightly BEFORE
    the reciter starts (so the fade-in is complete when the voice begins) and
    stays up until the next aya's caption takes over; the last one stays to
    the end of the audio.
    """
    data = json.loads(Path(timings_file).read_text(encoding="utf-8"))
    by_key = {(int(t["surah"]), int(t["ayah"])): t for t in data}
    LEAD = CONFIG.get("quran_caption_lead", 0.0)  # must be > fade-in so the caption is fully visible when the voice starts
    starts, offs = [], []
    for p in pairs:
        t = by_key.get((int(p["surah"]), int(p["ayah"])))
        if t is None:
            raise ValueError(f"no exact timing for {p['surah']}:{p['ayah']} in {timings_file}")
        starts.append(float(t["start"]))
        offs.append(float(t["end"]))
    if any(starts[i + 1] <= starts[i] for i in range(len(starts) - 1)):
        raise ValueError("exact timings are not in increasing order")
    cap_starts = []
    for i, s0 in enumerate(starts):
        cs = max(0.0, s0 - LEAD)
        if cap_starts:
            cs = max(cs, cap_starts[-1] + 0.1)
        cap_starts.append(cs)
    timed = []
    for i, p in enumerate(pairs):
        end = (cap_starts[i + 1] - 0.02) if i + 1 < len(pairs) else max(total_duration, offs[i])
        item = dict(p)
        item["start"] = round(cap_starts[i], 3)
        item["end"]   = round(max(end, cap_starts[i] + 0.1), 3)
        item["speech_start"] = round(starts[i], 3)
        item["speech_end"]   = round(offs[i], 3)
        timed.append(item)
    return timed


def compute_quran_ayah_timings(pairs: list, audio_path) -> list:
    """
    Assign real start/end times to each aya using silence-gap speech
    segmentation (one speech segment per aya — the reciter's natural pause
    between verses), the same technique bilingual mode uses for phrase
    pairs. Unlike bilingual mode, the translation is silent text (nobody
    reads it aloud), so each aya only ever consumes ONE segment, not one
    per line.

    `pairs` is a list of dicts: {"surah": int, "ayah": int, "ar": str,
    "translation": str|None, "ref": str|None}. Returns the same dicts with
    "start"/"end" (float seconds) added.
    """
    HOLD    = CONFIG.get("bilingual_hold_seconds", 0.9)
    END_PAD = CONFIG.get("bilingual_end_padding", 0.18)
    target_n = len(pairs)

    segments = _detect_speech_segments_auto(audio_path, target_n)
    if len(segments) != target_n:
        log(f"WARNING: Quran mode expected {target_n} speech segment(s) (one per aya, split at "
            f"pauses) but detected {len(segments)}. Reconciling automatically by merging/splitting "
            f"— for best accuracy, leave a clear pause between each aya when recording/trimming.")
        if len(segments) > target_n:
            weights = [_arabic_letter_count(p.get("ar_plain") or p.get("ar") or "") for p in pairs]
            segments = _group_segments_by_weight(segments, weights)
            log(f"  grouped into {len(segments)} aya(s) using aya length (letter count) as a guide")
        else:
            segments = _force_segment_count(segments, target_n)

    padded = []
    for idx, (a, b) in enumerate(segments):
        next_start = segments[idx + 1][0] if idx + 1 < len(segments) else b + END_PAD + 1
        padded.append((a, max(min(b + END_PAD, next_start - 0.05), a + 0.05)))
    segments = padded

    timed: list = []
    for p, (start, end) in zip(pairs, segments):
        min_end = start + _min_phrase_seconds(p.get("ar", ""))
        end = max(end, min_end) + HOLD
        item = dict(p)
        item["start"] = round(start, 3)
        item["end"]   = round(end, 3)
        timed.append(item)

    for i in range(len(timed) - 1):
        nxt_start = timed[i + 1]["start"]
        floor = timed[i]["start"] + 0.05
        timed[i]["end"] = max(min(timed[i]["end"], nxt_start - 0.05), floor)

    return timed


def _quran_scenes_from_timings(timed_ayahs: list, total_duration: float = None) -> list:
    """
    Build the `scenes` list Quran mode's background/clip-matching step needs.
    One scene per aya, using the translation as the background-matching
    query text. Scenes are CONTIGUOUS and cover the whole audio — the first
    starts at 0 and the last runs past the end of the audio (the final mux
    trims it) — so the background track can never be shorter than the
    recitation (which would clip the end of the audio via -shortest) and a
    background cut lands exactly where the caption changes. A very short
    aya (<2s) is merged into the previous scene.
    """
    n = len(timed_ayahs)
    tail = 0.6
    scenes = []
    for i, p in enumerate(timed_ayahs):
        seg_start = 0.0 if i == 0 else p["start"]
        if i + 1 < n:
            seg_end = timed_ayahs[i + 1]["start"]
        else:
            seg_end = (total_duration if total_duration else p["end"]) + tail
        query = (p.get("translation") or p.get("ar_plain") or p.get("ar") or "").strip()
        dur = seg_end - seg_start
        if dur < 2.0 and scenes:
            scenes[-1]["words"]    += " " + query
            scenes[-1]["end_time"]  = seg_end
            scenes[-1]["duration"]  = round(seg_end - scenes[-1]["start_time"], 3)
        else:
            scenes.append({
                "id": len(scenes), "words": query,
                "start_time": round(seg_start, 3), "end_time": round(seg_end, 3),
                "duration":   round(dur, 3),
            })
    log(f"Quran mode: {len(scenes)} background scene(s) from {n} aya(s) "
        f"(contiguous, total {sum(sc['duration'] for sc in scenes):.1f}s)")
    return scenes


def _hex_to_ffmpeg_color(hex_color: str) -> str:
    """'#1a1a2e' -> '0x1a1a2e' (ffmpeg color= syntax). Passes through
    non-hex values (e.g. 'black', 'red') unchanged."""
    h = (hex_color or "").strip()
    if h.startswith("#"):
        return "0x" + h[1:]
    return h or "0x000000"


def generate_round_mask_png(width: int, height: int, radius: int, save_path) -> str:
    """White rounded rectangle on transparent background — used as an
    alpha mask so a clip's corners can be cut into rounded corners."""
    from PIL import Image, ImageDraw
    width, height, radius = max(2, int(width)), max(2, int(height)), max(0, int(radius))
    radius = min(radius, width // 2, height // 2)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, width - 1, height - 1], radius=radius, fill=(255, 255, 255, 255))
    img.save(str(save_path))
    return str(save_path)


def apply_rounded_frame(
    video_path,
    output_path,
    width: int = None,
    height: int = None,
    corner_radius: int = 40,
    padding: int = 30,
    padding_y: int = None,
    bg_color: str = "#1a1a2e",
    bg_image: str = None,
    shadow_enabled: bool = False,
    shadow_blur: int = 30,
    shadow_opacity: float = 0.55,
    shadow_offset: int = 12,
):
    """
    Shrinks the video into a padded rounded-rect 'card' and drops it on a
    solid/branded background. The video fills the card completely (cropped
    to the card's aspect ratio, no letterbox bars inside it) — same visual
    idea as the rounded-mask frame used for the long-form YouTube export,
    kept self-contained here so it can be applied to any clip (long video
    or a short) at any point in the pipeline.

    video_path / output_path: Path-like
    width / height: canvas size — defaults to CONFIG["image_width"/"image_height"]
    """
    video_path  = Path(video_path)
    output_path = Path(output_path)
    W = int(width  or CONFIG["image_width"])
    H = int(height or CONFIG["image_height"])
    padding  = max(0, int(padding))
    pad_y    = max(0, int(padding_y)) if padding_y is not None else padding
    iw, ih   = max(2, W - padding * 2), max(2, H - pad_y * 2)
    work_dir = output_path.parent

    use_image_bg = bool(bg_image) and Path(bg_image).exists()

    log(f"Applying rounded frame: canvas={W}x{H} inner={iw}x{ih} "
        f"radius={corner_radius} padding={padding}/{pad_y} "
        f"shadow={'on' if shadow_enabled else 'off'} "
        + (f"bg_image={bg_image}" if use_image_bg else f"bg={bg_color}"))

    mask_png = generate_round_mask_png(iw, ih, corner_radius, work_dir / "_frame_mask.png")

    parts = []
    # [0:v] = source video, [1:v] = rounded-rect alpha mask
    # force_original_aspect_ratio=increase + crop fills the whole iw x ih box
    # with no black bars — excess is cropped from the center instead.
    parts.append(
        f"[0:v]scale={iw}:{ih}:force_original_aspect_ratio=increase,"
        f"crop={iw}:{ih},format=rgba[inner]"
    )
    parts.append(f"[1:v]format=rgba[mk]")
    parts.append("[inner][mk]alphamerge[card]")

    inputs = ["-i", str(video_path), "-i", mask_png]

    if use_image_bg:
        # Background is a still image, cover-cropped to fill the full canvas
        # (same fill logic as the video card) instead of a flat color.
        inputs += ["-loop", "1", "-i", str(bg_image)]
        parts.append(
            f"[2:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},format=rgba[bg]"
        )
    else:
        ffmpeg_bg = _hex_to_ffmpeg_color(bg_color)
        parts.append(f"color=c={ffmpeg_bg}:s={W}x{H}:r=30,format=rgba[bg]")

    if shadow_enabled:
        # Blur needs headroom beyond the mask's own canvas to bleed outward,
        # so pad the mask before blurring, then overlay it under the card,
        # offset slightly down, to fake a soft drop shadow.
        shadow_margin = max(4, int(shadow_blur * 3))
        parts.append(
            f"[1:v]format=rgba,"
            f"pad=w={iw + shadow_margin * 2}:h={ih + shadow_margin * 2}:"
            f"x={shadow_margin}:y={shadow_margin}:color=0x00000000,"
            f"colorchannelmixer=rr=0:gg=0:bb=0:aa={shadow_opacity},"
            f"gblur=sigma={shadow_blur}[shadow]"
        )
        shx = padding - shadow_margin
        shy = pad_y - shadow_margin + shadow_offset
        parts.append(f"[bg][shadow]overlay={shx}:{shy}:format=auto[bg_sh]")
        parts.append(f"[bg_sh][card]overlay={padding}:{pad_y}:format=auto[vout]")
    else:
        parts.append(f"[bg][card]overlay={padding}:{pad_y}:format=auto[vout]")

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", "0:a?",
        *_venc(18, "veryfast"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    run(cmd)
    log(f"✅ Rounded frame applied -> {output_path}")
    return output_path


# ═════════════════════════════ Make Quran Video ═════════════════════════════

def prepare_audio(audio_in, work: Path, target_lufs: float) -> Path:
    """Recitation -> voice.m4a. Loudness-normalised so every video plays at
    the same level (timing is unchanged — loudnorm doesn't shift samples)."""
    out = work / "voice.m4a"
    af = ["-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"] if target_lufs else []
    r = run(["ffmpeg", "-y", "-i", str(audio_in), "-vn", *af, "-ar", "44100", "-ac", "2",
             "-c:a", "aac", "-b:a", "192k", str(out)], check=False)
    if r.returncode != 0 or not out.exists():
        raise UserError("audio_unreadable")
    return out


def _media_kind(path) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    raise UserError("bg_unsupported", name=Path(path).name)


def _media_duration(path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], check=False)
    try:
        return max(0.0, float(r.stdout.strip()))
    except ValueError:
        return 0.0


def _render_segment(item: dict, out_path: Path, W: int, H: int, fps: int, duration: float,
                    offset: float, motion: bool, fade_in: bool):
    """One background piece of exactly `duration` seconds, cover-fitted to WxH
    (never letterboxed), silent, constant fps — so all pieces concat losslessly."""
    path, kind = item["path"], item["kind"]
    frames = max(1, int(round(duration * fps)))
    fade = ",fade=t=in:st=0:d=0.6" if fade_in else ""
    if kind == "image":
        if motion:
            # slow Ken Burns zoom; up-scale first so zoompan doesn't jitter
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                  f"zoompan=z='1+0.07*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps}")
        else:
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}"
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(path),
               "-vf", vf + f",setsar=1,format=yuv420p{fade}", "-frames:v", str(frames)]
    else:
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(path), "-an",
               "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},setsar=1,format=yuv420p{fade}",
               "-frames:v", str(frames)]
    cmd += [*_venc(18, "veryfast"), "-pix_fmt", "yuv420p", "-r", str(fps), "-video_track_timescale", "90000", str(out_path)]
    r = run(cmd, check=False)
    if r.returncode != 0 or not out_path.exists():
        raise UserError("bg_broken", name=item.get("name") or Path(path).name)


def build_background_track(scenes: list, media: list, mode: str, W: int, H: int, fps: int,
                           work: Path, motion: bool = True) -> Path:
    """Replaces the old AI / stock / Pinterest / clip-matching background step:
    only the media the user picked from the library or uploaded is used.
      single -> the first item fills the whole video (a video loops)
      multi  -> one item per aya scene, cycling through the selection in order;
                each video continues where it left off instead of restarting."""
    if not media:
        raise UserError("bg_required")
    for m in media:
        m["kind"] = m.get("kind") or _media_kind(m["path"])
        if not Path(m["path"]).exists():
            raise UserError("media_gone")
    total = sum(s["duration"] for s in scenes)
    if mode != "multi" or len(media) == 1:
        plan = [(media[0], total)]
    else:
        plan, k = [], 0
        for s in scenes:
            item = media[k % len(media)]
            k += 1
            if plan and plan[-1][0] is item:
                plan[-1] = (item, plan[-1][1] + s["duration"])
            else:
                plan.append((item, s["duration"]))
    cursors, parts = {}, []
    for i, (item, dur) in enumerate(plan):
        off = 0.0
        if item["kind"] == "video":
            d = item.setdefault("_dur", _media_duration(item["path"]))
            off = cursors.get(id(item), 0.0) % d if d > 0.5 else 0.0
            cursors[id(item)] = off + dur
        part = work / f"bg_{i:03d}.mp4"
        _render_segment(item, part, W, H, fps, dur, off, motion, fade_in=(i == 0))
        parts.append(part)
        progress(12 + int(46 * (i + 1) / len(plan)), "backgrounds")
    if len(parts) == 1:
        return parts[0]
    lst = work / "bg_list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    out = work / "background.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out.name], cwd=str(work))
    for p in parts:
        p.unlink(missing_ok=True)
    return out


def mux_recitation(bg: Path, voice: Path, duration: float, out: Path) -> Path:
    """Background + recitation. The recitation is the ONLY audio track."""
    run(["ffmpeg", "-y", "-i", str(bg), "-i", str(voice), "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "copy", "-t", f"{duration:.3f}", str(out)])
    return out


def burn_captions(video: Path, ass_path: Path, fonts_dir: Path, out: Path) -> Path:
    """Burn the Quran captions. Each style line names its own font, and every
    font in fonts/ is visible to libass. shaping=complex makes libass shape Arabic
    with HarfBuzz (OpenType joining, marks, Quranic ligatures); the `subtitles`
    filter's default "simple" shaping maps letters to legacy presentation forms,
    which most modern Arabic fonts do not contain (they render as boxes)."""
    work = video.parent
    local_ass = work / "captions.ass"
    if ass_path.resolve() != local_ass.resolve():
        shutil.copy(ass_path, local_ass)
    font_str = str(Path(fonts_dir).resolve()).replace("\\", "/").replace(":", "\\:")
    run(["ffmpeg", "-y", "-i", video.name, "-vf", f"ass=captions.ass:fontsdir='{font_str}':shaping=complex",
         *_venc(18, "veryfast"), "-pix_fmt", "yuv420p", "-c:a", "copy", out.name], cwd=str(work))
    return out


def cap_file_size(video: Path, limit_mb: float, duration: float) -> Path:
    if not limit_mb or video.stat().st_size <= limit_mb * 1024 * 1024:
        return video
    audio_kbps = 160
    v_kbps = int(limit_mb * 8 * 1024 * 0.92 / max(duration, 1) - audio_kbps)
    v_kbps = max(v_kbps, 300)
    log(f"Output is {video.stat().st_size / 1048576:.1f} MB > {limit_mb} MB — re-encoding at {v_kbps} kb/s")
    out = video.with_name(video.stem + "_sized.mp4")
    run(["ffmpeg", "-y", "-i", str(video), "-c:v", "libx264", "-preset", "medium", "-b:v", f"{v_kbps}k",
         "-maxrate", f"{int(v_kbps * 1.2)}k", "-bufsize", f"{v_kbps * 2}k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", f"{audio_kbps}k", str(out)])
    return out


CAPTION_LEAD = 0.30   # a caption is fully faded in when the reciter starts (fade-in is 0.25 s)


def _align_to_voice(timed: list, env, duration: float, offset: float = 0.0, voice=None):
    """Lock every caption to the moment the reciter's voice actually says its first word.

    1. word-level alignment (speech recognition + the exact Quran words, app/align.py):
       every word gets its recitation time; an ayah starts at its first word.
    2. each word time is snapped to the true sound onset found in the audio (the end
       of the silence just before it) — recognition timestamps can be off by ~0.2 s.
    3. fallback when recognition is unavailable: the rough ayah windows (exact CDN
       timings or pause detection), refined with the loudness envelope.
    A caption is fully faded in CAPTION_LEAD before its first word; `offset` is the
    user's fine-tune (negative = earlier)."""
    ratio = 0.0
    if voice is not None:
        try:
            from app import align
            ratio = align.word_times(timed, voice, duration)
            log(f"Word alignment: {ratio:.0%} of Quran words recognised")
        except ImportError:
            log("Word alignment unavailable (faster-whisper not installed) — using pause detection")
        except Exception as e:
            log(f"Word alignment failed ({e!r}) — using pause detection")
    use_words = ratio >= 0.35 and all(p.get("word_times") for p in timed)
    if not use_words:
        for p in timed:
            p.pop("word_times", None)

    # silences of the whole recording, to snap onsets precisely
    pauses = sync.speech_map(env, 0.0, duration)["pauses"]

    def snap(t):
        best = None
        for a, b in pauses:
            if t - 0.35 <= b <= t + 0.25 and (best is None or abs(b - t) < abs(best - t)):
                best = b
        return best if best is not None else t

    if use_words:
        for p in timed:
            p["word_times"] = [snap(t) for t in p["word_times"]]
        for i, p in enumerate(timed):
            p["start"] = p["word_times"][0]
            p["end"] = timed[i + 1]["word_times"][0] if i + 1 < len(timed) else duration
    prev_end = 0.0
    for p in timed:
        a = max(float(p["start"]) - (0.05 if use_words else 0.6), prev_end + 0.02, 0.0)
        p["speech"] = sync.speech_map(env, a, max(a + 0.1, float(p["end"])))
        if use_words:
            p["speech"]["start"] = p["word_times"][0]       # the first word, snapped to its onset
        prev_end = p["speech"]["end"]
    for i, p in enumerate(timed):
        st = p["speech"]["start"] - CAPTION_LEAD
        if i > 0:
            st = max(st, timed[i - 1]["speech"]["end"] + 0.03, timed[i - 1]["start"] + 0.3)
        p["start"] = max(0.0, st)
    for i in range(len(timed) - 1):
        timed[i]["end"] = timed[i + 1]["start"]
    timed[-1]["end"] = max(float(timed[-1]["end"]), timed[-1]["speech"]["end"] + 0.5)
    if offset:
        for p in timed:
            if p.get("word_times"):
                p["word_times"] = [max(0.0, t + offset) for t in p["word_times"]]
            p["start"] = max(0.0, p["start"] + offset)
            p["end"] = min(duration + 0.5, max(p["start"] + 0.2, p["end"] + offset))
            sp = p["speech"]
            sp["start"], sp["end"] = sp["start"] + offset, sp["end"] + offset
            sp["pauses"] = [(x + offset, y + offset) for x, y in sp["pauses"]]
            if p.get("word_times"):
                p["word_times"] = [t + offset for t in p["word_times"]]


def render(job: dict) -> Path:
    work = Path(job["work_dir"]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    out_final = Path(job["output"]).resolve()
    W, H = int(job.get("width", 1920)) // 2 * 2, int(job.get("height", 1080)) // 2 * 2
    fps = int(job.get("fps", 30))
    CONFIG["image_width"], CONFIG["image_height"] = W, H
    pairs = job["pairs"]
    if not pairs:
        raise UserError("no_ayah")

    progress(2, "recitation")
    voice = prepare_audio(job["audio"], work, float(job.get("target_lufs", -14)))
    duration = _get_audio_duration(voice)
    max_s = float(job.get("max_audio_seconds") or 0)
    if max_s and duration > max_s:
        raise UserError("too_long_audio", dur=f"{duration / 60:.1f}", max=f"{max_s / 60:.0f}")

    progress(6, "sync")
    timed = None
    tf = job.get("timings_file")
    if tf and Path(tf).exists():
        try:
            # the exact timings were measured on the source file; loudnorm keeps the timeline
            timed = compute_quran_ayah_timings_exact(pairs, tf, duration)
            log("Exact per-aya timings used.")
        except Exception as e:
            log(f"Exact timings unusable ({e}) — using pause detection.")
    if timed is None:
        timed = compute_quran_ayah_timings(pairs, voice)
    # where the reciter really speaks and pauses inside each ayah (line-level sync)
    env = sync.envelope(voice)
    style = job.get("caption_style") or CAP.resolve_style("classic")
    _align_to_voice(timed, env, duration, float(style.get("sync_offset") or 0), voice=voice)
    (work / "timings_used.json").write_text(json.dumps(timed, ensure_ascii=False, indent=1), encoding="utf-8")

    progress(10, "backgrounds")
    scenes = _quran_scenes_from_timings(timed, total_duration=duration)
    bg = build_background_track(scenes, job.get("backgrounds") or [], job.get("bg_mode", "single"),
                                W, H, fps, work, motion=bool(job.get("bg_motion", True)))

    progress(60, "mux")
    video = mux_recitation(bg, voice, duration, work / "with_audio.mp4")

    progress(66, "captions")
    fonts_dir = Path(job.get("fonts_dir") or Path(__file__).resolve().parent.parent / "fonts")
    ass = CAP.generate_quran_ass(timed, work / "captions.ass", W, H, style, fonts_dir)
    video = burn_captions(video, ass, fonts_dir, work / "captioned.mp4")

    frame = job.get("frame") or {}
    if frame.get("enabled"):
        progress(82, "frame")
        video = apply_rounded_frame(
            video, work / "framed.mp4", width=W, height=H,
            corner_radius=int(frame.get("radius", 40)), padding=int(frame.get("padding", 30)),
            padding_y=frame.get("padding_y"), bg_color=frame.get("bg_color", "#1a1a2e"),
            bg_image=frame.get("bg_image") or None,
            shadow_enabled=bool(frame.get("shadow", False)), shadow_blur=int(frame.get("shadow_blur", 30)),
            shadow_opacity=float(frame.get("shadow_opacity", 0.55)), shadow_offset=int(frame.get("shadow_offset", 12)))

    wm = job.get("watermark") or {}
    if wm.get("enabled") and wm.get("path"):
        progress(90, "watermark")
        frame_box = None
        if frame.get("enabled"):
            frame_box = {"padding": int(frame.get("padding", 30)), "padding_y": frame.get("padding_y"),
                         "radius": int(frame.get("radius", 40))}
        WM.apply_watermark(video, wm, log=log, frame=frame_box)

    progress(95, "finalising")
    video = cap_file_size(video, float(job.get("output_limit_mb") or 0), duration)
    out_final.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_final.with_suffix(".part.mp4")
    run(["ffmpeg", "-y", "-i", str(video), "-c", "copy", "-movflags", "+faststart", str(tmp)])
    tmp.replace(out_final)
    progress(100, "done")
    return out_final


def main():
    ap = argparse.ArgumentParser(description="Make Quran Video render engine")
    ap.add_argument("--job", required=True, type=Path, help="job description JSON")
    ap.add_argument("--keep-work", action="store_true", help="don't delete the work folder (debugging)")
    a = ap.parse_args()
    job = json.loads(a.job.read_text(encoding="utf-8"))
    code = 0
    try:
        out = render(job)
        log(f"Done -> {out}")
    except UserError as e:
        print(f"@@ERROR {e.key} {json.dumps(e.params, ensure_ascii=False)}", flush=True)
        code = 1
    except Exception:  # unexpected: full trace in the server log, generic message for the user
        traceback.print_exc()
        print("@@ERROR render_failed {}", flush=True)
        code = 1
    finally:
        if not a.keep_work:
            shutil.rmtree(job["work_dir"], ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
