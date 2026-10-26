"""
quran_api.py — thin client for the public alquran.cloud Quran API.

No API key needed. Used by the Quran-video mode to:
  1. fetch the Arabic text (+ an optional translation) for a surah/ayah range
     and shape it into the "pairs" list the render engine
     expects: [{"surah", "ayah", "ar", "translation", "ref"}, ...]
  2. optionally fetch the reciter's audio for that same range and concatenate
     it into one file, with a short silence inserted between each aya so the
     engine's silence-gap segmentation (compute_quran_ayah_timings) has a
     clean pause to lock onto even if the source clips are trimmed tight.

Docs: https://alquran.cloud/api
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BASE = "https://api.alquran.cloud/v1"
CDN_AYAH_AUDIO = "https://cdn.islamic.network/quran/audio/{bitrate}/{edition}/{global_ayah}.mp3"

DEFAULT_ARABIC_EDITION = "quran-uthmani"

# A short curated list for the UI — the live API has many more; see
# list_editions() for the full set.
RECITERS = [
    {"id": "ar.alafasy",          "name": "Mishary Alafasy", "name_ar": "مشاري العفاسي"},
    {"id": "ar.husary",           "name": "Mahmoud Al-Husary", "name_ar": "محمود خليل الحصري"},
    {"id": "ar.abdulbasitmurattal", "name": "Abdul Basit (Murattal)", "name_ar": "عبد الباسط عبد الصمد (مرتل)"},
    {"id": "ar.minshawi",         "name": "Mohamed Al-Minshawi", "name_ar": "محمد صديق المنشاوي"},
    {"id": "ar.hudhaify",         "name": "Ali Al-Hudhaify", "name_ar": "علي الحذيفي"},
    {"id": "ar.muhammadayyoub",   "name": "Muhammad Ayyoub", "name_ar": "محمد أيوب"},
    {"id": "ar.mahermuaiqly",     "name": "Maher Al-Muaiqly", "name_ar": "ماهر المعيقلي"},
    {"id": "ar.abdurrahmaansudais", "name": "Abdur-Rahman As-Sudais", "name_ar": "عبد الرحمن السديس"},
]

TRANSLATIONS = [
    {"id": "en.sahih",      "name": "English — Saheeh International", "name_ar": "الإنجليزية — صحيح انترناشونال", "lang": "en"},
    {"id": "en.pickthall",  "name": "English — Pickthall", "name_ar": "الإنجليزية — بيكثال",            "lang": "en"},
    {"id": "en.yusufali",   "name": "English — Yusuf Ali", "name_ar": "الإنجليزية — يوسف علي",            "lang": "en"},
    {"id": "fr.hamidullah", "name": "Français — Hamidullah", "name_ar": "الفرنسية — حميد الله",          "lang": "fr"},
]


class QuranAPIError(RuntimeError):
    pass


_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def to_arabic_indic_numerals(n: int) -> str:
    """'12' -> '١٢' (Eastern Arabic-Indic digits, as used inside a Mushaf's
    end-of-ayah marker)."""
    return "".join(_ARABIC_INDIC_DIGITS[int(d)] for d in str(n))


def ayah_end_sign(n: int) -> str:
    """The traditional end-of-ayah marker on its own: the ayah number in
    Arabic-Indic numerals wrapped in ornate Quranic parentheses (﴿ ﴾).
    Kept as a standalone helper for callers that just want the marker
    (not a full wrapped-and-framed aya) — see wrap_ayah_text for how
    lines are framed end to end."""
    return f"\uFD3F{to_arabic_indic_numerals(n)}\uFD3E"


DEFAULT_MAX_WORDS_PER_LINE = 7
_ORNATE_OPEN  = "\uFD3F"   # ﴿ — opens a line (rightmost glyph, RTL)
_ORNATE_CLOSE = "\uFD3E"   # ﴾ — closes a line (leftmost glyph, RTL)


def wrap_ayah_text(ar_plain: str, ayah_number: int, max_words: int = DEFAULT_MAX_WORDS_PER_LINE) -> str:
    """Break an aya into hard lines of at most `max_words` words each
    (real '\\n' characters, not just a rendering hint) — and frame every
    line with the ornate ﴿ ﴾ marks at both ends, matching the classic
    Quranic end-of-ayah sign, so each line looks intentional on its own
    rather than just cut off mid-ornament. The ayah number sits inside
    the closing bracket of the LAST line only — that's the one true
    end-of-ayah marker; earlier lines get a plain ﴿ ... ﴾ frame with no
    number.
        "بِسْمِ اللَّهِ ... السَّابِعَة" (9 words, max_words=7) ->
        "﴿بِسْمِ اللَّهِ ... الرَّابِعَة﴾\n﴿الْخَامِسَة السَّادِسَة السَّابِعَة ١﴾"
    Wrapping here — at fetch time — means every consumer downstream (the
    script hint box, the aya preview list, and the burned captions) sees
    the same already-broken, already-framed text instead of each having
    to re-implement this on its own.
    """
    words = (ar_plain or "").split()
    num = to_arabic_indic_numerals(ayah_number)
    if not words:
        return f"{_ORNATE_OPEN}{num}{_ORNATE_CLOSE}"
    chunks = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    lines = [f"{_ORNATE_OPEN}{chunk}{_ORNATE_CLOSE}" for chunk in chunks[:-1]]
    lines.append(f"{_ORNATE_OPEN}{chunks[-1]} {num}{_ORNATE_CLOSE}")
    return "\n".join(lines)


def _cache_dir() -> Path:
    try:
        from app.config import CACHE_DIR
        d = Path(CACHE_DIR)
    except Exception:
        d = Path(__file__).resolve().parent.parent / "data" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_json(url: str, timeout: int = 20) -> dict:
    """GET + JSON decode, with a permanent disk cache: the Quran text and
    editions never change, so each URL is fetched from the API only once."""
    import hashlib
    cache = _cache_dir() / "api" / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": "make-quran-video/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise QuranAPIError("The Quran text service could not be reached. Please try again.") from e
    if data.get("code") != 200:
        raise QuranAPIError(f"The Quran text service returned an error ({data.get('status')}).")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data["data"], ensure_ascii=False), encoding="utf-8")
    return data["data"]


def list_editions(format: Optional[str] = None, language: Optional[str] = None,
                   type: Optional[str] = None) -> list:
    """Live list of every edition the API has, optionally filtered.
    format: 'text' | 'audio'. language: e.g. 'en', 'ar', 'fr'. type: e.g. 'translation'."""
    params = []
    if format:
        params.append(f"format={format}")
    if language:
        params.append(f"language={language}")
    if type:
        params.append(f"type={type}")
    qs = ("?" + "&".join(params)) if params else ""
    return _get_json(f"{BASE}/edition{qs}")


def get_surah_meta(surah_num: int) -> dict:
    """Name, ayah count, revelation type, etc. for a surah number (1-114)."""
    return _get_json(f"{BASE}/surah/{surah_num}")


def fetch_ayah_range(surah_num: int, ayah_start: int, ayah_end: int,
                      translation_edition: Optional[str] = "en.sahih",
                      arabic_edition: str = DEFAULT_ARABIC_EDITION,
                      max_words_per_line: int = DEFAULT_MAX_WORDS_PER_LINE) -> list:
    """
    Returns a list of dicts, one per aya, in order:
        {"surah": int, "ayah": int (number within surah), "global_number": int,
         "ar": str, "ar_plain": str, "translation": str|None,
         "ref": "Surah Name : Ayah"}
    "ar" is the fully-diacritized (tashkil) Uthmani text, pre-wrapped into
    hard lines of at most `max_words_per_line` words (real '\\n' between
    lines — not something a later rendering step has to figure out), with
    the traditional end-of-ayah marker — the ayah number in Arabic-Indic
    numerals inside the ornate ﴿ ﴾ sign — attached to the end of the last
    line, e.g. for a 9-word aya with max_words_per_line=7:
        "بِسْمِ اللَّهِ ... السَّابِعَة\n... الْكَلِمَة ﴿١﴾"
    "ar_plain" is the same text unwrapped, on one line, no marker — in
    case some caller needs the bare aya.
    ayah_end is inclusive. Fetches the whole surah once (cheap, single call)
    and slices locally — simpler and fewer round trips than one call per aya.
    """
    editions = [arabic_edition] + ([translation_edition] if translation_edition else [])
    data = _get_json(f"{BASE}/surah/{surah_num}/editions/{','.join(editions)}")
    # data is a list: one entry per edition, each with its own "ayahs" list
    # in the same order (aligned by index).
    arabic_ed = data[0]
    surah_name = arabic_ed.get("englishName") or arabic_ed.get("name") or f"Surah {surah_num}"
    translation_ed = data[1] if len(data) > 1 else None

    out = []
    for i, ar_ayah in enumerate(arabic_ed["ayahs"]):
        n = ar_ayah["numberInSurah"]
        if n < ayah_start or n > ayah_end:
            continue
        translation_text = translation_ed["ayahs"][i]["text"] if translation_ed else None
        ar_plain = ar_ayah["text"]
        out.append({
            "surah": surah_num,
            "ayah": n,
            "global_number": ar_ayah["number"],
            "ar": wrap_ayah_text(ar_plain, n, max_words_per_line),
            "ar_plain": ar_plain,
            "translation": translation_text,
            "ref": f"{surah_name} : {n}",
        })
    out.sort(key=lambda p: p["ayah"])
    return out


def reciter_audio_url(global_ayah_number: int, reciter_edition: str = "ar.alafasy",
                       bitrate: int = 128) -> str:
    """Direct CDN URL for a single aya's recitation — no API round-trip needed."""
    return CDN_AYAH_AUDIO.format(bitrate=bitrate, edition=reciter_edition,
                                  global_ayah=global_ayah_number)


def _wav_speech_bounds(wav_path, threshold: int = 500, margin_s: float = 0.03):
    """Returns (duration_s, speech_start_s, speech_end_s) for a 16-bit PCM
    wav. Speech bounds are the first/last samples whose amplitude exceeds
    `threshold` (about -36 dBFS), padded by `margin_s`, so a CDN clip that
    carries a little leading/trailing silence still gets an exact onset."""
    import wave
    import numpy as np
    with wave.open(str(wav_path), "rb") as w:
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(n)
    dur = n / float(rate)
    arr = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        arr = arr[: (len(arr) // ch) * ch].reshape(-1, ch)[:, 0]
    loud = np.flatnonzero(np.abs(arr.astype(np.int32)) > threshold)
    if loud.size == 0:
        return dur, 0.0, dur
    return (dur,
            max(0.0, loud[0] / rate - margin_s),
            min(dur, loud[-1] / rate + margin_s))


def download_and_concat_reciter_audio(ayahs: list, reciter_edition: str, out_path,
                                       bitrate: int = 128, silence_ms: int = 500) -> Path:
    """
    Downloads each aya's recitation from the CDN (in order) and joins them
    into a single mp3 at `out_path`, with `silence_ms` of silence between
    consecutive ayat.

    Every aya is decoded to PCM first and the final file is assembled
    sample by sample, so the exact start/end of each aya inside the
    combined audio is KNOWN (not guessed by silence detection). Those
    exact timings are written to a sidecar `<out_path stem>.timings.json`:
        [{"surah", "ayah", "start", "end", "clip_start", "clip_end"}, ...]
    "start"/"end" are the speech onset/offset; "clip_start"/"clip_end" are
    the bounds of the whole CDN clip. the render engine reads
    this file so captions are locked to the audio.
    """
    import wave
    out_path = Path(out_path)
    tmp_dir = out_path.parent / f"_quran_dl_{out_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    # mp3s are cached per reciter (same aya + reciter = same file forever)
    mp3_cache = _cache_dir() / "audio" / reciter_edition / str(bitrate)
    mp3_cache.mkdir(parents=True, exist_ok=True)

    RATE, CH = 44100, 2
    wav_paths = []
    for p in ayahs:
        url = reciter_audio_url(p["global_number"], reciter_edition, bitrate)
        mp3 = mp3_cache / f"{p['global_number']}.mp3"
        wav = tmp_dir / f"{p['surah']:03d}_{p['ayah']:03d}.wav"
        if not mp3.exists():
            req = urllib.request.Request(url, headers={"User-Agent": "make-quran-video/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    blob = resp.read()
                part = mp3.with_suffix(".part")
                part.write_bytes(blob)
                part.replace(mp3)
            except (urllib.error.URLError, TimeoutError) as e:
                raise QuranAPIError(f"The recitation for ayah {p['surah']}:{p['ayah']} could not be "
                                     f"downloaded. Please try again.") from e
        if not wav.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3), "-ar", str(RATE), "-ac", str(CH),
                 "-c:a", "pcm_s16le", str(wav)],
                check=True, capture_output=True)
        wav_paths.append(wav)

    silence_frames = int(RATE * silence_ms / 1000.0) if silence_ms > 0 else 0
    silence_bytes = b"\x00" * (silence_frames * CH * 2)

    combined = tmp_dir / "combined.wav"
    timings = []
    cursor_frames = 0
    with wave.open(str(combined), "wb") as out:
        out.setnchannels(CH)
        out.setsampwidth(2)
        out.setframerate(RATE)
        for i, (p, wav) in enumerate(zip(ayahs, wav_paths)):
            dur, sp_start, sp_end = _wav_speech_bounds(wav)
            with wave.open(str(wav), "rb") as w:
                n = w.getnframes()
                while True:
                    buf = w.readframes(RATE * 4)
                    if not buf:
                        break
                    out.writeframes(buf)
            clip_start = cursor_frames / float(RATE)
            clip_end = (cursor_frames + n) / float(RATE)
            timings.append({
                "surah": p["surah"], "ayah": p["ayah"],
                "start": round(clip_start + sp_start, 3),
                "end":   round(clip_start + sp_end, 3),
                "clip_start": round(clip_start, 3),
                "clip_end":   round(clip_end, 3),
            })
            cursor_frames += n
            if silence_frames and i < len(wav_paths) - 1:
                out.writeframes(silence_bytes)
                cursor_frames += silence_frames

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(combined), "-ar", "44100", "-ac", "2",
         "-b:a", "192k", str(out_path)],
        check=True, capture_output=True)

    timings_path = Path(out_path).with_suffix(".timings.json")
    timings_path.write_text(json.dumps(timings, indent=2), encoding="utf-8")
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_path


def build_pairs_file(surah_num: int, ayah_start: int, ayah_end: int,
                      translation_edition: Optional[str], out_path,
                      arabic_edition: str = DEFAULT_ARABIC_EDITION) -> Path:
    """Fetch the range and write it straight to the JSON --quran-pairs-file
    app/engine.py expects. Returns the written path."""
    ayahs = fetch_ayah_range(surah_num, ayah_start, ayah_end, translation_edition, arabic_edition)
    pairs = [{"surah": p["surah"], "ayah": p["ayah"], "ar": p["ar"],
              "ar_plain": p["ar_plain"], "translation": p["translation"],
              "ref": p["ref"]} for p in ayahs]
    out_path = Path(out_path)
    out_path.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path