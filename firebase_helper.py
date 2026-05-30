"""
firebase_helper.py — Firebase Realtime Database REST client (no service account required).
Public rules database; optionally secured with FIREBASE_SECRET env var.
"""
import requests, os, json

TIMEOUT = 12

def _base_url():
    return os.environ.get("FIREBASE_URL", "").rstrip("/")

def _secret():
    return os.environ.get("FIREBASE_SECRET", "")

def _url(path: str) -> str:
    base = f"{_base_url()}/{path}.json"
    s = _secret()
    return f"{base}?auth={s}" if s else base

def get(path: str):
    try:
        r = requests.get(_url(path), timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[FB GET] {path} → {e}")
        return None

def put(path: str, data):
    try:
        r = requests.put(_url(path), json=data, timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[FB PUT] {path} → {e}")
        return None

def patch(path: str, data: dict):
    try:
        r = requests.patch(_url(path), json=data, timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[FB PATCH] {path} → {e}")
        return None

def post(path: str, data):
    try:
        r = requests.post(_url(path), json=data, timeout=TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[FB POST] {path} → {e}")
        return None

def delete(path: str) -> bool:
    try:
        r = requests.delete(_url(path), timeout=TIMEOUT)
        return r.status_code == 200
    except Exception as e:
        print(f"[FB DEL] {path} → {e}")
        return False

def get_list(path: str) -> list:
    data = get(path)
    if not data or not isinstance(data, dict):
        return []
    return [{"_id": k, **v} if isinstance(v, dict) else {"_id": k, "value": v} for k, v in data.items()]

def cfg(key: str, default=None):
    """Read a single config value from /config/<key>."""
    try:
        val = get(f"config/{key}")
        return val if val is not None else default
    except:
        return default

def set_cfg(key: str, value):
    return put(f"config/{key}", value)

def get_config() -> dict:
    return get("config") or {}
