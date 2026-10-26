"""
db.py — thin Supabase client (REST: Auth, PostgREST, Storage) using plain
`requests`, so no extra SDK is needed. Only used when Supabase is configured
(config.DEV_MODE is False); every call uses the SERVICE key and therefore
runs server-side only — the service key never reaches the browser.

Row Level Security still protects the tables for anyone talking to Supabase
directly with the public anon key (see supabase/schema.sql); the server
additionally scopes every query to the signed-in user itself.
"""
import time
from pathlib import Path
from urllib.parse import quote

import requests

from app import config as C


class SupabaseError(RuntimeError):
    pass


def is_remote() -> bool:
    return not C.DEV_MODE


def _h(json_body=True, extra=None):
    h = {"apikey": C.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {C.SUPABASE_SERVICE_KEY}"}
    if json_body:
        h["Content-Type"] = "application/json"
    if extra:
        h.update(extra)
    return h


def _check(r: requests.Response, what: str):
    if r.status_code >= 300:
        raise SupabaseError(f"{what} failed ({r.status_code}): {r.text[:300]}")
    return r


# ───────────────────────────── Auth ─────────────────────────────
_USER_CACHE: dict = {}


def verify_user(token: str):
    """Validate a user's access token with Supabase Auth. Returns
    {"id", "email"} or None. Results are cached for 60 s."""
    if not token:
        return None
    hit = _USER_CACHE.get(token)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        r = requests.get(f"{C.SUPABASE_URL}/auth/v1/user",
                         headers={"apikey": C.SUPABASE_ANON_KEY or C.SUPABASE_SERVICE_KEY,
                                  "Authorization": f"Bearer {token}"}, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    u = r.json()
    user = {"id": u.get("id"), "email": u.get("email")}
    if len(_USER_CACHE) > 5000:
        _USER_CACHE.clear()
    _USER_CACHE[token] = (time.time() + 60, user)
    return user


# ───────────────────────────── Tables (PostgREST) ─────────────────────────────
def select(table: str, params: dict) -> list:
    r = requests.get(f"{C.SUPABASE_URL}/rest/v1/{table}", headers=_h(False), params=params, timeout=15)
    return _check(r, f"select {table}").json()


def insert(table: str, row: dict, upsert: bool = False):
    prefer = "return=minimal" + (",resolution=merge-duplicates" if upsert else "")
    r = requests.post(f"{C.SUPABASE_URL}/rest/v1/{table}", headers=_h(extra={"Prefer": prefer}),
                      json=row, timeout=15)
    _check(r, f"insert {table}")


def update(table: str, match: dict, values: dict):
    params = {k: f"eq.{v}" for k, v in match.items()}
    r = requests.patch(f"{C.SUPABASE_URL}/rest/v1/{table}", headers=_h(extra={"Prefer": "return=minimal"}),
                       params=params, json=values, timeout=15)
    _check(r, f"update {table}")


def count_since(table: str, user_id: str, since_iso: str) -> int:
    r = requests.get(f"{C.SUPABASE_URL}/rest/v1/{table}",
                     headers=_h(False, {"Prefer": "count=exact", "Range": "0-0"}),
                     params={"select": "id", "user_id": f"eq.{user_id}", "created_at": f"gte.{since_iso}"},
                     timeout=15)
    _check(r, f"count {table}")
    rng = r.headers.get("Content-Range", "*/0")
    try:
        return int(rng.split("/")[-1])
    except ValueError:
        return 0


# ───────────────────────────── Storage ─────────────────────────────
def _obj(bucket: str, path: str) -> str:
    return f"{C.SUPABASE_URL}/storage/v1/object/{bucket}/{quote(path)}"


def storage_list(bucket: str, prefix: str = "", limit: int = 1000) -> list:
    r = requests.post(f"{C.SUPABASE_URL}/storage/v1/object/list/{bucket}", headers=_h(),
                      json={"prefix": prefix, "limit": limit, "offset": 0,
                            "sortBy": {"column": "created_at", "order": "desc"}}, timeout=20)
    return _check(r, f"list {bucket}/{prefix}").json()


def storage_upload(bucket: str, path: str, file_path, content_type: str = "application/octet-stream"):
    with open(file_path, "rb") as f:
        r = requests.post(_obj(bucket, path), headers=_h(False, {"Content-Type": content_type, "x-upsert": "true"}),
                          data=f, timeout=600)
    _check(r, f"upload {bucket}/{path}")


def storage_download(bucket: str, path: str, dest) -> Path:
    dest = Path(dest)
    with requests.get(_obj(bucket, path), headers=_h(False), stream=True, timeout=600) as r:
        _check(r, f"download {bucket}/{path}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.replace(dest)
    return dest


def storage_signed_url(bucket: str, path: str, expires: int = 3600, download_name: str = None) -> str:
    r = requests.post(f"{C.SUPABASE_URL}/storage/v1/object/sign/{bucket}/{quote(path)}", headers=_h(),
                      json={"expiresIn": int(expires)}, timeout=15)
    signed = _check(r, f"sign {bucket}/{path}").json().get("signedURL") or ""
    url = f"{C.SUPABASE_URL}/storage/v1{signed}"
    if download_name:
        url += ("&" if "?" in url else "?") + "download=" + quote(download_name)
    return url


def storage_delete(bucket: str, paths: list):
    if not paths:
        return
    r = requests.delete(f"{C.SUPABASE_URL}/storage/v1/object/{bucket}", headers=_h(),
                        json={"prefixes": list(paths)}, timeout=30)
    _check(r, f"delete {bucket}")
