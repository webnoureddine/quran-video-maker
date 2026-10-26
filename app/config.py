"""All settings come from environment variables (see .env.example)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:          # python-dotenv is optional at runtime
    pass

BASE = Path(__file__).resolve().parent.parent
_e = lambda k, d="": os.getenv(k, d)

SUPABASE_URL = _e("SUPABASE_URL").rstrip("/")
SUPABASE_ANON_KEY = _e("SUPABASE_ANON_KEY")               # public, safe to send to the browser
SUPABASE_SERVICE_KEY = _e("SUPABASE_SERVICE_KEY")        # server-side only, never sent to the browser
DEV_MODE = not (SUPABASE_URL and SUPABASE_SERVICE_KEY)    # no Supabase configured -> local files + no login

BUCKET_LIBRARY, BUCKET_UPLOADS, BUCKET_OUTPUTS = "library", "uploads", "outputs"

DATA_DIR = Path(_e("DATA_DIR", str(BASE / "data")))       # dev-mode storage + caches
WORK_DIR = Path(_e("WORK_DIR", str(BASE / "work")))       # temp render folders (deleted after each job)
LIBRARY_DIR = DATA_DIR / "library"                        # dev mode: your own background library
USER_UPLOADS_DIR = DATA_DIR / "uploads"                   # dev mode: backgrounds/logos uploaded from the UI
OUTPUTS_DIR = DATA_DIR / "outputs"                        # finished videos (local copy, kept RETENTION_DAYS)
CACHE_DIR = DATA_DIR / "cache"                            # Quran text + reciter audio cache
FONTS_DIR = BASE / "fonts"
LOGO_PATH = Path(_e("LOGO_PATH", str(BASE / "assets" / "logo.png")))
FORCE_WATERMARK = _e("FORCE_WATERMARK", "false").lower() == "true"

MAX_AYAHS = int(_e("MAX_AYAHS", "40"))
MAX_AUDIO_SECONDS = int(_e("MAX_AUDIO_SECONDS", "900"))
MAX_BG_ITEMS = int(_e("MAX_BG_ITEMS", "30"))
MAX_UPLOAD_MB = int(_e("MAX_UPLOAD_MB", "50"))            # Supabase free plan = 50 MB per file
OUTPUT_LIMIT_MB = int(_e("OUTPUT_LIMIT_MB", "48"))        # rendered video is re-encoded to stay under this (0 = no limit)
WORKERS = int(_e("WORKERS", "1"))
DAILY_JOB_LIMIT = int(_e("DAILY_JOB_LIMIT", "20"))
RETENTION_DAYS = int(_e("RETENTION_DAYS", "7"))
TARGET_LUFS = float(_e("TARGET_LUFS", "-14"))             # loudness of the recitation in the video (0 = leave untouched)
PORT = int(_e("PORT", "8000"))

for _d in (DATA_DIR, WORK_DIR, LIBRARY_DIR, USER_UPLOADS_DIR, OUTPUTS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
