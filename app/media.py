"""
media.py — the background media library + uploads (replaces every web search,
Pinterest scraping, stock-photo API and AI image generator of the old app).

Two sources:
  library  — media YOU curated (dev: data/library/, Supabase: bucket "library")
  uploads  — media a user uploaded from their device
             (dev: data/uploads/<user>/, Supabase: bucket "uploads", <user_id>/...)

Item ids are "library/<path>" or "uploads/<user_id>/<path>", and every
operation checks that an uploads id belongs to the calling user.
"""
import json
import re
import subprocess
import uuid
from pathlib import Path

from app import config as C
from app import db
from app.i18n import AppError

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4",
        ".mkv": "video/x-matroska"}


class MediaError(AppError):
    """Message is safe to show to the user (translated, see app/i18n.py)."""


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return "image" if ext in IMAGE_EXTS else "video" if ext in VIDEO_EXTS else ""


def safe_name(name: str) -> str:
    stem, ext = Path(name or "file").stem, Path(name or "").suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[:40] or "file"
    return f"{uuid.uuid4().hex[:8]}-{stem}{ext}"


# ───────────────────────────── validation ─────────────────────────────
def _probe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def validate_visual(path, kind: str):
    """Make sure the file really is the image/video its extension claims."""
    if kind == "image":
        try:
            from PIL import Image
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                if min(im.size) < 200:
                    raise MediaError("image_small")
        except MediaError:
            raise
        except Exception:
            raise MediaError("image_invalid")
        return
    info = _probe(path)
    if not any(s.get("codec_type") == "video" for s in info.get("streams", [])):
        raise MediaError("video_invalid")


def validate_audio(path) -> float:
    info = _probe(path)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise MediaError("audio_invalid")
    try:
        dur = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0
    if dur < 1:
        raise MediaError("audio_short")
    if dur > C.MAX_AUDIO_SECONDS:
        raise MediaError("audio_long", dur=f"{dur / 60:.1f}", max=f"{C.MAX_AUDIO_SECONDS / 60:.0f}")
    return dur


def check_size(file_storage):
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > C.MAX_UPLOAD_MB * 1024 * 1024:
        raise MediaError("file_too_large", name=file_storage.filename, mb=C.MAX_UPLOAD_MB)
    if size == 0:
        raise MediaError("file_empty", name=file_storage.filename)
    return size


# ───────────────────────────── listing ─────────────────────────────
def _uid(user) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", str(user["id"]))


def _local_items(root: Path, id_prefix: str, source: str, sub: str = "") -> list:
    out = []
    base = root / sub if sub else root
    if not base.exists():
        return out
    for f in sorted(base.rglob("*"), key=lambda p: -p.stat().st_mtime):
        if f.is_file() and kind_of(f.name):
            rel = f.relative_to(root).as_posix()
            out.append({"id": f"{id_prefix}/{rel}", "name": f.name.split("-", 1)[-1] if source == "uploads" else f.name,
                        "kind": kind_of(f.name), "source": source, "size": f.stat().st_size,
                        "url": f"/api/media/file?id={id_prefix}/{rel}"})
    return out


def _remote_items(bucket: str, prefix: str, id_prefix: str, source: str, depth: int = 0) -> list:
    out = []
    for o in db.storage_list(bucket, prefix):
        name = o.get("name") or ""
        path = f"{prefix}{name}"
        if o.get("id") is None:                       # a folder
            if depth < 2:
                out += _remote_items(bucket, path + "/", id_prefix, source, depth + 1)
            continue
        if not kind_of(name):
            continue
        out.append({"id": f"{id_prefix}/{path}", "name": name.split("-", 1)[-1] if source == "uploads" else name,
                    "kind": kind_of(name), "source": source,
                    "size": (o.get("metadata") or {}).get("size"),
                    "url": db.storage_signed_url(bucket, path, 3600)})
    return out


def list_media(user) -> dict:
    uid = _uid(user)
    if db.is_remote():
        lib = _remote_items(C.BUCKET_LIBRARY, "", "library", "library")
        up = _remote_items(C.BUCKET_UPLOADS, f"{uid}/backgrounds/", "uploads", "uploads")
    else:
        lib = _local_items(C.LIBRARY_DIR, "library", "library")
        up = _local_items(C.USER_UPLOADS_DIR, "uploads", "uploads", f"{uid}/backgrounds")
    return {"library": lib, "uploads": up}


# ───────────────────────────── uploads ─────────────────────────────
def save_background(user, file_storage, tmp_dir: Path) -> dict:
    kind = kind_of(file_storage.filename or "")
    if not kind:
        raise MediaError("media_type", name=file_storage.filename)
    size = check_size(file_storage)
    name = safe_name(file_storage.filename)
    tmp = Path(tmp_dir) / name
    file_storage.save(tmp)
    try:
        validate_visual(tmp, kind)
        return _store(user, tmp, f"backgrounds/{name}", kind, size)
    finally:
        tmp.unlink(missing_ok=True)


FONT_EXTS = (".ttf", ".otf", ".woff", ".woff2")
MAX_FONT_MB = 15


def _font_meta_cache() -> dict:
    try:
        return json.loads((C.CACHE_DIR / "userfonts.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _font_meta_save(cache: dict):
    try:
        (C.CACHE_DIR / "userfonts.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def save_font(user, file_storage, tmp_dir: Path) -> dict:
    """Validate an uploaded font (converted to .ttf), check that it really renders,
    store it in the user's fonts folder."""
    from app import captions as CAP
    ext = Path(file_storage.filename or "").suffix.lower()
    if ext not in FONT_EXTS:
        raise MediaError("font_type")
    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_FONT_MB * 1024 * 1024:
        raise MediaError("file_too_large", name=file_storage.filename, mb=MAX_FONT_MB)
    raw = Path(tmp_dir) / safe_name(file_storage.filename)
    file_storage.save(raw)
    ttf = raw.with_suffix(".ttf") if ext != ".otf" else raw
    try:
        try:
            from fontTools.ttLib import TTFont
            f = TTFont(str(raw))
            if ext in (".woff", ".woff2"):
                f.flavor = None
                f.save(str(ttf))
        except Exception:
            raise MediaError("font_invalid")
        info = CAP.check_font_file(ttf)
        if info["script"] == "none":
            raise MediaError("font_unusable")
        item = _store(user, ttf, f"fonts/{ttf.name}", "font", ttf.stat().st_size)
        cache = _font_meta_cache()
        cache[item["id"]] = info
        _font_meta_save(cache)
        return {**item, **info}
    finally:
        raw.unlink(missing_ok=True)
        ttf.unlink(missing_ok=True)


def list_fonts(user, tmp_dir: Path) -> list:
    """The user's uploaded fonts: [{id, family, script, quran_ok, url, file}]."""
    from app import captions as CAP
    uid = _uid(user)
    if db.is_remote():
        objs = [(f"uploads/{uid}/fonts/{o['name']}", f"{uid}/fonts/{o['name']}")
                for o in db.storage_list(C.BUCKET_UPLOADS, f"{uid}/fonts/") if o.get("id") is not None]
    else:
        d = C.USER_UPLOADS_DIR / uid / "fonts"
        objs = [(f"uploads/{uid}/fonts/{f.name}", f"{uid}/fonts/{f.name}") for f in sorted(d.glob("*.[ot]tf"))] if d.exists() else []
    cache, changed, out = _font_meta_cache(), False, []
    for mid, path in objs:
        info = cache.get(mid)
        if info is None:                      # e.g. cache lost: check again once
            try:
                local = fetch_for_render(user, mid, tmp_dir)
                info = CAP.check_font_file(local)
                if db.is_remote():
                    Path(local).unlink(missing_ok=True)
            except Exception:
                info = {"family": Path(path).stem, "script": "none", "quran_ok": False}
            cache[mid] = info
            changed = True
        if info["script"] == "none":
            continue
        url = db.storage_signed_url(C.BUCKET_UPLOADS, path, 3600) if db.is_remote() else f"/api/media/file?id={mid}"
        out.append({"id": mid, **info, "url": url, "file": Path(path).name, "user": True})
    if changed:
        _font_meta_save(cache)
    return out


def save_logo(user, file_storage, tmp_dir: Path) -> dict:
    if Path(file_storage.filename or "").suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise MediaError("logo_type")
    size = check_size(file_storage)
    name = safe_name(file_storage.filename)
    tmp = Path(tmp_dir) / name
    file_storage.save(tmp)
    try:
        try:
            from PIL import Image
            with Image.open(tmp) as im:
                im.verify()
        except Exception:
            raise MediaError("image_invalid")
        return _store(user, tmp, f"logos/{name}", "image", size)
    finally:
        tmp.unlink(missing_ok=True)


def _store(user, tmp: Path, rel: str, kind: str, size: int) -> dict:
    uid = _uid(user)
    path = f"{uid}/{rel}"
    if db.is_remote():
        db.storage_upload(C.BUCKET_UPLOADS, path, tmp, MIME.get(tmp.suffix.lower(), "application/octet-stream"))
        url = db.storage_signed_url(C.BUCKET_UPLOADS, path, 3600)
    else:
        dest = C.USER_UPLOADS_DIR / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(dest)
        url = f"/api/media/file?id=uploads/{path}"
    return {"id": f"uploads/{path}", "name": tmp.name.split("-", 1)[-1], "kind": kind,
            "source": "uploads", "size": size, "url": url}


# ───────────────────────────── access ─────────────────────────────
def _split(user, media_id: str):
    """-> (source, path) after checking the caller may use this item."""
    media_id = (media_id or "").strip()
    if ".." in media_id or media_id.startswith("/") or "\\" in media_id:
        raise MediaError("media_invalid")
    src, _, path = media_id.partition("/")
    if src == "library" and path:
        return src, path
    if src == "uploads" and path.startswith(_uid(user) + "/"):
        return src, path
    raise MediaError("media_unavailable")


def local_path(user, media_id: str):
    """Dev mode: the file on disk (for serving / rendering)."""
    src, path = _split(user, media_id)
    root = C.LIBRARY_DIR if src == "library" else C.USER_UPLOADS_DIR
    p = (root / path).resolve()
    if root.resolve() not in p.parents or not p.is_file():
        raise MediaError("media_gone")
    return p


def fetch_for_render(user, media_id: str, dest_dir: Path) -> Path:
    """A local copy of the item for the render engine."""
    src, path = _split(user, media_id)
    if not db.is_remote():
        return local_path(user, media_id)
    bucket = C.BUCKET_LIBRARY if src == "library" else C.BUCKET_UPLOADS
    dest = Path(dest_dir) / safe_name(Path(path).name)
    try:
        return db.storage_download(bucket, path, dest)
    except db.SupabaseError:
        raise MediaError("media_load_failed", name=Path(path).name)


def delete(user, media_id: str):
    src, path = _split(user, media_id)
    if src != "uploads":
        raise MediaError("library_readonly")
    if db.is_remote():
        db.storage_delete(C.BUCKET_UPLOADS, [path])
    else:
        local_path(user, media_id).unlink(missing_ok=True)
