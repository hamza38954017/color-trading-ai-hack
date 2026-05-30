"""
app.py — Flask Application
Routes:
  /             → Website home (requires chatid+token OR shows browser error)
  /app          → Predictor website
  /api/*        → Website API (key validation, logging, etc.)
  /admin/*      → Admin panel
  /support/*    → Customer support routes
  /kimipay_webhook → Payment callback
"""
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, url_for, send_from_directory, abort, make_response)
from functools import wraps
import datetime, threading, os, time, json, secrets, hashlib
import firebase_helper as fb
import kimipay as kp
import security
import bot as main_bot
import support_bot as sb
from config import (
    SECRET_KEY, FLASK_PORT, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_CHAT_ID,
    NOTIFY_CHAT_IDS, LICENSE_PLANS, REFER_COMMISSION, SITE_URL,
)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16 MB max upload
)

# ── Security headers middleware ───────────────────────────────────────────────
@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"]        = "DENY"
    resp.headers["X-XSS-Protection"]       = "1; mode=block"
    resp.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    return resp

def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def now_ts():  return int(time.time())
def fmt_inr(v):
    try: return f"₹{float(v):,.0f}"
    except: return f"₹{v}"

# ── Get real IP ───────────────────────────────────────────────────────────────
def get_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else request.remote_addr

# ── Rate limiter (simple per-IP in-memory, backed by Firebase for persistence)
_rate_cache = {}

def rate_limit(max_calls: int, period_secs: int):
    """Decorator. Returns 429 if exceeded. Keyed by IP."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip  = get_ip()
            key = f"{f.__name__}:{ip}"
            now = time.time()
            history = _rate_cache.get(key, [])
            history = [t for t in history if now - t < period_secs]
            if len(history) >= max_calls:
                return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
            history.append(now)
            _rate_cache[key] = history
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ══════════════════════════════════════════════════════════════════════════════
# WEBSITE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Redirect to Telegram bot if accessed directly."""
    bot_username = fb.cfg("bot_username") or "PredictorBot"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Predictor App</title>
<style>body{{margin:0;background:#050807;color:#00ff41;font-family:monospace;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid #00ff4155;padding:40px 30px;max-width:400px}}
h2{{font-size:22px;margin-bottom:16px}}p{{color:#a0a0a0;margin-bottom:24px;line-height:1.6}}
a{{display:inline-block;background:#00ff41;color:#050807;font-weight:700;
padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:2px}}</style>
</head><body><div class="box">
<h2>⚠️ BROWSER ACCESS DENIED</h2>
<p>This application can only be accessed through the official Telegram bot.<br><br>
You cannot open this website directly from a browser.</p>
<a href="https://t.me/{bot_username}">OPEN IN TELEGRAM</a>
</div></body></html>""", 200

@app.route("/app")
@rate_limit(30, 60)
def predictor_app():
    """Serve the predictor website — requires valid chatid + token."""
    chat_id = security.sanitize_str(request.args.get("chatid", ""), 20)
    token   = security.sanitize_str(request.args.get("t", ""), 60)

    bot_username = fb.cfg("bot_username") or "PredictorBot"

    if not chat_id or not token:
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Access Denied</title>
<style>body{{margin:0;background:#050807;color:#00ff41;font-family:monospace;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid #ff003355;padding:40px 30px;max-width:400px}}
h2{{color:#ff0033;font-size:22px;margin-bottom:16px}}
p{{color:#a0a0a0;margin-bottom:24px;line-height:1.6}}
a{{display:inline-block;background:#00ff41;color:#050807;font-weight:700;
padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:2px}}</style>
</head><body><div class="box">
<h2>⚠️ ACCESS DENIED</h2>
<p>You can't access this application from a browser.<br><br>
Use it from the official Telegram bot.</p>
<a href="https://t.me/{bot_username}">OPEN TELEGRAM BOT</a>
</div></body></html>""", 403

    # Verify token
    if not security.verify_site_token(token, chat_id):
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link Expired</title>
<style>body{{margin:0;background:#050807;color:#00ff41;font-family:monospace;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid #ff8c0055;padding:40px 30px;max-width:400px}}
h2{{color:orange;font-size:22px;margin-bottom:16px}}
p{{color:#a0a0a0;margin-bottom:24px;line-height:1.6}}
a{{display:inline-block;background:#00ff41;color:#050807;font-weight:700;
padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:2px}}</style>
</head><body><div class="box">
<h2>⏳ LINK EXPIRED</h2>
<p>This link has expired or already been used.<br><br>
Go to the Telegram bot and click <b>License Key</b> to get a new link.</p>
<a href="https://t.me/{bot_username}">OPEN TELEGRAM BOT</a>
</div></body></html>""", 403

    # Check ban
    if security.check_key_ban(chat_id, ""):
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Banned</title>
<style>body{{margin:0;background:#050807;color:#ff0033;font-family:monospace;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid #ff003355;padding:40px 30px;max-width:400px}}
h2{{font-size:22px;margin-bottom:16px}}p{{color:#a0a0a0}}</style>
</head><body><div class="box">
<h2>🚫 ACCOUNT BANNED</h2>
<p>Your account has been permanently banned.<br>Contact support if you believe this is a mistake.</p>
</div></body></html>""", 403

    # Look up user info for embedding in page
    user = fb.get(f"users/{chat_id}") or {}
    display_name = user.get("first_name") or user.get("full_name") or chat_id

    # Serve the predictor website with embedded chatid
    site_settings = fb.get("settings") or {}
    return render_template("predictor.html",
        chat_id=chat_id,
        display_name=display_name,
        fb_url=os.environ.get("FIREBASE_URL", ""),
        site_settings=json.dumps(site_settings),
    )

@app.route("/api/validate_key", methods=["POST"])
@rate_limit(10, 60)
def api_validate_key():
    """Validate a license key from the website."""
    data      = request.get_json(silent=True) or {}
    key_raw   = security.sanitize_str(data.get("key", ""), 25).upper().strip()
    chat_id   = security.sanitize_str(data.get("chat_id", ""), 20)
    device_fp = security.sanitize_str(data.get("device_fp", ""), 100)
    ip        = get_ip()
    ua        = request.headers.get("User-Agent", "")

    if not key_raw or not chat_id:
        return jsonify({"error": "missing_params"}), 400

    # Check if chatid is banned
    if security.check_key_ban(chat_id, device_fp):
        return jsonify({"error": "banned", "message": "Your account has been banned."}), 403

    if not security.validate_license_key_format(key_raw):
        return jsonify({"error": "invalid_format", "message": "Invalid key format."}), 400

    fb_key = key_raw.replace("-", "_")
    lic    = fb.get(f"licenses/{fb_key}")

    if not lic:
        result = security.record_wrong_key(chat_id, device_fp, "", "", ip)
        if result["banned"]:
            return jsonify({"error": "banned", "message": "Account permanently banned (5 wrong keys)."}), 403
        return jsonify({"error": "not_found", "message": "Key not found.", "attempts": result["attempts"]}), 404

    if not lic.get("active"):
        result = security.record_wrong_key(chat_id, device_fp, "", "", ip)
        if result["banned"]:
            return jsonify({"error": "banned", "message": "Account permanently banned."}), 403
        return jsonify({"error": "inactive", "message": "This key is inactive.", "attempts": result["attempts"]}), 403

    if lic.get("expiry", 0) < now_ts():
        return jsonify({"error": "expired", "message": "This key has expired."}), 403

    # Check chatid ownership
    if lic.get("chat_id") and str(lic["chat_id"]) != str(chat_id):
        result = security.record_wrong_key(chat_id, device_fp, "", "", ip)
        if result["banned"]:
            return jsonify({"error": "banned", "message": "Account permanently banned."}), 403
        return jsonify({
            "error": "device_mismatch",
            "message": "This key is registered on another account/device.",
            "attempts": result["attempts"],
        }), 403

    # Bind device fingerprint if not yet set
    if not lic.get("device_fp") and device_fp:
        fb.patch(f"licenses/{fb_key}", {"device_fp": device_fp, "chat_id": chat_id})
    elif lic.get("device_fp") and lic["device_fp"] != device_fp:
        # Different browser fingerprint — same chatid is OK, just log it
        pass

    expiry_dt = datetime.datetime.fromtimestamp(lic["expiry"])
    expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M")

    # Store access log
    log_id = f"{now_ts()}_{chat_id}"
    fb.put(f"access_logs/{log_id}", {
        "chat_id":     chat_id,
        "username":    lic.get("username", ""),
        "full_name":   lic.get("full_name", ""),
        "device_fp":   device_fp,
        "ip":          ip,
        "user_agent":  ua[:200],
        "device_type": security.detect_device_type(ua),
        "time":        now_str(),
        "ts":          now_ts(),
        "action":      "key_validated",
    })

    # Track today's returning user
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    fb.patch(f"daily_stats/{today}", {
        "returning_visits": (fb.get(f"daily_stats/{today}/returning_visits") or 0) + 1,
        "date": today,
    })

    # Clear wrong-key counter on success
    fb.delete(f"wrong_key_attempts/{chat_id}")

    return jsonify({
        "success":     True,
        "client_name": lic.get("full_name") or lic.get("username") or chat_id,
        "expiry_str":  expiry_str,
        "plan":        lic.get("plan_label", ""),
    })

@app.route("/api/log_access", methods=["POST"])
@rate_limit(20, 60)
def api_log_access():
    """Log page access from the website."""
    data      = request.get_json(silent=True) or {}
    chat_id   = security.sanitize_str(data.get("chat_id", ""), 20)
    device_fp = security.sanitize_str(data.get("device_fp", ""), 100)
    ip        = get_ip()
    ua        = request.headers.get("User-Agent", "")

    if not chat_id: return jsonify({"ok": False}), 400

    user = fb.get(f"users/{chat_id}") or {}
    log_id = f"{now_ts()}_{chat_id}"
    fb.put(f"access_logs/{log_id}", {
        "chat_id":     chat_id,
        "username":    user.get("username", ""),
        "full_name":   user.get("full_name", ""),
        "device_fp":   device_fp,
        "ip":          ip,
        "user_agent":  ua[:200],
        "device_type": security.detect_device_type(ua),
        "time":        now_str(),
        "ts":          now_ts(),
        "action":      "page_view",
    })
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# KIMIPAY WEBHOOK
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/kimipay_webhook", methods=["POST"])
@rate_limit(60, 60)
def kimipay_webhook():
    data = request.get_json(silent=True) or request.form.to_dict()
    main_bot.handle_kimipay_webhook(data)
    return "ok", 200

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/admin/login", methods=["GET", "POST"])
@rate_limit(20, 60)
def admin_login():
    ip = get_ip()
    locked, wait_secs = security.check_admin_lockout(ip)
    if locked:
        # Return generic error to avoid revealing lock info
        if request.method == "POST":
            return jsonify({"error": "API service temporarily unavailable."}), 503
        return render_template("admin_login.html", error="⚠️ API service temporarily unavailable. Try again later.", locked=True)

    if request.method == "GET":
        return render_template("admin_login.html", error="", locked=False)

    uname   = security.sanitize_str(request.form.get("username", ""), 50)
    passwd  = security.sanitize_str(request.form.get("password", ""), 100)
    chat_id = security.sanitize_str(request.form.get("chat_id", ""), 20)

    expected_user   = ADMIN_USERNAME()
    expected_pass   = ADMIN_PASSWORD()
    expected_chatid = ADMIN_CHAT_ID()

    if (uname == expected_user and passwd == expected_pass
            and str(chat_id) == str(expected_chatid)):
        security.clear_admin_fails(ip)
        session["admin_logged_in"] = True
        session["admin_ip"]        = ip
        return redirect(url_for("admin_dashboard"))
    else:
        attempts = security.record_admin_fail(ip)
        rem = max(0, security.ADMIN_MAX_ATTEMPTS - attempts)
        error = f"❌ Invalid credentials. {rem} attempts remaining." if rem > 0 else "❌ Too many failed attempts."
        return render_template("admin_login.html", error=error, locked=False)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@app.route("/admin/")
@admin_required
def admin_dashboard():
    """Main admin panel — single-page app."""
    return render_template("admin_panel.html")

# ── Admin API endpoints ───────────────────────────────────────────────────────

@app.route("/admin/api/dashboard")
@admin_required
@rate_limit(30, 60)
def api_dashboard():
    users    = fb.get("users") or {}
    licenses = fb.get("licenses") or {}
    payments = fb.get("pending_payments") or {}
    withdrawals = fb.get("withdrawals") or {}
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_stats = fb.get(f"daily_stats/{today}") or {}

    total_income = sum(
        p.get("amount", 0) for p in payments.values() if p.get("is_paid")
    )
    pending_wds  = sum(
        1 for w in withdrawals.values() if w.get("status") == "pending"
    )
    paid_count   = sum(1 for p in payments.values() if p.get("is_paid"))
    active_lic   = sum(
        1 for l in licenses.values()
        if isinstance(l, dict) and l.get("active") and l.get("expiry", 0) > now_ts()
    )
    banned = fb.get("banned_users") or {}

    return jsonify({
        "total_users":     len(users),
        "total_licenses":  len(licenses),
        "active_licenses": active_lic,
        "total_income_inr": fmt_inr(total_income),
        "paid_count":      paid_count,
        "pending_withdrawals": pending_wds,
        "banned_users":    len(banned),
        "new_users_today": today_stats.get("new_users", 0),
        "visits_today":    today_stats.get("returning_visits", 0),
        "income_raw":      total_income,
    })

@app.route("/admin/api/users")
@admin_required
@rate_limit(20, 60)
def api_users():
    users = fb.get("users") or {}
    result = []
    for cid, u in users.items():
        banned = bool(fb.get(f"banned_users/{cid}"))
        result.append({
            "chat_id":     cid,
            "full_name":   u.get("full_name", ""),
            "username":    u.get("username", ""),
            "wallet":      u.get("wallet", 0),
            "total_spent": u.get("total_spent", 0),
            "refer_count": u.get("refer_count", 0),
            "purchase_count": u.get("purchase_count", 0),
            "created_at":  u.get("created_at", ""),
            "last_seen":   u.get("last_seen", ""),
            "banned":      banned,
        })
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(result)

@app.route("/admin/api/users/<cid>", methods=["GET", "PATCH"])
@admin_required
@rate_limit(20, 60)
def api_user(cid):
    if request.method == "GET":
        u = fb.get(f"users/{cid}")
        if not u: return jsonify({"error": "not found"}), 404
        return jsonify(u)
    # PATCH - update user
    data = request.get_json(silent=True) or {}
    allowed = {"full_name","username","wallet","referred_by"}
    update  = {k: v for k, v in data.items() if k in allowed}
    if update:
        fb.patch(f"users/{cid}", update)
    return jsonify({"ok": True})

@app.route("/admin/api/users/<cid>/ban", methods=["POST"])
@admin_required
def api_ban_user(cid):
    u = fb.get(f"users/{cid}") or {}
    fb.put(f"banned_users/{cid}", {
        "chat_id":   cid,
        "username":  u.get("username",""),
        "full_name": u.get("full_name",""),
        "banned_at": now_str(),
        "reason":    security.sanitize_str(request.json.get("reason","Admin ban") if request.is_json else "Admin ban", 200),
    })
    return jsonify({"ok": True})

@app.route("/admin/api/users/<cid>/unban", methods=["POST"])
@admin_required
def api_unban_user(cid):
    fb.delete(f"banned_users/{cid}")
    fb.delete(f"wrong_key_attempts/{cid}")
    return jsonify({"ok": True})

@app.route("/admin/api/licenses")
@admin_required
@rate_limit(20, 60)
def api_licenses():
    lics = fb.get("licenses") or {}
    result = []
    for lid, l in lics.items():
        if not isinstance(l, dict): continue
        expiry_ts  = l.get("expiry", 0)
        expired    = expiry_ts < now_ts()
        expiry_str = datetime.datetime.fromtimestamp(expiry_ts).strftime("%Y-%m-%d %H:%M") if expiry_ts else "?"
        result.append({
            "_id":        lid,
            "key":        l.get("key", ""),
            "chat_id":    l.get("chat_id", ""),
            "username":   l.get("username", ""),
            "full_name":  l.get("full_name", ""),
            "plan_label": l.get("plan_label", ""),
            "amount":     l.get("amount", 0),
            "amount_str": fmt_inr(l.get("amount", 0)),
            "active":     l.get("active", False) and not expired,
            "expired":    expired,
            "expiry_str": expiry_str,
            "purchase_date": l.get("purchase_date", ""),
            "created_by": l.get("created_by", ""),
        })
    result.sort(key=lambda x: x.get("purchase_date",""), reverse=True)
    return jsonify(result)

@app.route("/admin/api/licenses/create", methods=["POST"])
@admin_required
@rate_limit(10, 60)
def api_create_license():
    from bot import gen_key
    import random, string
    data       = request.get_json(silent=True) or {}
    chat_id    = security.sanitize_str(str(data.get("chat_id","")), 20)
    username   = security.sanitize_str(data.get("username",""), 50)
    full_name  = security.sanitize_str(data.get("full_name",""), 100)
    plan_id    = security.sanitize_str(data.get("plan_id","7day"), 20)
    plan       = LICENSE_PLANS.get(plan_id, LICENSE_PLANS["7day"])

    key = gen_key()
    while fb.get(f"licenses/{key.replace('-','_')}"):
        key = gen_key()

    expiry_ts  = now_ts() + plan["days"] * 86400
    expiry_dt  = datetime.datetime.fromtimestamp(expiry_ts)
    expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M")

    lic_data = {
        "key":           key,
        "chat_id":       chat_id,
        "username":      username,
        "full_name":     full_name,
        "plan_id":       plan_id,
        "plan_label":    plan["label"],
        "amount":        plan["amount"],
        "validity_days": plan["days"],
        "purchase_date": now_str(),
        "expiry":        expiry_ts,
        "expiry_str":    expiry_str,
        "active":        True,
        "device_fp":     "",
        "created_by":    "admin",
    }
    fb.put(f"licenses/{key.replace('-','_')}", lic_data)
    if chat_id:
        fb.put(f"user_licenses/{chat_id}/{key.replace('-','_')}", lic_data)
        fb.patch(f"users/{chat_id}", {"active_license": key})

    return jsonify({"ok": True, "key": key, "expiry_str": expiry_str})

@app.route("/admin/api/licenses/<lid>", methods=["PATCH"])
@admin_required
@rate_limit(20, 60)
def api_update_license(lid):
    data    = request.get_json(silent=True) or {}
    allowed = {"active","full_name","username","chat_id","expiry","plan_label","amount"}
    update  = {k: v for k, v in data.items() if k in allowed}
    if update:
        fb.patch(f"licenses/{lid}", update)
    return jsonify({"ok": True})

@app.route("/admin/api/licenses/<lid>/revoke", methods=["POST"])
@admin_required
def api_revoke_license(lid):
    fb.patch(f"licenses/{lid}", {"active": False})
    return jsonify({"ok": True})

@app.route("/admin/api/payments")
@admin_required
@rate_limit(20, 60)
def api_payments():
    payments = fb.get("pending_payments") or {}
    result   = [
        {
            "order_sn":   p.get("order_sn",""),
            "chat_id":    p.get("chat_id",""),
            "username":   p.get("username",""),
            "full_name":  p.get("full_name",""),
            "amount":     p.get("amount",0),
            "amount_str": fmt_inr(p.get("amount",0)),
            "is_paid":    p.get("is_paid",False),
            "payment_url": p.get("payment_url",""),
            "plan_label": p.get("plan_label",""),
            "created_at": p.get("created_at",""),
        }
        for p in payments.values() if isinstance(p, dict)
    ]
    result.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return jsonify(result)

@app.route("/admin/api/withdrawals")
@admin_required
@rate_limit(20, 60)
def api_withdrawals():
    wds = fb.get("withdrawals") or {}
    result = [
        {
            "_id":       w.get("wd_id",""),
            "chat_id":   w.get("chat_id",""),
            "username":  w.get("username",""),
            "full_name": w.get("full_name",""),
            "amount":    w.get("amount",0),
            "amount_str": fmt_inr(w.get("amount",0)),
            "account":   w.get("account",""),
            "status":    w.get("status","pending"),
            "created_at": w.get("created_at",""),
        }
        for w in wds.values() if isinstance(w, dict)
    ]
    result.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return jsonify(result)

@app.route("/admin/api/withdrawals/<wid>", methods=["PATCH"])
@admin_required
@rate_limit(10, 60)
def api_update_withdrawal(wid):
    data = request.get_json(silent=True) or {}
    new_status = security.sanitize_str(data.get("status",""), 20)
    if new_status not in ("pending","approved","rejected"):
        return jsonify({"error":"invalid status"}), 400
    wd = fb.get(f"withdrawals/{wid}") or {}
    fb.patch(f"withdrawals/{wid}", {"status": new_status, "updated_at": now_str()})
    cid = wd.get("chat_id")
    if cid:
        u = fb.get(f"users/{cid}") or {}
        if new_status == "rejected":
            # Refund wallet
            fb.patch(f"users/{cid}", {"wallet": u.get("wallet",0) + wd.get("amount",0)})
        # Notify user
        icons = {"approved":"✅","rejected":"❌","pending":"⏳"}
        try:
            main_bot.bot.send_message(cid,
                f"{icons.get(new_status,'📋')} *Withdrawal Update*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Amount: {fmt_inr(wd.get('amount',0))}\n"
                f"📊 Status: *{new_status.upper()}*\n"
                f"🔖 ID: `{wid}`",
                parse_mode="Markdown")
        except: pass
    return jsonify({"ok": True})

@app.route("/admin/api/banned")
@admin_required
@rate_limit(20, 60)
def api_banned():
    banned = fb.get("banned_users") or {}
    return jsonify(list(banned.values()))

@app.route("/admin/api/logs")
@admin_required
@rate_limit(10, 60)
def api_logs():
    logs = fb.get("access_logs") or {}
    result = sorted(
        [v for v in logs.values() if isinstance(v, dict)],
        key=lambda x: x.get("ts", 0), reverse=True
    )[:200]
    return jsonify(result)

@app.route("/admin/api/referrals")
@admin_required
@rate_limit(20, 60)
def api_referrals():
    refs = fb.get("referrals") or {}
    result = []
    for owner_id, referrals in refs.items():
        if not isinstance(referrals, dict): continue
        owner = fb.get(f"users/{owner_id}") or {}
        for ref_id, ref_data in referrals.items():
            result.append({
                "owner_id":   owner_id,
                "owner_name": owner.get("full_name",""),
                "ref_id":     ref_id,
                "ref_name":   ref_data.get("name",""),
                "status":     ref_data.get("status","pending"),
                "earned":     ref_data.get("earned",0),
                "earned_str": fmt_inr(ref_data.get("earned",0)),
                "joined_at":  ref_data.get("joined_at",""),
            })
    result.sort(key=lambda x: x.get("joined_at",""), reverse=True)
    return jsonify(result)

@app.route("/admin/api/daily_stats")
@admin_required
@rate_limit(20, 60)
def api_daily_stats():
    stats = fb.get("daily_stats") or {}
    result = sorted(stats.values(), key=lambda x: x.get("date","") if isinstance(x,dict) else "", reverse=True)
    return jsonify(result)

@app.route("/admin/api/settings", methods=["GET", "POST"])
@admin_required
@rate_limit(20, 60)
def api_settings():
    if request.method == "GET":
        cfg = fb.get_config()
        return jsonify(cfg)
    data    = request.get_json(silent=True) or {}
    allowed = {
        "bot_token","support_bot_token","bot_username","support_bot_username",
        "channel_id","channel_invite","admin_chat_id","admin_username","admin_password",
        "notify_chat_ids","support_notify_chat_ids","site_url","panel_url",
        "kimipay_app_id","kimipay_api_key","kimipay_base_url",
        "refer_commission","min_withdrawal","max_withdrawal",
        "privacy_policy","terms_conditions","support_greeting","support_auto_reply",
        "maintenanceMode","maintenanceMessage","tickerText","protocols",
        "homeVersionBadge","homeTitleWord","homeTitleNum","homeSubtitle",
        "appMainTitle","appMainSub","joinChannelUrl","contactUrl",
        "serverStatus","predictionLimit",
    }
    update = {k: v for k, v in data.items() if k in allowed}
    for k, v in update.items():
        fb.put(f"config/{k}", v)
    return jsonify({"ok": True})

@app.route("/admin/api/website_settings", methods=["GET","POST"])
@admin_required
@rate_limit(20, 60)
def api_website_settings():
    if request.method == "GET":
        s = fb.get("settings") or {}
        return jsonify(s)
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        fb.patch("settings", {k: v})
    return jsonify({"ok": True})

@app.route("/admin/api/broadcast", methods=["POST"])
@admin_required
@rate_limit(2, 60)
def api_broadcast():
    text         = security.sanitize_str(request.form.get("text",""), 4000)
    image_url    = security.sanitize_str(request.form.get("image_url",""), 500)
    btn_text     = security.sanitize_str(request.form.get("btn_text",""), 100)
    btn_url      = security.sanitize_str(request.form.get("btn_url",""), 500)
    target       = request.form.get("target","main")   # main | support | both
    image_bytes  = None

    if "image" in request.files:
        f = request.files["image"]
        if f and f.filename:
            image_bytes = f.read()

    if not text and not image_url and not image_bytes:
        return jsonify({"error":"No content to broadcast"}), 400

    ok = fail = 0
    if target in ("main","both"):
        o, f_ = main_bot.broadcast_message(
            text=text, image_url=image_url or None, image_bytes=image_bytes,
            inline_btn_text=btn_text or None, inline_btn_url=btn_url or None)
        ok += o; fail += f_

    if target in ("support","both"):
        sup_users = fb.get("support") or {}
        chat_ids  = list(sup_users.keys())
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        mk = None
        if btn_text and btn_url:
            mk = InlineKeyboardMarkup()
            mk.add(InlineKeyboardButton(btn_text, url=btn_url))
        for cid in chat_ids:
            try:
                if image_bytes:
                    import io; f2 = io.BytesIO(image_bytes); f2.name="img.jpg"
                    sb.support_bot.send_photo(cid, f2, caption=text or None, parse_mode="Markdown", reply_markup=mk)
                elif image_url:
                    sb.support_bot.send_photo(cid, image_url, caption=text or None, parse_mode="Markdown", reply_markup=mk)
                elif text:
                    sb.support_bot.send_message(cid, text, parse_mode="Markdown", reply_markup=mk)
                ok += 1; time.sleep(0.04)
            except Exception as e:
                print(f"[SUPPORT_BC] {cid}: {e}"); fail += 1

    return jsonify({"ok": True, "sent": ok, "failed": fail})

# ══════════════════════════════════════════════════════════════════════════════
# SUPPORT ROUTES (identical to ownshop)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/support")
@admin_required
def support_list():
    raw = fb.get("support") or {}
    chats = sorted(
        [d.get("meta",{}) for d in raw.values() if isinstance(d,dict) and d.get("meta")],
        key=lambda c: c.get("last_ts",0), reverse=True
    )
    return render_template("support.html", chats=chats)

@app.route("/support/<cid>")
@admin_required
def support_chat(cid):
    meta = fb.get(f"support/{cid}/meta") or {}
    raw  = fb.get(f"support/{cid}/messages") or {}
    msgs = sorted(raw.values(), key=lambda m: m.get("ts",0))
    return render_template("support_chat.html", cid=cid, meta=meta, messages=msgs)

@app.route("/support/<cid>/send", methods=["POST"])
@admin_required
@rate_limit(30, 60)
def support_send(cid):
    text      = security.sanitize_str(request.form.get("text",""), 4000)
    image_url = security.sanitize_str(request.form.get("image_url",""), 500)
    return jsonify(sb.admin_reply(cid, text, image_url))

@app.route("/support/<cid>/send_file", methods=["POST"])
@admin_required
@rate_limit(10, 60)
def support_send_file(cid):
    f = request.files.get("file")
    if not f: return jsonify({"error":"No file"}), 400
    caption   = security.sanitize_str(request.form.get("text",""), 1000)
    file_bytes = f.read()
    filename   = f.filename or "file"
    mime_type  = f.content_type or "application/octet-stream"
    return jsonify(sb.admin_send_file(cid, file_bytes, filename, mime_type, caption))

@app.route("/support/<cid>/block", methods=["POST"])
@admin_required
def support_block(cid):
    return jsonify(sb.block_user(cid))

@app.route("/support/<cid>/unblock", methods=["POST"])
@admin_required
def support_unblock(cid):
    return jsonify(sb.unblock_user(cid))

@app.route("/support/<cid>/messages")
@admin_required
@rate_limit(60, 60)
def support_messages(cid):
    raw  = fb.get(f"support/{cid}/messages") or {}
    msgs = sorted(raw.values(), key=lambda m: m.get("ts",0))
    return jsonify(msgs)

@app.route("/support/<cid>/message/<mid>/edit", methods=["POST"])
@admin_required
@rate_limit(20, 60)
def support_edit(cid, mid):
    text = security.sanitize_str(request.form.get("text",""), 4000)
    return jsonify(sb.admin_edit_message(cid, mid, text))

@app.route("/support/<cid>/message/<mid>/delete", methods=["POST"])
@admin_required
@rate_limit(20, 60)
def support_delete_msg(cid, mid):
    return jsonify(sb.admin_delete_message(cid, mid))

@app.route("/support/<cid>/clear", methods=["POST"])
@admin_required
def support_clear(cid):
    fb.delete(f"support/{cid}/messages")
    fb.patch(f"support/{cid}/meta", {"last_message":"", "unread":0})
    return redirect(url_for("support_chat", cid=cid))

@app.route("/support/unread_count")
@admin_required
@rate_limit(60, 60)
def support_unread_count():
    raw   = fb.get("support") or {}
    total = sum((d.get("meta",{}).get("unread") or 0) for d in raw.values() if isinstance(d,dict))
    return jsonify({"count": total})

# ── Static assets ─────────────────────────────────────────────────────────────
@app.route("/website/<path:filename>")
def website_static(filename):
    return send_from_directory("website", filename)

# ══════════════════════════════════════════════════════════════════════════════
# BOT THREADS
# ══════════════════════════════════════════════════════════════════════════════
def _start_bots():
    threading.Thread(target=main_bot.run_bot, daemon=True).start()
    threading.Thread(target=sb.run_support_bot, daemon=True).start()

_start_bots()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)
