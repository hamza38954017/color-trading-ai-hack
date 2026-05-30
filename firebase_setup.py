# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PREDICTOR 4.0 — Firebase Database Setup                                   ║
# ║  Run this in Google Colab to initialise your Firebase Realtime Database     ║
# ║  No service account required — uses public rules                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ────────────────────────────────────────────────────────────────────────────
# CELL 1 — Install dependencies
# ────────────────────────────────────────────────────────────────────────────
# !pip install requests

import requests, json, datetime

# ────────────────────────────────────────────────────────────────────────────
# CELL 2 — CONFIG  ← only thing you need to change
# ────────────────────────────────────────────────────────────────────────────
FIREBASE_URL = "https://YOUR-PROJECT-default-rtdb.firebaseio.com"  # ← paste your URL
FIREBASE_SECRET = ""   # leave empty if rules are public; paste secret if private

TIMEOUT = 12

def fb_url(path):
    base = f"{FIREBASE_URL.rstrip('/')}/{path}.json"
    return f"{base}?auth={FIREBASE_SECRET}" if FIREBASE_SECRET else base

def put(path, data):
    r = requests.put(fb_url(path), json=data, timeout=TIMEOUT)
    if r.status_code == 200:
        print(f"  ✅  PUT  /{path}")
    else:
        print(f"  ❌  PUT  /{path}  →  {r.status_code}: {r.text[:120]}")
    return r.json() if r.status_code == 200 else None

def patch(path, data):
    r = requests.patch(fb_url(path), json=data, timeout=TIMEOUT)
    if r.status_code == 200:
        print(f"  ✅  PATCH /{path}")
    else:
        print(f"  ❌  PATCH /{path}  →  {r.status_code}: {r.text[:120]}")
    return r.json() if r.status_code == 200 else None

now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
today = datetime.datetime.now().strftime("%Y-%m-%d")

print("=" * 60)
print("  PREDICTOR 4.0 — Firebase Database Initialiser")
print("=" * 60)
print(f"  Target: {FIREBASE_URL}")
print()

# ────────────────────────────────────────────────────────────────────────────
# CELL 3 — Write default config
# ────────────────────────────────────────────────────────────────────────────
print("▶ Writing /config …")
put("config", {
    # ── Bot tokens (fill via Admin Panel or here) ───────────────────────────
    "bot_token":               "",
    "support_bot_token":       "",
    "bot_username":            "PredictorBot",
    "support_bot_username":    "PredictorSupportBot",

    # ── Channel ──────────────────────────────────────────────────────────────
    "channel_id":              "",
    "channel_invite":          "https://t.me/",

    # ── Admin ────────────────────────────────────────────────────────────────
    "admin_chat_id":           "",
    "admin_username":          "admin",
    "admin_password":          "Admin@2026",
    "notify_chat_ids":         "",
    "support_notify_chat_ids": "",

    # ── URLs ─────────────────────────────────────────────────────────────────
    "site_url":    "https://your-app.onrender.com",
    "panel_url":   "https://your-app.onrender.com",

    # ── KimiPay ──────────────────────────────────────────────────────────────
    "kimipay_app_id":  "",
    "kimipay_api_key": "",
    "kimipay_base_url": "https://kimipay.in/api",

    # ── Finance ──────────────────────────────────────────────────────────────
    "refer_commission": 10,
    "min_withdrawal":   100,
    "max_withdrawal":   50000,

    # ── Legal ─────────────────────────────────────────────────────────────────
    "privacy_policy": (
        "🔒 *Privacy Policy — Predictor 4.0*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "We collect your Telegram Chat ID, username, and full name solely to provide "
        "the service. Your data is never sold or shared with third parties.\n\n"
        "• License key data is encrypted and stored securely.\n"
        "• Payment data is handled by KimiPay and never stored on our servers.\n"
        "• You may request deletion of your data at any time via support.\n\n"
        "_Last updated: 2026_"
    ),
    "terms_conditions": (
        "📋 *Terms & Conditions — Predictor 4.0*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1. License keys are non-transferable and tied to your Telegram account.\n"
        "2. Attempting to share, resell, or misuse a license key will result in a permanent ban.\n"
        "3. Refunds are not offered after key delivery.\n"
        "4. We reserve the right to ban accounts that violate these terms.\n"
        "5. By using this service you agree to all terms.\n\n"
        "_Last updated: 2026_"
    ),
    "support_greeting": (
        "👋 *Welcome to Predictor 4.0 Support!*\n\n"
        "Please describe your issue clearly.\n"
        "Our team will respond as soon as possible.\n\n"
        "📌 _Include your Order ID or Chat ID for faster help._"
    ),
    "support_auto_reply": "",
})

# ────────────────────────────────────────────────────────────────────────────
# CELL 4 — Website settings (controls website UI text)
# ────────────────────────────────────────────────────────────────────────────
print("\n▶ Writing /settings …")
put("settings", {
    "homeVersionBadge":  "VERSION 4.0",
    "homeTitleWord":     "PREDICTOR",
    "homeTitleNum":      "4.0",
    "homeSubtitle":      "ALL GAMES CONNECTED • DIRECT API SERVER",
    "appMainTitle":      "WINGO\nTRADING",
    "appMainSub":        "SELECT YOUR NODE AND SYNC DURATION",
    "tickerText": (
        "OG Owner: @PredictorApp 💎 | "
        "SECURE CONNECTION ✅ | "
        "ALL GAMES CONNECTED ⚡ | "
        "DIRECT API 🚀 | "
        "PREDICTOR 4.0 🔥 | "
        "NEW VERSION LIVE 🎯 | "
        "JOIN OUR CHANNEL 📢"
    ),
    "protocols": [
        "We do NOT request game deposits or promote external gambling.",
        "Old versions of this app are deprecated — anyone selling them is a SCAM.",
        "Purchase license keys ONLY through the official Telegram bot.",
    ],
    "joinChannelUrl":     "https://t.me/",
    "contactUrl":         "https://t.me/",
    "serverStatus":       "Active",
    "predictionLimit":    "Unlimited",
    "maintenanceMode":    False,
    "maintenanceMessage": "PREDICTOR 4.0 is temporarily offline. Please check back shortly.",
})

# ────────────────────────────────────────────────────────────────────────────
# CELL 5 — Placeholder nodes (so Firebase shows all paths)
# ────────────────────────────────────────────────────────────────────────────
print("\n▶ Creating placeholder nodes …")

nodes = {
    "users":            {"_init": True},
    "licenses":         {"_init": True},
    "user_licenses":    {"_init": True},
    "pending_payments": {"_init": True},
    "withdrawals":      {"_init": True},
    "referrals":        {"_init": True},
    "refer_codes":      {"_init": True},
    "support":          {"_init": True},
    "banned_users":     {"_init": True},
    "banned_devices":   {"_init": True},
    "access_logs":      {"_init": True},
    "site_tokens":      {"_init": True},
    "wrong_key_attempts":{"_init": True},
    "payment_attempts": {"_init": True},
    "admin_lockouts":   {"_init": True},
    "broadcast_history":{"_init": True},
}
for path, val in nodes.items():
    patch(path, val)

# ────────────────────────────────────────────────────────────────────────────
# CELL 6 — Daily stats seed
# ────────────────────────────────────────────────────────────────────────────
print(f"\n▶ Seeding daily_stats for today ({today}) …")
put(f"daily_stats/{today}", {
    "date":              today,
    "new_users":         0,
    "returning_visits":  0,
})

# ────────────────────────────────────────────────────────────────────────────
# CELL 7 — Verify: read back config
# ────────────────────────────────────────────────────────────────────────────
print("\n▶ Verifying — reading back /config …")
r = requests.get(fb_url("config"), timeout=TIMEOUT)
if r.status_code == 200:
    cfg = r.json()
    print(f"  ✅  Config keys present: {sorted(cfg.keys())}")
else:
    print(f"  ❌  Could not read config: {r.status_code}")

print()
print("=" * 60)
print("  ✅  Firebase database structure initialised!")
print()
print("  NEXT STEPS:")
print("  1. Deploy the app to Render / Railway / VPS")
print("  2. Set env vars: FIREBASE_URL, SECRET_KEY (see .env.example)")
print("  3. Open /admin/login — enter admin / Admin@2026 + your Chat ID")
print("  4. In Admin Panel → Settings, fill in:")
print("     • BOT_TOKEN, SUPPORT_BOT_TOKEN")
print("     • CHANNEL_ID, CHANNEL_INVITE")
print("     • ADMIN_CHAT_ID (your Telegram numeric ID)")
print("     • SITE_URL (your deployed URL)")
print("     • KIMIPAY_APP_ID, KIMIPAY_API_KEY")
print("  5. Send /start to your bot in Telegram")
print("=" * 60)
