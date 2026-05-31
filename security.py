"""
security.py — Rate limiting, ban management, security utilities.
All limits are server-side (stored in Firebase for persistence across restarts).
"""
import time, hashlib, secrets, datetime, re
import firebase_helper as fb

# ── Admin login rate limiting ─────────────────────────────────────────────────
ADMIN_MAX_ATTEMPTS  = 5
ADMIN_LOCKOUT_SECS  = 3600  # 60 minutes

def check_admin_lockout(ip: str) -> tuple:
    """Returns (is_locked, seconds_remaining)."""
    key = ip.replace(".", "_").replace(":", "_")
    data = fb.get(f"admin_lockouts/{key}") or {}
    locked_until = data.get("locked_until", 0)
    now_ts = int(time.time())
    if locked_until > now_ts:
        return True, locked_until - now_ts
    return False, 0

def record_admin_fail(ip: str) -> int:
    """Record a failed admin login. Returns total attempts."""
    key = ip.replace(".", "_").replace(":", "_")
    data = fb.get(f"admin_lockouts/{key}") or {}
    now_ts = int(time.time())
    # Reset if previous lockout expired
    if data.get("locked_until", 0) < now_ts and data.get("locked_until", 0) != 0:
        data = {}
    attempts = data.get("attempts", 0) + 1
    update = {"attempts": attempts, "last_attempt": now_ts}
    if attempts >= ADMIN_MAX_ATTEMPTS:
        update["locked_until"] = now_ts + ADMIN_LOCKOUT_SECS
        update["attempts"] = 0
    fb.put(f"admin_lockouts/{key}", update)
    return attempts

def clear_admin_fails(ip: str):
    key = ip.replace(".", "_").replace(":", "_")
    fb.delete(f"admin_lockouts/{key}")

# ── KimiPay payment link rate limiting ───────────────────────────────────────
PAYMENT_COOLDOWN_SECS   = 900   # 15 minutes
MAX_PAYMENT_ATTEMPTS    = 3     # 3rd attempt = "try yesterday"

def check_payment_rate_limit(chat_id: str) -> dict:
    """
    Returns {"ok": True} or {"error": "...", "wait_secs": N}
    Logic:
      - 1st click: generate
      - 2nd click within 15min: "try after 15 minutes"
      - 3rd+ click even after 15min: "try yesterday"
    """
    data = fb.get(f"payment_attempts/{chat_id}") or {}
    now_ts = int(time.time())
    count      = data.get("count", 0)
    last_ts    = data.get("last_ts", 0)
    cooldown_end = last_ts + PAYMENT_COOLDOWN_SECS

    if count == 0:
        # First attempt
        fb.put(f"payment_attempts/{chat_id}", {"count": 1, "last_ts": now_ts})
        return {"ok": True, "attempt": 1}

    if count >= MAX_PAYMENT_ATTEMPTS:
        return {"error": "try_yesterday"}

    if now_ts < cooldown_end:
        wait = cooldown_end - now_ts
        return {"error": "wait", "wait_secs": wait}

    # Cooldown passed, allow generation but increment count
    new_count = count + 1
    fb.put(f"payment_attempts/{chat_id}", {"count": new_count, "last_ts": now_ts})
    return {"ok": True, "attempt": new_count}

def reset_payment_attempts(chat_id: str):
    fb.delete(f"payment_attempts/{chat_id}")

# ── Website access rate limiting ──────────────────────────────────────────────
WEB_KEY_MAX_WRONG   = 5
WEB_LOCKOUT_SECS    = 86400  # 24 hours

def check_key_ban(chat_id: str, device_fp: str) -> bool:
    """Check if chatid or device is permanently banned."""
    if fb.get(f"banned_users/{chat_id}"):
        return True
    if device_fp and fb.get(f"banned_devices/{device_fp}"):
        return True
    return False

def record_wrong_key(chat_id: str, device_fp: str, username: str,
                     full_name: str, ip: str) -> dict:
    """
    Record a wrong key attempt. Returns {"banned": True/False, "attempts": N}.
    After 5 wrong keys → permanent ban.
    """
    key_path = f"wrong_key_attempts/{chat_id}"
    data = fb.get(key_path) or {"count": 0}
    count = data.get("count", 0) + 1
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fb.put(key_path, {"count": count, "last_attempt": now_str})

    if count >= WEB_KEY_MAX_WRONG:
        # Permanently ban
        ban_data = {
            "chat_id":   chat_id,
            "username":  username,
            "full_name": full_name,
            "device_fp": device_fp,
            "ip":        ip,
            "banned_at": now_str,
            "reason":    "5 wrong license key attempts",
        }
        fb.put(f"banned_users/{chat_id}", ban_data)
        if device_fp:
            fb.put(f"banned_devices/{device_fp}", ban_data)
        fb.delete(key_path)
        return {"banned": True, "attempts": count}

    return {"banned": False, "attempts": count}

# ── Session tokens (website access) ──────────────────────────────────────────
TOKEN_EXPIRY_SECS = 600  # 10 minutes

def generate_site_token(chat_id: str) -> str:
    """Generate a secure one-time access token for website. Stored in Firebase."""
    token = secrets.token_urlsafe(24)
    now_ts = int(time.time())
    fb.put(f"site_tokens/{token}", {
        "chat_id":    chat_id,
        "created_at": now_ts,
        "expires_at": now_ts + TOKEN_EXPIRY_SECS,
        "used":       False,
    })
    return token

def verify_site_token(token: str, chat_id: str) -> bool:
    """Verify that token is valid for the given chatid. Tokens are single-use."""
    data = fb.get(f"site_tokens/{token}")
    if not data:
        return False
    if data.get("chat_id") != chat_id:
        return False
    if data.get("used"):
        return False
    if int(time.time()) > data.get("expires_at", 0):
        fb.delete(f"site_tokens/{token}")
        return False
    # Mark as used
    fb.patch(f"site_tokens/{token}", {"used": True})
    return True

def cleanup_old_tokens():
    """Delete expired tokens (call periodically)."""
    tokens = fb.get("site_tokens") or {}
    now_ts = int(time.time())
    for tok, data in tokens.items():
        if isinstance(data, dict) and data.get("expires_at", 0) < now_ts:
            fb.delete(f"site_tokens/{tok}")

# ── Device detection ──────────────────────────────────────────────────────────
def detect_device_type(user_agent: str) -> str:
    ua = user_agent.lower()
    if any(x in ua for x in ["android", "iphone", "ipad", "mobile", "blackberry"]):
        return "mobile"
    if "tablet" in ua:
        return "tablet"
    return "desktop"

# ── Input sanitisation ────────────────────────────────────────────────────────
def sanitize_str(s: str, max_len: int = 500) -> str:
    if not isinstance(s, str):
        return ""
    # Remove null bytes and control characters
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", s)
    return s[:max_len]

def validate_license_key_format(key: str) -> bool:
    """XXXX-XXXX-XXXX-XXXX pattern."""
    return bool(re.match(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", key.upper()))
