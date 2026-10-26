"""
Make Quran Video — web server (Flask).

Serves the single-page app and a small JSON API. Renders run in a separate
engine process (app/engine.py) on a bounded worker pool, so a long render
never blocks the web server and can be cancelled.

Run locally:   python -m app.server        (or: gunicorn -w 1 --threads 8 app.server:app)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory

from app import captions as CAP
from app import config as C
from app import db, media, quran_api
from app.i18n import AppError, t as tr
from app.surahs import BY_NUMBER, as_list as surah_list

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
AUDIO_DIR = C.DATA_DIR / "audio"          # uploaded recitations (temporary, deleted after 24 h)
TMP_DIR = C.WORK_DIR / "_incoming"
PREFS_FILE = C.DATA_DIR / "preferences.json"
for d in (AUDIO_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

FORMATS = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = (C.MAX_UPLOAD_MB * 10 + 5) * 1024 * 1024   # a multi-file request


def log(msg):
    print(f"[server] {msg}", flush=True)


# ───────────────────────────── auth ─────────────────────────────
def require_user(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if C.DEV_MODE:
            g.user = {"id": "local", "email": None}
        else:
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.lower().startswith("bearer ") else request.args.get("access_token", "")
            user = db.verify_user(token)
            if not user:
                return err("sign_in", 401)
            g.user = user
        return fn(*a, **kw)
    return wrapper


def lang() -> str:
    return "ar" if (request.headers.get("X-Lang") or request.args.get("lang") or "").lower().startswith("ar") else "en"


def err(key_or_exc, code=400, **params):
    """JSON error in the user's language. Accepts a message key or an AppError."""
    if isinstance(key_or_exc, AppError):
        return jsonify({"error": tr(key_or_exc.key, lang(), **key_or_exc.params)}), code
    return jsonify({"error": tr(key_or_exc, lang(), **params)}), code


@app.errorhandler(413)
def too_large(_e):
    return err("upload_too_large", 413, mb=C.MAX_UPLOAD_MB)


@app.errorhandler(500)
def server_error(_e):
    return err("server_error", 500)


# ───────────────────────────── pages & public data ─────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


@app.route("/fonts/<path:name>")
def fonts(name):
    if not name.lower().endswith((".ttf", ".otf")):
        abort(404)
    return send_from_directory(C.FONTS_DIR, name, max_age=86400 * 30)


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "ffmpeg": bool(shutil.which("ffmpeg"))})


@app.route("/api/public-config")
def public_config():
    """Everything the browser may know. The anon key is public by design;
    the service key is never included."""
    return jsonify({
        "auth_required": not C.DEV_MODE,
        "supabase_url": C.SUPABASE_URL if not C.DEV_MODE else "",
        "supabase_anon_key": C.SUPABASE_ANON_KEY if not C.DEV_MODE else "",
        "limits": {"max_ayahs": C.MAX_AYAHS, "max_upload_mb": C.MAX_UPLOAD_MB,
                   "max_bg_items": C.MAX_BG_ITEMS, "max_audio_minutes": round(C.MAX_AUDIO_SECONDS / 60)},
        "force_watermark": C.FORCE_WATERMARK,
    })


@app.route("/api/surahs")
def surahs():
    return jsonify(surah_list())


@app.route("/api/quran/reciters")
def reciters():
    return jsonify(quran_api.RECITERS)


@app.route("/api/quran/translations")
def translations():
    return jsonify(quran_api.TRANSLATIONS)


def _db_styles() -> dict:
    """Extra / overridden caption styles from the caption_styles table."""
    if C.DEV_MODE:
        return {}
    try:
        rows = db.select("caption_styles", {"select": "id,label,description,sort,config", "is_active": "eq.true"})
        return {r["id"]: {**(r.get("config") or {}), "label": r.get("label") or r["id"],
                          "description": r.get("description") or "", "sort": r.get("sort") or 99} for r in rows}
    except Exception as e:
        log(f"caption_styles table unavailable: {e}")
        return {}


_FONTS = None
_FONTS_LOCK = threading.Lock()


def fonts_list() -> list:
    global _FONTS
    with _FONTS_LOCK:
        if _FONTS is None:
            _FONTS = CAP.available_fonts(C.FONTS_DIR, C.CACHE_DIR)
        return _FONTS


def user_fonts(user) -> list:
    try:
        return media.list_fonts(user, TMP_DIR)
    except Exception as e:
        log(f"user fonts: {e}")
        return []


@app.route("/api/fonts")
@require_user
def fonts_api():
    return jsonify(fonts_list() + user_fonts(g.user))


@app.route("/api/fonts/upload", methods=["POST"])
@require_user
def font_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return err("font_required")
    try:
        return jsonify(media.save_font(g.user, f, TMP_DIR))
    except media.MediaError as e:
        return err(e)
    except db.SupabaseError as e:
        log(f"font upload: {e}")
        return err("media_save_failed", 502, name=f.filename)


@app.route("/api/caption-styles")
def caption_styles():
    return jsonify(CAP.list_styles(_db_styles()))


def _range(data):
    try:
        surah = int(data.get("surah"))
        a = int(data.get("ayah_start"))
        b = int(data.get("ayah_end"))
    except (TypeError, ValueError):
        raise AppError("range_required")
    if surah not in BY_NUMBER:
        raise AppError("surah_invalid")
    n = BY_NUMBER[surah]["ayah_count"]
    if not (1 <= a <= b <= n):
        name = BY_NUMBER[surah]["name_ar" if lang() == "ar" else "name_en"]
        raise AppError("range_invalid", surah=name, n=n)
    if b - a + 1 > C.MAX_AYAHS:
        raise AppError("range_too_long", n=C.MAX_AYAHS)
    return surah, a, b


@app.route("/api/quran/preview", methods=["POST"])
def quran_preview():
    data = request.get_json(silent=True) or {}
    try:
        surah, a, b = _range(data)
        ed = data.get("translation_edition") or None
        if ed and ed not in {t["id"] for t in quran_api.TRANSLATIONS}:
            ed = None
        fam = str(data.get("ar_font") or "")
        info = next((f for f in fonts_list() if f["family"] == fam), {"quran_ok": True})
        ayahs = quran_api.fetch_ayah_range(surah, a, b, ed, "quran-uthmani" if CAP.text_script(info) == "uthmani"
                                           else "quran-simple")
    except AppError as e:
        return err(e)
    except quran_api.QuranAPIError:
        return err("quran_unreachable", 502)
    return jsonify({"ayahs": [{"ayah": x["ayah"], "text": x["ar_plain"], "translation": x["translation"]}
                              for x in ayahs]})


# ───────────────────────────── media library ─────────────────────────────
@app.route("/api/media")
@require_user
def media_list():
    try:
        return jsonify(media.list_media(g.user))
    except db.SupabaseError as e:
        log(f"media list: {e}")
        return err("library_failed", 502)


@app.route("/api/media/upload", methods=["POST"])
@require_user
def media_upload():
    files = request.files.getlist("files")
    if not files:
        return err("media_required")
    saved, errors = [], []
    for f in files[:C.MAX_BG_ITEMS]:
        try:
            saved.append(media.save_background(g.user, f, TMP_DIR))
        except media.MediaError as e:
            errors.append(tr(e.key, lang(), **e.params))
        except db.SupabaseError as e:
            log(f"upload: {e}")
            errors.append(tr("media_save_failed", lang(), name=f.filename))
    return jsonify({"items": saved, "errors": errors}), (200 if saved else 400)


@app.route("/api/media", methods=["DELETE"])
@require_user
def media_delete():
    try:
        media.delete(g.user, (request.get_json(silent=True) or {}).get("id"))
    except media.MediaError as e:
        return err(e)
    return jsonify({"ok": True})


@app.route("/api/media/file")
@require_user
def media_file():
    """Dev mode only (Supabase mode serves signed storage URLs)."""
    if not C.DEV_MODE:
        abort(404)
    try:
        return send_file(media.local_path(g.user, request.args.get("id", "")), conditional=True, max_age=3600)
    except media.MediaError:
        abort(404)


@app.route("/api/logo/upload", methods=["POST"])
@require_user
def logo_upload():
    f = request.files.get("file")
    if not f:
        return err("logo_required")
    try:
        return jsonify(media.save_logo(g.user, f, TMP_DIR))
    except media.MediaError as e:
        return err(e)
    except db.SupabaseError as e:
        log(f"logo upload: {e}")
        return err("logo_failed", 502)


@app.route("/api/audio/upload", methods=["POST"])
@require_user
def audio_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return err("audio_required")
    if Path(f.filename).suffix.lower() not in media.AUDIO_EXTS:
        return err("audio_type")
    try:
        media.check_size(f)
    except media.MediaError as e:
        return err(e)
    folder = AUDIO_DIR / media._uid(g.user)
    folder.mkdir(parents=True, exist_ok=True)
    name = media.safe_name(f.filename)
    dest = folder / name
    f.save(dest)
    try:
        dur = media.validate_audio(dest)
    except media.MediaError as e:
        dest.unlink(missing_ok=True)
        return err(e)
    return jsonify({"audio_id": name, "duration": round(dur, 1), "name": f.filename})


# ───────────────────────────── recitation recognition ─────────────────────────────
DETECTIONS: dict = {}          # (user id, audio id) -> {"status", "result" | "error"}


def _detect_worker(key, path):
    try:
        from app import detect
        r = detect.detect_file(path)
        s = BY_NUMBER[r["surah"]]
        DETECTIONS[key] = {"status": "done", "result": {**r, "name_en": s["name_en"], "name_ar": s["name_ar"]}}
    except ImportError:
        DETECTIONS[key] = {"status": "error", "error": "detect_unavailable"}
    except Exception as e:
        log(f"detect {path}: {e!r}")
        DETECTIONS[key] = {"status": "error", "error": "detect_failed"}


@app.route("/api/audio/detect", methods=["POST"])
@require_user
def audio_detect_start():
    aid = Path(str((request.get_json(silent=True) or {}).get("audio_id") or "")).name
    path = AUDIO_DIR / media._uid(g.user) / aid
    if not aid or not path.is_file():
        return err("audio_reupload")
    key = (g.user["id"], aid)
    if DETECTIONS.get(key, {}).get("status") not in ("running", "done"):
        DETECTIONS[key] = {"status": "running"}
        threading.Thread(target=_detect_worker, args=(key, path), daemon=True).start()
    return jsonify({"status": DETECTIONS[key]["status"]})


@app.route("/api/audio/detect/<audio_id>")
@require_user
def audio_detect_status(audio_id):
    d = DETECTIONS.get((g.user["id"], Path(audio_id).name))
    if not d:
        abort(404)
    out = {"status": d["status"], "result": d.get("result")}
    if d.get("error"):
        out["error"] = tr(d["error"], lang())
    return jsonify(out)


# ───────────────────────────── preferences ─────────────────────────────
PREF_KEYS = {"caption_style", "caption_options", "format", "bg_mode", "bg_motion", "frame", "watermark",
             "reciter", "translation_edition", "ui_lang", "theme"}


def _load_prefs(user) -> dict:
    if C.DEV_MODE:
        try:
            return json.loads(PREFS_FILE.read_text(encoding="utf-8")).get(user["id"], {})
        except Exception:
            return {}
    try:
        rows = db.select("user_preferences", {"select": "prefs", "user_id": f"eq.{user['id']}"})
        return (rows[0].get("prefs") or {}) if rows else {}
    except Exception as e:
        log(f"prefs load: {e}")
        return {}


@app.route("/api/preferences", methods=["GET", "POST"])
@require_user
def preferences():
    if request.method == "GET":
        return jsonify(_load_prefs(g.user))
    data = {k: v for k, v in (request.get_json(silent=True) or {}).items() if k in PREF_KEYS}
    if len(json.dumps(data)) > 20000:
        return err("prefs_large")
    if C.DEV_MODE:
        try:
            allp = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except Exception:
            allp = {}
        allp[g.user["id"]] = data
        PREFS_FILE.write_text(json.dumps(allp, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        try:
            db.insert("user_preferences", {"user_id": g.user["id"], "prefs": data,
                                           "updated_at": datetime.now(timezone.utc).isoformat()}, upsert=True)
        except Exception as e:
            log(f"prefs save: {e}")
            return err("prefs_failed", 502)
    return jsonify({"ok": True})


# ───────────────────────────── jobs ─────────────────────────────
JOBS: dict = {}
JOBS_LOCK = threading.Lock()
WORKER_SLOTS = threading.Semaphore(max(1, C.WORKERS))


def _public(job) -> dict:
    keys = ("id", "status", "progress", "stage", "title", "created", "video_url", "download_url",
            "queue_position")
    out = {k: job.get(k) for k in keys}
    e = job.get("error")
    out["error"] = tr(e[0], lang(), **e[1]) if isinstance(e, tuple) else e
    if job["status"] == "queued":
        with JOBS_LOCK:
            waiting = sorted((j for j in JOBS.values() if j["status"] == "queued"), key=lambda j: j["created"])
        out["queue_position"] = next((i + 1 for i, j in enumerate(waiting) if j["id"] == job["id"]), None)
    return out


def _daily_count(user) -> int:
    since = time.time() - 86400
    with JOBS_LOCK:
        n = sum(1 for j in JOBS.values() if j["user_id"] == user["id"] and j["created"] >= since)
    if not C.DEV_MODE:
        try:
            iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            n = max(n, db.count_since("render_jobs", user["id"], iso))
        except Exception as e:
            log(f"job count: {e}")
    return n


def _color(v, default):
    v = str(v or "")
    return v if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else default


def _num(v, lo, hi, default):
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        return default


def _validate_request(user, data) -> dict:
    """Turn the browser's request into a clean, bounded job spec (raises ValueError)."""
    surah, a, b = _range(data)
    audio = data.get("audio") or {}
    if audio.get("source") == "upload":
        aid = Path(str(audio.get("audio_id") or "")).name
        p = AUDIO_DIR / media._uid(user) / aid
        if not aid or not p.is_file():
            raise AppError("audio_reupload")
        audio_spec = {"source": "upload", "path": str(p)}
    else:
        rec = audio.get("reciter") or "ar.alafasy"
        if rec not in {r["id"] for r in quran_api.RECITERS}:
            raise AppError("reciter_required")
        audio_spec = {"source": "reciter", "reciter": rec}

    bg = data.get("backgrounds") or []
    if not isinstance(bg, list) or not bg:
        raise AppError("bg_required")
    if len(bg) > C.MAX_BG_ITEMS:
        raise AppError("bg_too_many", n=C.MAX_BG_ITEMS)
    for mid in bg:
        media._split(user, str(mid))          # ownership check (raises MediaError, a ValueError)

    cap = data.get("caption") or {}
    fonts = fonts_list() + user_fonts(user)
    styles = CAP.all_styles(_db_styles())
    style_id = cap.get("style") if cap.get("style") in styles else next(iter(styles))
    opts = cap.get("options") or {}
    clean_opts = {
        "ar_color": _color(opts.get("ar_color"), None), "tr_color": _color(opts.get("tr_color"), None),
        "ref_color": _color(opts.get("ref_color"), None), "outline_color": _color(opts.get("outline_color"), None),
        "ar_font": str(opts.get("ar_font") or "")[:80] or None, "tr_font": str(opts.get("tr_font") or "")[:80] or None,
        "ar_size": _num(opts.get("ar_size"), 0.04, 0.18, None), "tr_ratio": _num(opts.get("tr_ratio"), 0.25, 0.8, None),
        "center_y": _num(opts.get("center_y"), 0.15, 0.85, None),
        "max_words_per_line": int(_num(opts.get("max_words_per_line"), 1, 15, 0)) or None,
        "break_at_waqf": bool(opts.get("break_at_waqf")) if "break_at_waqf" in opts else None,
        "sync_offset": _num(opts.get("sync_offset"), -1.5, 1.5, None),
        "show_translation": bool(opts.get("show_translation")) if "show_translation" in opts else None,
        "show_reference": bool(opts.get("show_reference")) if "show_reference" in opts else None,
        "box": bool(opts.get("box")) if "box" in opts else None,
        "box_color": _color(opts.get("box_color"), None),
        "box_opacity": _num(opts.get("box_opacity"), 0, 1, None),
        "box_radius": _num(opts.get("box_radius"), 0, 0.1, None),
        "anim": opts.get("anim") if opts.get("anim") in CAP.ANIMS else None,
        "hl_color": _color(opts.get("hl_color"), None),
        "glow": bool(opts.get("glow")) if "glow" in opts else None,
        "band": bool(opts.get("band")) if "band" in opts else None,
        "ornament": bool(opts.get("ornament")) if "ornament" in opts else None,
        "brackets": opts.get("brackets") if opts.get("brackets") in CAP.BRACKETS else None,
        "outline": _num(opts.get("outline"), 0, 10, None),
    }
    style = CAP.resolve_style(style_id, clean_opts, _db_styles(), fonts)
    # display fonts without the Uthmani marks get the standard ("simple") script
    # of the same published text — never an altered or generated one
    ar_info = next((f for f in fonts if f["family"] == style["ar_font"]), None)
    arabic_edition = "quran-uthmani" if CAP.text_script(ar_info) == "uthmani" else "quran-simple"
    tr_ed = cap.get("translation_edition") if style["show_translation"] else None
    if tr_ed and tr_ed not in {t["id"] for t in quran_api.TRANSLATIONS}:
        tr_ed = "en.sahih"
    if style["show_translation"] and not tr_ed:
        tr_ed = "en.sahih"

    fr = data.get("frame") or {}
    frame = {"enabled": bool(fr.get("enabled")), "radius": int(_num(fr.get("radius"), 0, 200, 40)),
             "padding": int(_num(fr.get("padding"), 0, 300, 40)), "bg_color": _color(fr.get("bg_color"), "#10231c"),
             "shadow": bool(fr.get("shadow")), "shadow_blur": int(_num(fr.get("shadow_blur"), 0, 80, 30)),
             "shadow_opacity": _num(fr.get("shadow_opacity"), 0, 1, 0.55),
             "shadow_offset": int(_num(fr.get("shadow_offset"), -40, 40, 12)),
             "bg_image_id": fr.get("bg_image_id") or None}
    if frame["bg_image_id"]:
        media._split(user, str(frame["bg_image_id"]))

    wm = data.get("watermark") or {}
    positions = ("tl", "tc", "tr", "bl", "bc", "br", "c")
    watermark = {"enabled": bool(wm.get("enabled")) or C.FORCE_WATERMARK, "logo_id": wm.get("logo_id") or None,
                 "position": wm.get("position") if wm.get("position") in positions else "br",
                 "size_pct": _num(wm.get("size_pct"), 3, 40, 14), "opacity": _num(wm.get("opacity"), 0.1, 1, 0.85),
                 "margin_pct": _num(wm.get("margin_pct"), 0, 15, 3), "shadow": bool(wm.get("shadow", True)),
                 "fade": 0.6, "show": "always"}
    if watermark["logo_id"]:
        media._split(user, str(watermark["logo_id"]))

    fmt = data.get("format") if data.get("format") in FORMATS else "landscape"
    return {"user_fonts": [f["id"] for f in fonts if f.get("user")],
            "surah": surah, "ayah_start": a, "ayah_end": b, "audio": audio_spec, "backgrounds": [str(x) for x in bg],
            "bg_mode": "multi" if data.get("bg_mode") == "multi" else "single",
            "bg_motion": bool(data.get("bg_motion", True)), "style": style, "translation_edition": tr_ed,
            "arabic_edition": arabic_edition,
            "frame": frame, "watermark": watermark, "format": fmt}


@app.route("/api/generate", methods=["POST"])
@require_user
def generate():
    data = request.get_json(silent=True) or {}
    try:
        spec = _validate_request(g.user, data)
    except AppError as e:
        return err(e)
    if _daily_count(g.user) >= C.DAILY_JOB_LIMIT:
        return err("daily_limit", 429, n=C.DAILY_JOB_LIMIT)
    s = BY_NUMBER[spec["surah"]]
    title = f"{s['name_en']} {spec['ayah_start']}" + (f"–{spec['ayah_end']}" if spec["ayah_end"] != spec["ayah_start"] else "")
    job = {"id": uuid.uuid4().hex[:16], "user_id": g.user["id"], "user": g.user, "status": "queued",
           "progress": 0, "stage": "waiting", "error": None, "title": title, "created": time.time(),
           "spec": spec, "proc": None, "cancel": False, "video_url": None, "download_url": None}
    with JOBS_LOCK:
        JOBS[job["id"]] = job
    if not C.DEV_MODE:
        try:
            db.insert("render_jobs", {"id": job["id"], "user_id": g.user["id"], "status": "queued",
                                      "surah": spec["surah"], "ayah_start": spec["ayah_start"],
                                      "ayah_end": spec["ayah_end"], "title": title})
        except Exception as e:
            log(f"render_jobs insert: {e}")
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return jsonify(_public(job))


def _own_job(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job["user_id"] != g.user["id"]:
        abort(404)
    return job


@app.route("/api/jobs")
@require_user
def jobs_list():
    with JOBS_LOCK:
        mine = [j for j in JOBS.values() if j["user_id"] == g.user["id"]]
    return jsonify([_public(j) for j in sorted(mine, key=lambda j: -j["created"])[:20]])


@app.route("/api/jobs/<job_id>")
@require_user
def job_status(job_id):
    job = _own_job(job_id)
    if job["status"] == "done" and not C.DEV_MODE and job.get("_out_path"):
        # signed URLs expire — refresh on every poll
        try:
            job["video_url"] = db.storage_signed_url(C.BUCKET_OUTPUTS, job["_out_path"], 3600)
            job["download_url"] = db.storage_signed_url(C.BUCKET_OUTPUTS, job["_out_path"], 3600,
                                                        download_name=_file_name(job))
        except Exception:
            pass
    return jsonify(_public(job))


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
@require_user
def job_cancel(job_id):
    job = _own_job(job_id)
    job["cancel"] = True
    p = job.get("proc")
    if p and p.poll() is None:
        p.terminate()
    if job["status"] in ("queued", "running"):
        job.update(status="cancelled", stage="cancelled")
    return jsonify(_public(job))


@app.route("/api/jobs/<job_id>/video")
@require_user
def job_video(job_id):
    job = _own_job(job_id)
    out = C.OUTPUTS_DIR / f"{job['id']}.mp4"
    if job["status"] != "done" or not out.exists():
        abort(404)
    dl = request.args.get("download") == "1"
    return send_file(out, mimetype="video/mp4", as_attachment=dl, download_name=_file_name(job), conditional=True)


def _file_name(job) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", f"Quran_{job['title']}").strip("_") + ".mp4"


def _set(job, **kw):
    job.update(kw)


def _db_job(job, **values):
    if C.DEV_MODE:
        return
    try:
        db.update("render_jobs", {"id": job["id"]}, values)
    except Exception as e:
        log(f"render_jobs update: {e}")


def _run_job(job):
    """Prepare inputs, run the engine, publish the result. Always cleans up."""
    spec, user = job["spec"], job["user"]
    job_dir = C.WORK_DIR / job["id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    with WORKER_SLOTS:
        if job["cancel"]:
            shutil.rmtree(job_dir, ignore_errors=True)
            return
        _set(job, status="running", progress=1, stage="loading_ayahs")
        _db_job(job, status="running")
        try:
            # 1. Quran text — always the published text, never generated
            try:
                ayahs = quran_api.fetch_ayah_range(spec["surah"], spec["ayah_start"], spec["ayah_end"],
                                                   spec["translation_edition"],
                                                   spec.get("arabic_edition") or "quran-uthmani")
            except quran_api.QuranAPIError:
                raise AppError("quran_unreachable")
            if not ayahs:
                raise AppError("no_ayah")
            pairs = [{"surah": p["surah"], "ayah": p["ayah"], "ar": p["ar"], "ar_plain": p["ar_plain"],
                      "translation": p["translation"], "ref": f"{BY_NUMBER[p['surah']]['name_en']} : {p['ayah']}"}
                     for p in ayahs]

            # 2. recitation
            timings = None
            if spec["audio"]["source"] == "reciter":
                _set(job, progress=3, stage="downloading")
                full = [dict(p, global_number=a["global_number"]) for p, a in zip(pairs, ayahs)]
                audio_path = job_dir / "recitation.mp3"
                try:
                    quran_api.download_and_concat_reciter_audio(full, spec["audio"]["reciter"], audio_path)
                except (quran_api.QuranAPIError, subprocess.CalledProcessError):
                    raise AppError("recitation_download")
                tf = audio_path.with_suffix(".timings.json")
                timings = str(tf) if tf.exists() else None
            else:
                audio_path = Path(spec["audio"]["path"])
            if job["cancel"]:
                raise InterruptedError

            # 3. backgrounds, logo, frame image -> local files
            _set(job, progress=6, stage="loading_media")
            bg_dir = job_dir / "media"
            bg_dir.mkdir(exist_ok=True)
            backgrounds = []
            for mid in spec["backgrounds"]:
                p = media.fetch_for_render(user, mid, bg_dir)
                backgrounds.append({"path": str(p), "name": Path(mid).name.split("-", 1)[-1]})
            frame = dict(spec["frame"])
            if frame.pop("bg_image_id", None) and spec["frame"]["bg_image_id"]:
                frame["bg_image"] = str(media.fetch_for_render(user, spec["frame"]["bg_image_id"], bg_dir))
            wm = dict(spec["watermark"])
            logo_id = wm.pop("logo_id", None)
            if logo_id:
                wm["path"] = str(media.fetch_for_render(user, logo_id, bg_dir))
            elif wm.get("enabled") and C.LOGO_PATH.exists():
                wm["path"] = str(C.LOGO_PATH)
            else:
                wm["enabled"] = False

            # fonts for this render: built-in + the user's uploaded fonts
            fonts_dir = job_dir / "fonts"
            fonts_dir.mkdir(exist_ok=True)
            for f in C.FONTS_DIR.glob("*.[ot]tf"):
                shutil.copy(f, fonts_dir / f.name)
            for fid in spec.get("user_fonts", []):
                try:
                    p = media.fetch_for_render(user, fid, bg_dir)
                    shutil.copy(p, fonts_dir / Path(fid).name)
                except media.MediaError:
                    pass
            W, H = FORMATS[spec["format"]]
            out_path = C.OUTPUTS_DIR / f"{job['id']}.mp4"
            engine_job = {
                "work_dir": str(job_dir / "render"), "output": str(out_path), "width": W, "height": H, "fps": 30,
                "audio": str(audio_path), "pairs": pairs, "timings_file": timings,
                "backgrounds": backgrounds, "bg_mode": spec["bg_mode"], "bg_motion": spec["bg_motion"],
                "caption_style": spec["style"], "fonts_dir": str(fonts_dir),
                "frame": frame, "watermark": wm, "target_lufs": C.TARGET_LUFS,
                "output_limit_mb": C.OUTPUT_LIMIT_MB, "max_audio_seconds": C.MAX_AUDIO_SECONDS,
            }
            jf = job_dir / "job.json"
            jf.write_text(json.dumps(engine_job, ensure_ascii=False), encoding="utf-8")

            # 4. render in a separate process
            _set(job, progress=8, stage="starting")
            proc = subprocess.Popen([sys.executable, "-m", "app.engine", "--job", str(jf)], cwd=str(C.BASE),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", bufsize=1,
                                    env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
            job["proc"] = proc
            user_error = None
            for line in proc.stdout:
                line = line.rstrip()
                if line.startswith("@@PROGRESS"):
                    parts = line.split(" ", 2)
                    pct = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                    _set(job, progress=8 + int(pct * 0.9), stage=parts[2] if len(parts) > 2 else job["stage"])
                elif line.startswith("@@ERROR"):
                    key, _, params = line[8:].strip().partition(" ")
                    try:
                        user_error = (key, json.loads(params or "{}"))
                    except ValueError:
                        user_error = (key, {})
                else:
                    print(f"[job {job['id'][:6]}] {line}", flush=True)
            proc.wait()
            if job["cancel"]:
                raise InterruptedError
            if proc.returncode != 0 or not out_path.exists():
                key, params = user_error or ("render_failed", {})
                raise AppError(key, **params)

            # 5. publish
            _set(job, progress=99, stage="saving")
            if C.DEV_MODE:
                job["video_url"] = f"/api/jobs/{job['id']}/video"
                job["download_url"] = f"/api/jobs/{job['id']}/video?download=1"
            else:
                rel = f"{media._uid(user)}/{job['id']}.mp4"
                db.storage_upload(C.BUCKET_OUTPUTS, rel, out_path, "video/mp4")
                job["_out_path"] = rel
                job["video_url"] = db.storage_signed_url(C.BUCKET_OUTPUTS, rel, 3600)
                job["download_url"] = db.storage_signed_url(C.BUCKET_OUTPUTS, rel, 3600, download_name=_file_name(job))
            _set(job, status="done", progress=100, stage="ready")
            _db_job(job, status="done", output_path=job.get("_out_path") or str(out_path),
                    finished_at=datetime.now(timezone.utc).isoformat())
        except InterruptedError:
            _set(job, status="cancelled", stage="cancelled")
            _db_job(job, status="cancelled")
        except AppError as e:
            _set(job, status="error", error=(e.key, e.params), stage="failed")
            _db_job(job, status="error", error=str(e)[:500])
        except Exception as e:
            log(f"job {job['id']} crashed: {e!r}")
            _set(job, status="error", error=("render_failed", {}), stage="failed")
            _db_job(job, status="error", error=repr(e)[:500])
        finally:
            job["proc"] = None
            shutil.rmtree(job_dir, ignore_errors=True)
            if spec["audio"]["source"] == "upload" and job["status"] == "done":
                Path(spec["audio"]["path"]).unlink(missing_ok=True)


# ───────────────────────────── housekeeping ─────────────────────────────
def _cleanup_once():
    now = time.time()
    keep_out = C.RETENTION_DAYS * 86400

    def sweep(folder: Path, max_age: float, pattern="*"):
        for p in folder.glob(pattern):
            try:
                if now - p.stat().st_mtime > max_age:
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            except OSError:
                pass

    sweep(C.OUTPUTS_DIR, keep_out, "*.mp4")
    sweep(C.WORK_DIR, 86400)
    for d in AUDIO_DIR.glob("*"):
        if d.is_dir():
            sweep(d, 86400)
    with JOBS_LOCK:
        for jid in [k for k, j in JOBS.items() if now - j["created"] > keep_out and j["status"] not in ("queued", "running")]:
            JOBS.pop(jid, None)
    if not C.DEV_MODE:
        try:   # outputs bucket: <user>/<job>.mp4
            cutoff = datetime.now(timezone.utc) - timedelta(days=C.RETENTION_DAYS)
            for folder in db.storage_list(C.BUCKET_OUTPUTS, ""):
                if folder.get("id") is not None:
                    continue
                old = [f"{folder['name']}/{o['name']}" for o in db.storage_list(C.BUCKET_OUTPUTS, folder["name"] + "/")
                       if o.get("created_at") and datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")) < cutoff]
                db.storage_delete(C.BUCKET_OUTPUTS, old)
        except Exception as e:
            log(f"output cleanup: {e}")


def _housekeeping():
    while True:
        try:
            _cleanup_once()
        except Exception as e:
            log(f"cleanup: {e}")
        time.sleep(3600)


threading.Thread(target=_housekeeping, daemon=True).start()
log(f"Make Quran Video — {'local mode (no Supabase)' if C.DEV_MODE else 'Supabase mode'}, workers={C.WORKERS}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=C.PORT, debug=False, threaded=True)
