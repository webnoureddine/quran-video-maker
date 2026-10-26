"""Upload your own background images/videos to the shared Supabase "library" bucket.

    python scripts/upload_library.py path/to/folder [subfolder]

Every PNG/JPG/WEBP/MP4/MOV/WEBM in the folder is uploaded (existing files with the
same name are replaced). In local mode simply copy files into data/library/ instead.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config as C, db, media  # noqa: E402

if C.DEV_MODE:
    sys.exit("Supabase is not configured (.env). In local mode, copy files into data/library/.")
src = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(__doc__)
sub = (sys.argv[2].strip("/") + "/") if len(sys.argv) > 2 else ""
n = 0
for f in sorted(src.iterdir()):
    kind = media.kind_of(f.name)
    if not f.is_file() or not kind:
        continue
    if f.stat().st_size > C.MAX_UPLOAD_MB * 1048576:
        print(f"skip (>{C.MAX_UPLOAD_MB} MB): {f.name}")
        continue
    media.validate_visual(f, kind)
    db.storage_upload(C.BUCKET_LIBRARY, sub + f.name, f, media.MIME.get(f.suffix.lower(), "application/octet-stream"))
    n += 1
    print("uploaded", sub + f.name)
print(f"{n} file(s) uploaded to the library.")
