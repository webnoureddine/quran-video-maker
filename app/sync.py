"""
sync.py — line-level synchronisation inside each ayah.

A long ayah is shown as several lines, one at a time. The ayah's start/end
are known (exact reciter timings, or pause detection for uploaded audio);
this module decides WHEN each line inside the ayah appears:

  1. the recitation loudness envelope (10 ms frames) is computed once;
  2. inside each ayah the reciter's real pauses (breaths, waqf stops) are
     found, together with the true start/end of the recited sound;
  3. each line boundary is matched to a real pause when one is close to
     where that boundary should fall (by the amount of text recited so far);
     a matched line appears just before the reciter resumes after the pause;
  4. boundaries with no matching pause are placed by recited text length,
     measured in SPEECH time only (pauses excluded), between the anchors.

Pure numpy + ffmpeg; nothing here alters the Quranic text.
"""
import subprocess

import numpy as np

FRAME = 0.01                       # envelope resolution (s)
LEAD = 0.25                        # the next line is fully shown when the reciter resumes
MIN_PAUSE = 0.16                   # shorter silences are not pauses (stops inside words)
WAQF = set("ۖۗۘۙۚۛۜ")


# ───────────────────────────── audio envelope ─────────────────────────────
def envelope(audio_path, sr: int = 16000) -> np.ndarray:
    """Loudness per 10 ms frame in dBFS (mono)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "-"], capture_output=True, check=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(sr * FRAME)
    n = len(x) // hop
    if n == 0:
        return np.full(1, -90.0, np.float32)
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    return (20 * np.log10(rms + 1e-9)).astype(np.float32)


def speech_map(env: np.ndarray, a: float, b: float) -> dict:
    """Inside [a, b]: the first/last recited sound and the internal pauses."""
    i0, i1 = max(0, int(a / FRAME)), min(len(env), int(b / FRAME))
    if i1 - i0 < 10:
        return {"start": a, "end": b, "pauses": []}
    w = env[i0:i1]
    loud_ref = float(np.percentile(w, 95))
    thr = max(loud_ref - 24.0, -55.0)
    loud = w > thr
    # bridge tiny loud blips (clicks) and tiny dips (consonant closures)
    loud = _close(loud, int(0.05 / FRAME), True)
    idx = np.flatnonzero(loud)
    if idx.size == 0:
        return {"start": a, "end": b, "pauses": []}
    s, e = idx[0], idx[-1] + 1
    pauses, run = [], None
    for k in range(s, e):
        if not loud[k]:
            run = k if run is None else run
        elif run is not None:
            if (k - run) * FRAME >= MIN_PAUSE:
                pauses.append((round(float((i0 + run) * FRAME), 3), round(float((i0 + k) * FRAME), 3)))
            run = None
    return {"start": round(float((i0 + s) * FRAME), 3), "end": round(float((i0 + e) * FRAME), 3), "pauses": pauses}


def _close(mask: np.ndarray, n: int, value: bool) -> np.ndarray:
    """Remove runs of `value` shorter than n frames that are surrounded by the other value."""
    m = mask.copy()
    k, L = 0, len(m)
    while k < L:
        if m[k] == value:
            j = k
            while j < L and m[j] == value:
                j += 1
            if j - k < n and k > 0 and j < L:
                m[k:j] = not value
            k = j
        else:
            k += 1
    return m


# ───────────────────────────── text weights ─────────────────────────────
def word_weight(w: str) -> float:
    """How long a word takes to recite, roughly: letters + elongation (madd)
    + doubling (shadda) + a constant per word."""
    letters = sum(1 for ch in w if "ء" <= ch <= "ي" or ch == "ٱ")
    return letters + 2.0 * w.count("ٓ") + 0.5 * w.count("ّ") + 1.0


def quran_words(text: str) -> list:
    """The display words of an ayah. Tokens without letters (a pause mark or
    sign written apart, as in the standard "simple" script: "رَيْبَ ۛ فِيهِ")
    stay attached to the word before them, so every script has the same words."""
    out = []
    for tok in (text or "").split():
        if out and not any(ch.isalpha() for ch in tok):
            out[-1] += " " + tok
        else:
            out.append(tok)
    return out


def has_waqf(w: str) -> bool:
    return any(ch in WAQF for ch in w)


# ───────────────────────────── line timing ─────────────────────────────
def line_times(lines_words: list, start: float, end: float, speech: dict = None, word_times: list = None) -> list:
    """lines_words: [[word, ...], ...] for one ayah (in order).
    Returns [(t_on, t_off), ...] covering [start, end] without gaps.
    With word_times (one recitation time per word, from app/align.py) each line
    appears LEAD before its first word is recited; otherwise pauses + text length."""
    n = len(lines_words)
    if n == 1:
        return [(start, end)]
    if word_times and len(word_times) == sum(len(ln) for ln in lines_words):
        cuts, k, prev = [], 0, start
        for ln in lines_words[:-1]:
            k += len(ln)
            t = min(max(word_times[k] - LEAD, prev + 0.25), end - 0.25)
            cuts.append(round(t, 3))
            prev = t
        bounds = [start] + cuts + [end]
        return [(bounds[i], bounds[i + 1]) for i in range(n)]
    speech = speech or {}
    s0 = max(start, float(speech.get("start", start)))
    s1 = min(end, float(speech.get("end", end)))
    if s1 - s0 < 0.2 * n:
        s0, s1 = start, end
    pauses = [(max(s0, a), min(s1, b)) for a, b in speech.get("pauses", []) if s0 < a < b < s1]

    # speech-only clock: absolute time <-> recited time (pauses removed)
    segs, cur = [], s0
    for a, b in pauses:
        segs.append((cur, a))
        cur = b
    segs.append((cur, s1))
    total = sum(b - a for a, b in segs) or (s1 - s0)

    def to_abs(sp):                       # recited seconds -> absolute time
        acc = 0.0
        for a, b in segs:
            if sp <= acc + (b - a):
                return a + (sp - acc)
            acc += b - a
        return s1

    pause_sp, acc = [], 0.0               # recited time at which each pause happens
    for a, b in segs[:-1]:
        acc += b - a
        pause_sp.append(acc)

    wts = [sum(word_weight(w) for w in ln) for ln in lines_words]
    W = sum(wts)
    C = []                                # fraction of text recited at each line boundary
    c = 0.0
    for x in wts[:-1]:
        c += x
        C.append(c / W)

    # match boundaries to pauses (monotone, each pause used once)
    k = len(pauses)
    NOPAUSE = 0.10
    INF = 1e9
    # dp[i][j] = best cost for first i boundaries using pauses < j ; choice stored
    dp = [[INF] * (k + 1) for _ in range(n)]
    ch = [[None] * (k + 1) for _ in range(n)]
    for j in range(k + 1):
        dp[0][j] = 0.0
    for i in range(1, n):                 # boundary i-1
        ci = C[i - 1]
        for j in range(k + 1):
            best, arg = dp[i - 1][j] + NOPAUSE, ("none", j)
            if j > 0:
                pj = j - 1
                diff = abs(ci - pause_sp[pj] / total)
                plen = pauses[pj][1] - pauses[pj][0]
                if diff < 0.22:
                    cost = dp[i - 1][pj] + diff - 0.04 * min(plen, 1.0)
                    if cost < best:
                        best, arg = cost, ("pause", pj)
                if dp[i][j - 1] < best:
                    best, arg = dp[i][j - 1], ("carry", j - 1)
            dp[i][j], ch[i][j] = best, arg
    # backtrack
    assign = [None] * (n - 1)
    i, j = n - 1, k
    while i > 0:
        kind, v = ch[i][j]
        if kind == "carry":
            j = v
            continue
        if kind == "pause":
            assign[i - 1] = v
            j = v
        i -= 1

    # anchors (text fraction, recited time); interpolate the rest between them
    anchors = [(0.0, 0.0)] + [(C[i], pause_sp[p]) for i, p in enumerate(assign) if p is not None] + [(1.0, total)]
    cuts = []
    for i, ci in enumerate(C):
        p = assign[i]
        if p is not None:
            t = pauses[p][1] - LEAD          # just before the reciter resumes
            t = max(t, pauses[p][0] + 0.05)
        else:
            lo = max(a for a in anchors if a[0] <= ci)
            hi = min(a for a in anchors if a[0] >= ci)
            sp = lo[1] if hi[0] == lo[0] else lo[1] + (hi[1] - lo[1]) * (ci - lo[0]) / (hi[0] - lo[0])
            t = to_abs(sp) - LEAD
        cuts.append(t)
    # keep order and a minimum display time
    out, prev = [], start
    for t in cuts:
        t = min(max(t, prev + 0.25), end - 0.25)
        out.append(round(t, 3))
        prev = t
    bounds = [start] + out + [end]
    return [(bounds[i], bounds[i + 1]) for i in range(n)]
