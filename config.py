"""
config.py — Runtime configuration (reads live from Firebase + env vars).
"""
import os
import firebase_helper as fb

# ── Environment vars ─────────────────────────────────────────────────────────
FIREBASE_URL    = os.environ.get("FIREBASE_URL", "")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")
SECRET_KEY      = os.environ.get("SECRET_KEY", "predictor-secret-2026-change-me")
FLASK_PORT      = int(os.environ.get("PORT", 5000))

# ── Live config helpers ───────────────────────────────────────────────────────
def BOT_TOKEN():
    return (os.environ.get("BOT_TOKEN", "") or fb.cfg("bot_token", "")).strip()

def SUPPORT_BOT_TOKEN():
    return (os.environ.get("SUPPORT_BOT_TOKEN", "") or fb.cfg("support_bot_token", "")).strip()

def BOT_USERNAME():         return fb.cfg("bot_username", "PredictorBot")
def CHANNEL_ID():           return fb.cfg("channel_id", "")
def CHANNEL_INVITE():       return fb.cfg("channel_invite", "https://t.me/")
def ADMIN_CHAT_ID():        return str(fb.cfg("admin_chat_id", ""))
def ADMIN_USERNAME():
    v = fb.cfg("admin_username", "")
    return v if v else os.environ.get("ADMIN_USERNAME", "admin")
def ADMIN_PASSWORD():
    v = fb.cfg("admin_password", "")
    return v if v else os.environ.get("ADMIN_PASSWORD", "Admin@2026")
def NOTIFY_CHAT_IDS():
    raw = fb.cfg("notify_chat_ids", "")
    if not raw: return [ADMIN_CHAT_ID()] if ADMIN_CHAT_ID() else []
    return [x.strip() for x in str(raw).split(",") if x.strip()]
def SUPPORT_NOTIFY_CHAT_IDS():
    raw = fb.cfg("support_notify_chat_ids", "")
    if raw:
        return [x.strip() for x in str(raw).split(",") if x.strip()]
    return NOTIFY_CHAT_IDS()
def SITE_URL():             return fb.cfg("site_url", "http://localhost:5000")
def REFER_COMMISSION():     return float(fb.cfg("refer_commission", 10))
def MIN_WITHDRAWAL():       return int(fb.cfg("min_withdrawal", 100))
def MAX_WITHDRAWAL():       return int(fb.cfg("max_withdrawal", 50000))
def PRIVACY_POLICY():       return fb.cfg("privacy_policy", "🔒 *Privacy Policy*\n\nYour data is stored securely and never shared with third parties.")
def TERMS_CONDITIONS():     return fb.cfg("terms_conditions", "📋 *Terms & Conditions*\n\nBy using this service you agree to our terms.")
def SUPPORT_GREETING():     return fb.cfg("support_greeting", "👋 *Welcome to Support!*\n\nPlease describe your issue.")
def PANEL_URL():            return fb.cfg("panel_url", "")

# License plans (rupees)
LICENSE_PLANS = {
    "7day":    {"label": "7 Days",    "days": 7,  "amount": 2000},
    "15day":   {"label": "15 Days",   "days": 15, "amount": 5000},
    "1month":  {"label": "1 Month",   "days": 30, "amount": 8000},
}
