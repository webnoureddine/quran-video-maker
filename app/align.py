"""
align.py — word-level synchronisation.

Speech recognition (faster-whisper, local) gives the time of every word the
reciter says. Those recognised words are aligned to the exact Quran words
(banded Needleman–Wunsch on letter skeletons), so every Quran word gets the
moment it is recited. Words the recogniser missed are interpolated between
their neighbours by length.

Result: an ayah caption appears when its first word is recited, and each line
of a long ayah appears when ITS first word is recited — with any recitation,
uploaded or not. The recognised text is only used for timing; captions always
show the published Quran text.
"""
import os

from app.detect import normalize, _model
from app.sync import quran_words


def recognise_words(audio_path) -> list:
    """[(skeleton, start, end)] for every recognised word, in order."""
    segs, _ = _model().transcribe(str(audio_path), language="ar", beam_size=5, vad_filter=True,
                                  word_timestamps=True, condition_on_previous_text=False)
    out = []
    for seg in segs:
        for w in (seg.words or []):
            for sk in normalize(w.word):
                out.append((sk, float(w.start), float(w.end)))
    return out


def _bigrams(w: str) -> set:
    return {w[i:i + 2] for i in range(len(w) - 1)} or {w}


def _sim(a: str, b: str, ba: set, bb: set) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    j = len(ba & bb) / len(ba | bb)
    if a.startswith(b) or b.startswith(a):
        j = max(j, 0.7)
    return j


def align_words(quran: list, rec: list, band: int = 120) -> list:
    """quran: [skeleton] (may contain '' for marks), rec: [(skeleton, start, end)].
    Returns, per Quran word, the matched start time or None."""
    n, m = len(quran), len(rec)
    if not n or not m:
        return [None] * n
    qb = [_bigrams(w) for w in quran]
    rb = [_bigrams(w) for w, _, _ in rec]
    GAP = -0.45
    NEG = -1e9
    # banded DP around the diagonal j ~ i*m/n
    lo = [max(0, int(i * m / n) - band) for i in range(n + 1)]
    hi = [min(m, int(i * m / n) + band) for i in range(n + 1)]
    score = [dict() for _ in range(n + 1)]
    back = [dict() for _ in range(n + 1)]
    for j in range(0, hi[0] + 1):
        score[0][j] = GAP * j
        back[0][j] = 2
    for i in range(1, n + 1):
        si, sp = score[i], score[i - 1]
        qi, qbi = quran[i - 1], qb[i - 1]
        for j in range(lo[i], hi[i] + 1):
            best, arg = sp.get(j, NEG) + GAP, 1                      # Quran word not recognised
            if j > 0:
                v = si.get(j - 1, NEG) + GAP                          # extra recognised word
                if v > best:
                    best, arg = v, 2
                d = sp.get(j - 1)
                if d is not None and qi:
                    s = _sim(qi, rec[j - 1][0], qbi, rb[j - 1])
                    v = d + (2.0 * s - 0.6)
                    if v > best:
                        best, arg = v, 0
            si[j], back[i][j] = best, arg
    # backtrack
    out = [None] * n
    i, j = n, max(score[n], key=score[n].get)
    while i > 0 and j >= 0:
        a = back[i].get(j)
        if a is None:
            break
        if a == 0:
            if _sim(quran[i - 1], rec[j - 1][0], qb[i - 1], rb[j - 1]) >= 0.5:
                out[i - 1] = rec[j - 1][1]
            i, j = i - 1, j - 1
        elif a == 1:
            i -= 1
        else:
            j -= 1
    return out


def word_times(timed_ayahs: list, audio_path, duration: float):
    """Adds p["word_times"] (one start time per display word of p["ar_plain"])
    to every ayah. Returns the fraction of words matched (0 = not usable)."""
    if os.getenv("SYNC_ASR", "1") == "0":
        return 0.0
    rec = recognise_words(audio_path)
    if len(rec) < 3:
        return 0.0
    words, owner = [], []
    for k, p in enumerate(timed_ayahs):
        for w in quran_words(p.get("ar_plain") or ""):
            sk = normalize(w)
            words.append(sk[0] if sk else "")
            owner.append(k)
    times = align_words(words, rec)
    matched = sum(1 for t in times if t is not None)
    real = sum(1 for w in words if w)
    ratio = matched / max(1, real)
    # keep only anchors that move forward in time
    last = -1.0
    for i, t in enumerate(times):
        if t is not None:
            if t <= last:
                times[i] = None
            else:
                last = t
    # interpolate the rest by word length between anchors
    weight = [max(1, len(w)) for w in words]
    anchors = [i for i, t in enumerate(times) if t is not None]
    if not anchors:
        return 0.0
    full = list(times)
    for i in range(anchors[0]):                       # before the first anchor
        full[i] = max(0.0, times[anchors[0]] - 0.35 * (anchors[0] - i))
    # typical recitation speed (seconds per letter) from neighbouring anchors in the same ayah
    rates = sorted((times[b] - times[a]) / sum(weight[a:b]) for a, b in zip(anchors, anchors[1:])
                   if owner[a] == owner[b] and b - a <= 3)
    rate = rates[len(rates) // 2] if rates else 0.12
    for a, b in zip(anchors, anchors[1:]):
        if owner[a] == owner[b]:
            span = sum(weight[a:b])
            acc = 0
            for i in range(a + 1, b):
                acc += weight[i - 1]
                full[i] = times[a] + (times[b] - times[a]) * acc / span
        else:
            # an ayah boundary lies in between: missed words of the earlier ayah follow
            # anchor a, missed words of the later ayah lead up to anchor b, at the usual
            # speed — instead of being spread over the pause between the two ayat
            cut = next(i for i in range(a + 1, b + 1) if owner[i] != owner[a])
            t = times[a]
            for i in range(a + 1, cut):
                t = min(t + weight[i - 1] * rate, times[b])
                full[i] = t
            t = times[b]
            for i in range(b - 1, cut - 1, -1):
                t = max(t - weight[i] * rate, full[cut - 1] if cut - 1 > a else times[a])
                full[i] = t
    for i in range(anchors[-1] + 1, len(words)):      # after the last anchor
        full[i] = min(duration, full[i - 1] + 0.35)
    for k, p in enumerate(timed_ayahs):
        p["word_times"] = [round(full[i], 3) for i in range(len(words)) if owner[i] == k]
    return ratio
