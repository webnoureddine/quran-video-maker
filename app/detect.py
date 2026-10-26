"""
detect.py — recognise WHICH surah and ayah range an uploaded recitation contains.

  1. speech recognition (faster-whisper, runs locally, no API key) on the
     beginning and the end of the recording (the whole file when short);
  2. the recognised words are matched against the full Quran text
     (alquran.cloud "quran-simple-clean", downloaded once and cached) with
     word-trigram voting, which tolerates recognition mistakes, tajweed
     elongation, repeated ayat and the isti'adha before the recitation;
  3. the densest matching passage gives the surah, first and last ayah.

The recognised words are ONLY used to find the passage — captions always use
the published Quran text.

Model: env WHISPER_MODEL (default "small"; "medium" is more accurate, "base"
faster; a CTranslate2 Quran model folder also works). Downloaded on first use.
"""
import os
import re
import subprocess
import tempfile
import threading
from collections import Counter, defaultdict
from pathlib import Path

from app import quran_api

_DIAC = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_NON_AR = re.compile(r"[^ء-ي\s]")
ISTIADHA = ["اعوذ", "بالله", "من", "الشيطان", "الرجيم"]


def normalize(text: str) -> list:
    """Arabic word 'skeletons': no diacritics, unified letters, no alef — so
    Uthmani, simple spelling and speech-recognition output all compare equal."""
    t = (text or "").replace("ٱ", "ا").replace("ٰ", "ا")
    t = _DIAC.sub("", t)
    t = re.sub("[أإآ]", "ا", t).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي").replace("ء", "")
    t = _NON_AR.sub(" ", t)
    out = []
    for w in t.split():
        w = w.replace("ا", "")
        if w:
            out.append(w)
    return out


# ───────────────────────────── Quran corpus ─────────────────────────────
_CORPUS = None
_CORPUS_LOCK = threading.Lock()


def corpus():
    """(words, refs, trigram index): refs[i] = (surah, ayah) of word i."""
    global _CORPUS
    with _CORPUS_LOCK:
        if _CORPUS is None:
            data = quran_api._get_json(f"{quran_api.BASE}/quran/quran-simple-clean", timeout=60)
            _CORPUS = build_corpus([(s["number"], a["numberInSurah"], a["text"])
                                    for s in data["surahs"] for a in s["ayahs"]])
        return _CORPUS


def build_corpus(ayahs) -> tuple:
    words, refs = [], []
    for surah, ayah, text in ayahs:
        for w in normalize(text):
            words.append(w)
            refs.append((int(surah), int(ayah)))
    index = defaultdict(list)
    for i in range(len(words) - 2):
        index[(words[i], words[i + 1], words[i + 2])].append(i)
    return words, refs, dict(index)


# ───────────────────────────── matching ─────────────────────────────
def _strip_istiadha(ws: list) -> list:
    head = ws[:8]
    for k in range(len(head)):
        if head[k] == "رجيم" or head[k] == "لرجيم" or (k >= 2 and head[k - 1] == "لشيطن"):
            if any(x.startswith("عوذ") or x.startswith("عوذ") for x in head[:k]):
                return ws[k + 1:]
    return ws


def _hits(trans: list, corp) -> list:
    """Corpus positions matched by the transcript's trigrams: [(corpus_pos, transcript_pos)]."""
    words, refs, index = corp
    out = []
    for i in range(len(trans) - 2):
        pos = index.get((trans[i], trans[i + 1], trans[i + 2]))
        if pos and len(pos) <= 40:              # very common phrases say nothing about where we are
            out.extend((p, i) for p in pos)
    return out


def _best_cluster(hits: list, refs, surah: int = None, min_pos: int = None):
    """The best-supported alignment of the transcript to one passage.
    Returns (surah, [(corpus_pos, transcript_pos), ...] one per transcript trigram) or None."""
    by_surah = defaultdict(list)
    for p, i in hits:
        s = refs[p][0]
        if (surah is None or s == surah) and (min_pos is None or p >= min_pos):
            by_surah[s].append((p, i))
    best = None
    for s, hs in by_surah.items():
        diag = Counter((p - i) // 20 for p, i in hs)
        for d, _ in diag.most_common(3):
            near = [(p, i) for p, i in hs if abs((p - i) // 20 - d) <= 1]
            if not near:
                continue
            med = sorted(p - i for p, i in near)[len(near) // 2]
            # one corpus position per transcript trigram: the one on the alignment line
            pick = {}
            for p, i in near:
                if i not in pick or abs(p - i - med) < abs(pick[i] - i - med):
                    pick[i] = p
            pairs = sorted((p, i) for i, p in pick.items())
            # keep the longest run that moves forward without big jumps
            runs, cur = [], [pairs[0]]
            for x, y in zip(pairs, pairs[1:]):
                if y[0] - x[0] > 60 or y[1] < x[1]:
                    runs.append(cur)
                    cur = []
                cur.append(y)
            runs.append(cur)
            run = max(runs, key=len)
            if best is None or len(run) > len(best[1]):
                best = (s, run)
    return best


def locate(head_words: list, tail_words: list = None, corp=None):
    """-> {"surah", "ayah_start", "ayah_end", "confidence"} or None."""
    corp = corp or corpus()
    words, refs, _ = corp
    head = _strip_istiadha(head_words)
    h = _best_cluster(_hits(head, corp), refs)
    if not h or len(h[1]) < 2:
        return None
    surah, run = h
    # where the recording starts/ends in the corpus (extrapolated from the first/last
    # matched trigram), then snapped to the nearest ayah boundary
    p0, i0 = run[0]
    est_start = p0 - i0
    p1, i1 = run[-1]
    est_end = p1 + 2 + (len(head) - 3 - i1)
    votes, total = len(run), max(1, len(head) - 2)
    if tail_words:
        t = _best_cluster(_hits(tail_words, corp), refs, surah=surah, min_pos=max(0, est_start))
        if t and len(t[1]) >= 2:
            p1, i1 = t[1][-1]
            est_end = max(est_end, p1 + 2 + (len(tail_words) - 3 - i1))
            votes += len(t[1])
            total += max(1, len(tail_words) - 2)
    bounds = _ayah_bounds(refs, surah)                  # [(ayah, first_pos, last_pos)]
    a_start = min(bounds, key=lambda b: abs(b[1] - est_start))[0]
    a_end = min((b for b in bounds if b[0] >= a_start), key=lambda b: abs(b[2] - est_end))[0]
    return {"surah": surah, "ayah_start": a_start, "ayah_end": a_end,
            "confidence": round(min(1.0, votes / total), 2)}


def _ayah_bounds(refs, surah: int) -> list:
    out = {}
    for pos, (s, a) in enumerate(refs):
        if s == surah:
            lo, _ = out.get(a, (pos, pos))
            out[a] = (lo, pos)
    return [(a, lo, hi) for a, (lo, hi) in sorted(out.items())]


# ───────────────────────────── speech recognition ─────────────────────────────
_MODEL = None
_MODEL_LOCK = threading.Lock()


def _model():
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            _MODEL = WhisperModel(os.getenv("WHISPER_MODEL", "small"), device="auto", compute_type="int8")
        return _MODEL


def _duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _transcribe(path, start: float, length: float) -> list:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "part.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(path),
                        "-ac", "1", "-ar", "16000", str(wav)], check=True, capture_output=True)
        segs, _ = _model().transcribe(str(wav), language="ar", beam_size=5, vad_filter=True,
                                      condition_on_previous_text=False)
        return normalize(" ".join(s.text for s in segs))


def detect_file(path) -> dict:
    """Recognise the passage in an audio file. Raises on failure."""
    dur = _duration(path)
    win = 50.0
    if dur <= 2.2 * win:
        head, tail = _transcribe(path, 0, dur), None
    else:
        head = _transcribe(path, 0, win)
        tail = _transcribe(path, max(0.0, dur - win), win)
    res = locate(head, tail)
    if not res:
        raise LookupError("not recognised")
    return res
