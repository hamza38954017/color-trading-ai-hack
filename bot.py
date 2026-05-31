"""
bot.py — Predictor Main Telegram Bot (Updated v2)
New: Privacy/terms prompt on first run, auto-join approval with policy acceptance,
     1 active license limit, detailed purchase notification to admin,
     referral notifications (join + purchase), updated P&T text.
"""
import telebot
from telebot import types
import datetime, random, string, time, threading, os, re, secrets, json
import firebase_helper as fb
import kimipay
import security
from config import (
    BOT_TOKEN, BOT_USERNAME, CHANNEL_ID, CHANNEL_INVITE,
    ADMIN_CHAT_ID, NOTIFY_CHAT_IDS, REFER_COMMISSION,
    MIN_WITHDRAWAL, MAX_WITHDRAWAL, LICENSE_PLANS,
    PRIVACY_POLICY, TERMS_CONDITIONS, SUPPORT_BOT_TOKEN, SITE_URL,
)

def _make_bot():
    token = BOT_TOKEN()
    if not token:
        print("❌ BOT_TOKEN not set"); return None
    return telebot.TeleBot(token, parse_mode=None)

bot = _make_bot()

def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def now_ts():  return int(time.time())
def gen_key():
    chars = string.ascii_uppercase + string.digits
    return "-".join("".join(random.choices(chars, k=4)) for _ in range(4))
def gen_order_id(): return "ORD" + "".join(random.choices(string.digits, k=8))
def fmt_price(p):
    try: return f"₹{float(p):,.0f}"
    except: return f"₹{p}"

def send_msg(cid, text, **kw):
    try: bot.send_message(cid, text, parse_mode="Markdown", **kw)
    except Exception as e: print(f"[MSG] {cid}: {e}")

def send_notify(text):
    for cid in NOTIFY_CHAT_IDS():
        try: bot.send_message(cid, text, parse_mode="Markdown")
        except: pass

# ── User management ───────────────────────────────────────────────────────────
def get_user(cid): return fb.get(f"users/{cid}")
def is_banned(cid): return bool(fb.get(f"banned_users/{cid}"))

def ensure_user(message, referred_by=None):
    cid = str(message.chat.id)
    u = fb.get(f"users/{cid}")
    if u:
        fb.patch(f"users/{cid}", {"last_seen": now_str()})
        return u, False
    fn = (message.from_user.first_name or "").strip()
    ln = (message.from_user.last_name or "").strip()
    un = message.from_user.username or ""
    full_name = f"{fn} {ln}".strip()
    rc = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    while fb.get(f"refer_codes/{rc}"):
        rc = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    data = {
        "chat_id": cid, "full_name": full_name, "first_name": fn,
        "last_name": ln, "username": un, "refer_code": rc,
        "referred_by": referred_by or "", "wallet": 0, "total_earned": 0,
        "refer_count": 0, "verified_refer": 0, "pending_refer": 0,
        "total_spent": 0, "purchase_count": 0,
        "created_at": now_str(), "last_seen": now_str(), "active_license": None,
    }
    fb.put(f"users/{cid}", data)
    fb.put(f"refer_codes/{rc}", cid)
    if referred_by and referred_by != cid:
        ref_u = fb.get(f"users/{referred_by}")
        if ref_u:
            fb.patch(f"users/{referred_by}", {
                "pending_refer": ref_u.get("pending_refer", 0) + 1,
                "refer_count":   ref_u.get("refer_count", 0) + 1,
            })
            fb.put(f"referrals/{referred_by}/{cid}", {
                "chat_id": cid, "name": full_name, "username": un,
                "status": "pending", "joined_at": now_str(), "earned": 0,
            })
            # Notify referrer about new join
            send_msg(referred_by,
                f"👥 *New Referral Joined!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *Full Name:* {full_name}\n"
                f"🆔 *Status:* Pending (no purchase yet)\n"
                f"💸 *Earned:* ₹0\n"
                f"📅 *Date & Time:* {now_str()}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 You'll earn {REFER_COMMISSION()}% when they purchase a license!")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    fb.patch(f"daily_stats/{today}", {
        "new_users": (fb.get(f"daily_stats/{today}/new_users") or 0) + 1,
        "date": today,
    })
    return data, True

def check_membership(user_id):
    ch = CHANNEL_ID()
    if not ch: return True
    try:
        m = bot.get_chat_member(ch, user_id)
        return m.status in ("member", "administrator", "creator")
    except:
        return False

def _get_active_license(cid):
    licenses = fb.get(f"user_licenses/{cid}") or {}
    now = now_ts()
    for lid, lic in licenses.items():
        if lic.get("active") and lic.get("expiry", 0) > now:
            expiry_dt = datetime.datetime.fromtimestamp(lic["expiry"])
            lic["expiry_str"] = expiry_dt.strftime("%Y-%m-%d %H:%M")
            return lic
    return None

def has_active_license(cid):
    return _get_active_license(cid) is not None

# ── Keyboards ─────────────────────────────────────────────────────────────────
def kb_main():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("🏠 Home", "🔑 License Key")
    m.add("🎁 Refer & Earn", "👥 My Refer")
    m.add("💰 Wallet", "📞 Customer Support")
    m.add("📜 Privacy Policy", "📋 Terms & Conditions")
    return m

def kb_cancel():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("❌ Cancel")
    return m

# ── States ────────────────────────────────────────────────────────────────────
user_states = {}; user_temp = {}
def get_state(cid):    return user_states.get(str(cid))
def set_state(cid, s): user_states[str(cid)] = s
def clear_state(cid):  user_states.pop(str(cid), None); user_temp.pop(str(cid), None)
def get_temp(cid):     return user_temp.get(str(cid), {})
def upd_temp(cid, d):  user_temp.setdefault(str(cid), {}).update(d)

# ── /start ────────────────────────────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    cid  = str(msg.chat.id)
    args = msg.text.split()
    if is_banned(cid):
        bot.send_message(msg.chat.id, "🚫 Your account has been permanently banned."); return

    ref_by = None
    if len(args) > 1:
        ref_code = args[1]
        ref_cid  = fb.get(f"refer_codes/{ref_code}")
        if ref_cid and str(ref_cid) != cid:
            ref_by = str(ref_cid)

    # Show Privacy & Terms acceptance first (only for new users)
    existing = fb.get(f"users/{cid}")
    if not existing:
        pp  = PRIVACY_POLICY()
        tc  = TERMS_CONDITIONS()
        mk  = types.InlineKeyboardMarkup(row_width=1)
        mk.add(types.InlineKeyboardButton("✅ I Accept & Continue", callback_data=f"accept_terms_{ref_by or 'none'}"))
        mk.add(types.InlineKeyboardButton("📜 Privacy Policy", callback_data="view_privacy"))
        mk.add(types.InlineKeyboardButton("📋 Terms & Conditions", callback_data="view_terms"))
        bot.send_message(msg.chat.id,
            f"👋 *Welcome to Predictor 4.0!*\n\n"
            f"Before you continue, please review and accept our:\n\n"
            f"📜 *Privacy Policy* — We use AI for predictions. There is no 100% win guarantee. We are not affiliated with any gambling website.\n\n"
            f"📋 *Terms & Conditions* — License keys are non-transferable and bound to your Telegram account.\n\n"
            f"By clicking *I Accept*, you agree to all terms.",
            parse_mode="Markdown", reply_markup=mk)
        if ref_by:
            fb.put(f"pending_refs/{cid}", {"ref_by": ref_by})
        return

    _continue_start(msg, cid, ref_by)

def _continue_start(msg, cid, ref_by=None):
    if not check_membership(msg.from_user.id):
        invite = CHANNEL_INVITE()
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("📢 Join Channel", url=invite))
        bot.send_message(msg.chat.id,
            f"🔒 *Channel Membership Required*\n\n"
            f"Please join our official channel to use this bot.\n\n"
            f"_By continuing you accept our Privacy Policy and Terms & Conditions._",
            parse_mode="Markdown", reply_markup=mk)
        return
    u, is_new = ensure_user(msg, ref_by)
    fn = u.get("first_name", "User")
    lic = _get_active_license(cid)
    lic_status = f"✅ Active (expires: {lic.get('expiry_str','?')})" if lic else "❌ No active license"
    text = (
        f"🎉 *Welcome to Predictor 4.0, {fn}!*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 License: {lic_status}\n"
        f"💰 Wallet: *{fmt_price(u.get('wallet', 0))}*\n"
        f"🤝 Referrals: *{u.get('refer_count', 0)}*"
    )
    send_msg(cid, text, reply_markup=kb_main())

@bot.callback_query_handler(func=lambda c: c.data.startswith("accept_terms_"))
def cb_accept_terms(c):
    bot.answer_callback_query(c.id, "✅ Terms accepted!")
    cid = str(c.message.chat.id)
    ref_by_raw = c.data[len("accept_terms_"):]
    ref_by = None if ref_by_raw == "none" else ref_by_raw
    # Also check pending ref
    pending = fb.get(f"pending_refs/{cid}")
    if pending and not ref_by:
        ref_by = pending.get("ref_by")
    fb.delete(f"pending_refs/{cid}")
    try: bot.delete_message(c.message.chat.id, c.message.message_id)
    except: pass
    _continue_start(c.message, cid, ref_by)

@bot.callback_query_handler(func=lambda c: c.data == "view_privacy")
def cb_view_privacy(c):
    bot.answer_callback_query(c.id)
    send_msg(str(c.message.chat.id), PRIVACY_POLICY())

@bot.callback_query_handler(func=lambda c: c.data == "view_terms")
def cb_view_terms(c):
    bot.answer_callback_query(c.id)
    send_msg(str(c.message.chat.id), TERMS_CONDITIONS())

@bot.chat_join_request_handler()
def handle_join_request(req: types.ChatJoinRequest):
    uid = req.from_user.id
    fn  = req.from_user.first_name or "User"
    try:
        bot.approve_chat_join_request(req.chat.id, uid)
        bot.send_message(uid,
            f"✅ *Join Request Approved!*\n\nWelcome, *{fn}*! 🎉\n\n"
            f"Send /start to begin.\n\n"
            f"_By using this service you agree to our Privacy Policy and Terms & Conditions._",
            parse_mode="Markdown")
    except Exception as e:
        print(f"[JOIN_REQ] {uid}: {e}")

# ── Guard ─────────────────────────────────────────────────────────────────────
def _guard(msg) -> bool:
    cid = str(msg.chat.id)
    if is_banned(cid):
        bot.send_message(msg.chat.id, "🚫 Your account has been banned."); return False
    if not check_membership(msg.from_user.id):
        cmd_start(msg); return False
    u = fb.get(f"users/{cid}")
    if not u:
        cmd_start(msg); return False
    fb.patch(f"users/{cid}", {"last_seen": now_str()})
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    visit_key = f"daily_visits/{today}/{cid}"
    if not fb.get(visit_key):
        fb.put(visit_key, {"chat_id": cid, "ts": now_ts()})
    return True

# ── Home ──────────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🏠 Home")
def msg_home(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    u   = get_user(cid)
    lic = _get_active_license(cid)
    lic_status = f"✅ Active (expires: {lic.get('expiry_str','?')})" if lic else "❌ No active license"
    send_msg(cid,
        f"🏠 *Home*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *{u.get('full_name', 'User')}*\n"
        f"🔑 License: {lic_status}\n"
        f"💰 Wallet: *{fmt_price(u.get('wallet', 0))}*\n"
        f"🤝 Referrals: *{u.get('refer_count', 0)}*\n"
        f"💸 Total Earned: *{fmt_price(u.get('total_earned', 0))}*",
        reply_markup=kb_main())

# ── License Key ───────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🔑 License Key")
def msg_license(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    lic = _get_active_license(cid)
    if lic:
        token = security.generate_site_token(cid)
        url   = f"{SITE_URL()}/app?chatid={cid}&t={token}"
        send_msg(cid,
            f"🔑 *Your Active License*\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗝️ Key: `{lic.get('key', '?')}`\n"
            f"📦 Plan: *{lic.get('plan_label', '?')}*\n"
            f"💰 Amount Paid: *{fmt_price(lic.get('amount', 0))}*\n"
            f"📅 Purchased: *{lic.get('purchase_date', '?')[:16]}*\n"
            f"⏰ Valid Until: *{lic.get('expiry_str', '?')}*",
            reply_markup=kb_main())
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton("🚀 Open Predictor App", url=url))
        bot.send_message(msg.chat.id,
            "👇 Tap below to open the app _(link valid for 10 minutes)_:",
            parse_mode="Markdown", reply_markup=mk)
    else:
        _show_license_plans(cid)

def _show_license_plans(cid):
    mk = types.InlineKeyboardMarkup(row_width=1)
    for plan_id, plan in LICENSE_PLANS.items():
        mk.add(types.InlineKeyboardButton(
            f"⏱️ {plan['label']} — ₹{plan['amount']:,}",
            callback_data=f"buy_plan_{plan_id}"))
    mk.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy"))
    send_msg(cid,
        f"🔑 *Purchase License Key*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ *7 Days* — ₹2,000\n⏱️ *15 Days* — ₹5,000\n⏱️ *1 Month* — ₹8,000\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 Payment via KimiPay (UPI/Card/Net Banking)\n"
        f"🔑 Key delivered instantly after payment",
        reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_plan_"))
def cb_buy_plan(c):
    bot.answer_callback_query(c.id)
    cid     = str(c.message.chat.id)
    plan_id = c.data[9:]
    plan    = LICENSE_PLANS.get(plan_id)
    if not plan:
        bot.answer_callback_query(c.id, "Invalid plan", show_alert=True); return

    # ── ONE license at a time check ───────────────────────────────────────────
    if has_active_license(cid):
        bot.answer_callback_query(c.id,
            "⚠️ You already have an active license!\nYour current license must expire before purchasing a new one.",
            show_alert=True)
        return

    rate = security.check_payment_rate_limit(cid)
    if rate.get("error") == "try_yesterday":
        bot.send_message(cid,
            "⛔ *Too Many Requests*\n\nYou've generated too many payment links.\n"
            "Please *try again tomorrow*.", parse_mode="Markdown"); return
    if rate.get("error") == "wait":
        mins = max(1, rate["wait_secs"] // 60)
        bot.send_message(cid,
            f"⏳ *Please Wait*\n\nTry again in *{mins} minute(s)*.",
            parse_mode="Markdown"); return

    amount   = plan["amount"]
    order_sn = gen_order_id()
    u        = get_user(cid)
    fn       = u.get("full_name", "User") if u else "User"
    callback_url = f"{SITE_URL()}/kimipay_webhook"
    result = kimipay.create_order(
        amount=amount, order_sn=order_sn,
        description=f"Predictor License - {plan['label']}",
        callback_url=callback_url)
    if result.get("error"):
        bot.send_message(cid,
            f"⚠️ *Payment Gateway Error*\n\n{result['error']}\n\nTry again later.",
            parse_mode="Markdown"); return

    pay_url = result["payment_url"]
    kim_id  = result["kimipay_order_id"]
    fb.put(f"pending_payments/{order_sn}", {
        "order_sn": order_sn, "chat_id": cid,
        "username": u.get("username","") if u else "",
        "full_name": fn, "plan_id": plan_id, "plan_label": plan["label"],
        "amount": amount, "kimipay_order_id": kim_id, "payment_url": pay_url,
        "is_paid": False, "created_at": now_str(), "status": "pending",
    })
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(types.InlineKeyboardButton("💳 Pay Now (KimiPay)", url=pay_url))
    mk.add(types.InlineKeyboardButton("✅ I've Paid – Verify", callback_data=f"verify_lic_{order_sn}"))
    mk.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy"))
    bot.send_message(cid,
        f"💳 *Complete Your Payment*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Plan: *{plan['label']}*\n💰 Amount: *₹{amount:,}*\n🔖 Order: `{order_sn}`\n\n"
        f"1️⃣ Click *Pay Now*\n2️⃣ Complete payment\n3️⃣ Click *I've Paid*",
        parse_mode="Markdown", reply_markup=mk)

_verify_attempts = {}

@bot.callback_query_handler(func=lambda c: c.data.startswith("verify_lic_"))
def cb_verify_lic(c):
    bot.answer_callback_query(c.id, "🔍 Checking payment…")
    cid      = str(c.message.chat.id)
    order_sn = c.data[11:]
    if _verify_attempts.get(order_sn, 0) >= 10:
        bot.answer_callback_query(c.id, "❌ Too many attempts. Contact support.", show_alert=True); return
    _verify_attempts[order_sn] = _verify_attempts.get(order_sn, 0) + 1
    sess = fb.get(f"pending_payments/{order_sn}")
    if not sess:
        bot.answer_callback_query(c.id, "❌ Order not found.", show_alert=True); return
    if sess.get("is_paid"):
        _deliver_license(cid, order_sn); return
    result = kimipay.query_order(sess.get("kimipay_order_id",""))
    if result.get("status") in ("success","paid","completed"):
        _verify_attempts.pop(order_sn, None)
        _deliver_license(cid, order_sn)
    elif result.get("error"):
        bot.answer_callback_query(c.id, f"⚠️ Could not verify: {result['error'][:60]}", show_alert=True)
    else:
        rem = 10 - _verify_attempts.get(order_sn, 0)
        bot.answer_callback_query(c.id, f"⏳ Payment not confirmed yet. ({rem} checks left)", show_alert=True)

def _deliver_license(cid: str, order_sn: str):
    sess = fb.get(f"pending_payments/{order_sn}")
    if not sess or sess.get("delivered"): return
    fb.patch(f"pending_payments/{order_sn}", {"delivered": True, "is_paid": True})
    plan_id   = sess.get("plan_id", "7day")
    plan      = LICENSE_PLANS.get(plan_id, LICENSE_PLANS["7day"])
    amount    = sess.get("amount", plan["amount"])
    chat_id   = sess.get("chat_id", cid)
    key = gen_key()
    while fb.get(f"licenses/{key.replace('-','_')}"): key = gen_key()
    expiry_ts  = now_ts() + plan["days"] * 86400
    expiry_dt  = datetime.datetime.fromtimestamp(expiry_ts)
    expiry_str = expiry_dt.strftime("%Y-%m-%d %H:%M")
    u = get_user(chat_id) or {}
    lic_data = {
        "key": key, "chat_id": chat_id, "username": u.get("username",""),
        "full_name": u.get("full_name",""), "plan_id": plan_id,
        "plan_label": plan["label"], "amount": amount,
        "validity_days": plan["days"], "purchase_date": now_str(),
        "expiry": expiry_ts, "expiry_str": expiry_str,
        "active": True, "device_fp": "", "order_sn": order_sn, "created_by": "payment",
    }
    fb.put(f"licenses/{key.replace('-','_')}", lic_data)
    fb.put(f"user_licenses/{chat_id}/{key.replace('-','_')}", lic_data)
    fb.patch(f"pending_payments/{order_sn}", {"is_paid": True, "license_key": key, "paid_at": now_str()})
    fb.patch(f"users/{chat_id}", {
        "purchase_count": u.get("purchase_count",0) + 1,
        "total_spent":    u.get("total_spent",0) + amount,
        "active_license": key, "last_seen": now_str(),
    })

    # Referral commission
    referred_by = u.get("referred_by","")
    if referred_by and referred_by != chat_id:
        comm_pct = REFER_COMMISSION()
        earned   = round(amount * comm_pct / 100, 2)
        ref_u    = get_user(referred_by) or {}
        new_wallet  = ref_u.get("wallet",0) + earned
        new_earned  = ref_u.get("total_earned",0) + earned
        fb.patch(f"users/{referred_by}", {
            "wallet": new_wallet, "total_earned": new_earned,
            "verified_refer": ref_u.get("verified_refer",0) + 1,
            "pending_refer":  max(0, ref_u.get("pending_refer",0) - 1),
        })
        fb.patch(f"referrals/{referred_by}/{chat_id}",
                 {"status": "verified", "earned": earned, "verified_at": now_str()})
        fb.put(f"users/{referred_by}/transactions/{order_sn}_ref", {
            "type": "referral", "for": u.get("full_name","User"),
            "amount": earned, "status": "success", "date": now_str(),
        })
        # Notify referrer with full detail
        send_msg(referred_by,
            f"💸 *Referral Commission Earned!*\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Name:* {u.get('full_name','User')}\n"
            f"📦 *Plan:* {plan['label']} (₹{amount:,})\n"
            f"💰 *You Earned:* ₹{earned:,.0f} ({comm_pct}% commission)\n"
            f"👛 *New Wallet Balance:* {fmt_price(new_wallet)}\n"
            f"📅 *Date & Time:* {now_str()}")

    # Deliver key to buyer
    send_msg(chat_id,
        f"✅ *License Key Activated!*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗝️ Key: `{key}`\n📦 Plan: *{plan['label']}*\n"
        f"💰 Amount: *₹{amount:,}*\n⏰ Valid Until: *{expiry_str}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 Tap *License Key* in the menu to open the app!",
        reply_markup=kb_main())

    # Notify admin with full details
    send_notify(
        f"🔑 *New License Key Purchased!*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Full Name:* {u.get('full_name','?')}\n"
        f"🆔 *Chat ID:* `{chat_id}`\n"
        f"👤 *Username:* @{u.get('username','?')}\n"
        f"📦 *Plan:* {plan['label']}\n"
        f"💰 *Amount:* ₹{amount:,}\n"
        f"🗝️ *Key:* `{key}`\n"
        f"📅 *Date & Time:* {now_str()}")

@bot.callback_query_handler(func=lambda c: c.data == "cancel_buy")
def cb_cancel_buy(c):
    bot.answer_callback_query(c.id, "Cancelled")
    try: bot.delete_message(c.message.chat.id, c.message.message_id)
    except: pass

# ── Wallet ────────────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def msg_wallet(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    u   = get_user(cid)
    mk  = types.InlineKeyboardMarkup(row_width=2)
    mk.add(types.InlineKeyboardButton("➖ Withdraw", callback_data="wallet_withdraw"))
    mk.add(types.InlineKeyboardButton("📋 History",  callback_data="wallet_history"))
    send_msg(cid,
        f"💰 *My Wallet*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Balance: *{fmt_price(u.get('wallet',0))}*\n"
        f"💸 Total Earned: *{fmt_price(u.get('total_earned',0))}*\n"
        f"🛍️ Total Spent: *{fmt_price(u.get('total_spent',0))}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n_Balance earned through referrals._",
        reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "wallet_withdraw")
def cb_withdraw(c):
    bot.answer_callback_query(c.id)
    cid = str(c.message.chat.id)
    u   = get_user(cid)
    min_w = MIN_WITHDRAWAL()
    if u.get("wallet",0) < min_w:
        bot.answer_callback_query(c.id, f"❌ Minimum withdrawal is ₹{min_w:,}. You have ₹{u.get('wallet',0):,.0f}.", show_alert=True); return
    set_state(cid, "wait_withdraw_amount")
    send_msg(cid,
        f"🏦 *Withdraw from Wallet*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Available: *{fmt_price(u.get('wallet',0))}*\n"
        f"Min: *{fmt_price(min_w)}* | Max: *{fmt_price(MAX_WITHDRAWAL())}*\n\n"
        f"Enter withdrawal amount (₹):", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: get_state(str(m.chat.id)) == "wait_withdraw_amount")
def handle_withdraw_amount(msg):
    cid = str(msg.chat.id)
    if msg.text == "❌ Cancel": clear_state(cid); send_msg(cid, "❌ Cancelled.", reply_markup=kb_main()); return
    if not msg.text or not msg.text.strip().isdigit():
        send_msg(cid, "❌ Enter a valid number:", reply_markup=kb_cancel()); return
    amount = int(msg.text.strip())
    u = get_user(cid)
    if amount < MIN_WITHDRAWAL():
        send_msg(cid, f"❌ Minimum is *{fmt_price(MIN_WITHDRAWAL())}*:", reply_markup=kb_cancel()); return
    if amount > MAX_WITHDRAWAL():
        send_msg(cid, f"❌ Maximum is *{fmt_price(MAX_WITHDRAWAL())}*:", reply_markup=kb_cancel()); return
    if amount > u.get("wallet",0):
        send_msg(cid, f"❌ Insufficient balance. Available: *{fmt_price(u.get('wallet',0))}*", reply_markup=kb_cancel()); return
    upd_temp(cid, {"withdraw_amount": amount})
    set_state(cid, "wait_withdraw_upi")
    send_msg(cid, "🏦 Enter your *UPI ID* or *Bank Account + IFSC*:", reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: get_state(str(m.chat.id)) == "wait_withdraw_upi")
def handle_withdraw_upi(msg):
    cid = str(msg.chat.id)
    if msg.text == "❌ Cancel": clear_state(cid); send_msg(cid, "❌ Cancelled.", reply_markup=kb_main()); return
    temp   = get_temp(cid)
    amount = temp.get("withdraw_amount", 0)
    u      = get_user(cid)
    wd_id  = gen_order_id()
    fb.put(f"withdrawals/{wd_id}", {"wd_id": wd_id, "chat_id": cid, "username": u.get("username",""), "full_name": u.get("full_name",""), "amount": amount, "account": msg.text.strip(), "status": "pending", "created_at": now_str()})
    fb.patch(f"users/{cid}", {"wallet": max(0, u.get("wallet",0) - amount)})
    fb.put(f"users/{cid}/transactions/{wd_id}", {"type": "withdrawal", "for": msg.text.strip(), "amount": -amount, "status": "pending", "date": now_str()})
    clear_state(cid)
    send_msg(cid,
        f"✅ *Withdrawal Requested!*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Amount: *{fmt_price(amount)}*\n"
        f"🏦 Account: `{msg.text.strip()}`\n"
        f"🔖 ID: `{wd_id}`\n⏳ Processing: 24–48 hours",
        reply_markup=kb_main())
    send_notify(f"🏦 *Withdrawal Request!*\n👤 {u.get('full_name',cid)}\n💰 {fmt_price(amount)}\n🏦 {msg.text.strip()}")

@bot.callback_query_handler(func=lambda c: c.data == "wallet_history")
def cb_wallet_history(c):
    bot.answer_callback_query(c.id)
    cid  = str(c.message.chat.id)
    txns = fb.get(f"users/{cid}/transactions") or {}
    if not txns:
        bot.answer_callback_query(c.id, "No transactions yet.", show_alert=True); return
    icons = {"purchase":"🛍️","referral":"🤝","withdrawal":"🏦"}
    si    = {"success":"✅","pending":"⏳","failed":"❌"}
    lines = ["💳 *Transaction History*\n━━━━━━━━━━━━━━━━━━━━━"]
    for tid, td in sorted(txns.items(), key=lambda x: x[1].get("date",""), reverse=True)[:15]:
        icon = icons.get(td.get("type",""),"📋")
        amt  = td.get("amount",0)
        amt_s = f"+{fmt_price(amt)}" if amt > 0 else fmt_price(amt)
        lines.append(f"{si.get(td.get('status','pending'),'⏳')} {icon} *{td.get('type','?').title()}*\n   {fmt_price(abs(amt))} | {td.get('date','')[:16]}")
    send_msg(cid, "\n\n".join(lines))

# ── Refer & Earn ──────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "🎁 Refer & Earn")
def msg_refer(msg):
    if not _guard(msg): return
    cid  = str(msg.chat.id)
    u    = get_user(cid)
    rc   = u.get("refer_code","")
    link = f"https://t.me/{BOT_USERNAME()}?start={rc}"
    comm = REFER_COMMISSION()
    send_msg(cid,
        f"🎁 *Refer & Earn*\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 Earn *{comm}% commission* on every license purchase!\n\n"
        f"🔗 *Your Referral Link:*\n`{link}`\n\n"
        f"📊 *Your Stats:*\n"
        f"  👥 Total Referrals: *{u.get('refer_count',0)}*\n"
        f"  ✅ Verified (purchased): *{u.get('verified_refer',0)}*\n"
        f"  ⏳ Pending: *{u.get('pending_refer',0)}*\n"
        f"  💰 Total Earned: *{fmt_price(u.get('total_earned',0))}*\n"
        f"  💵 Wallet: *{fmt_price(u.get('wallet',0))}*")

@bot.message_handler(func=lambda m: m.text == "👥 My Refer")
def msg_my_refer(msg):
    if not _guard(msg): return
    cid  = str(msg.chat.id)
    refs = fb.get(f"referrals/{cid}") or {}
    if not refs:
        send_msg(cid, "👥 *My Referrals*\n━━━━━━━━━━━━━━━━━━━━━\nNo referrals yet.\n\nShare your link via *Refer & Earn* to start!"); return
    lines = [f"👥 *My Referrals* ({len(refs)} total)\n━━━━━━━━━━━━━━━━━━━━━"]
    for i, (rid, rd) in enumerate(refs.items(), 1):
        st = "✅" if rd.get("status") == "verified" else "⏳"
        earned = rd.get("earned",0)
        earned_str = f" | 💰 +{fmt_price(earned)}" if earned else ""
        lines.append(f"{i}. {st} *{rd.get('name','User')}*{earned_str}\n   📅 {rd.get('joined_at','?')[:10]}")
    send_msg(cid, "\n".join(lines))

# ── Customer Support ──────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📞 Customer Support")
def msg_support(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    sup_bot_username = (fb.cfg("support_bot_username") or "").strip("@")
    if not sup_bot_username:
        send_msg(cid, "📞 *Customer Support*\n━━━━━━━━━━━━━━━━━━━━━\nSupport bot not configured. Contact admin."); return
    mk = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton("💬 Open Support Chat", url=f"https://t.me/{sup_bot_username}"))
    bot.send_message(cid,
        "📞 *Customer Support*\n━━━━━━━━━━━━━━━━━━━━━\n"
        "🕐 Response: Usually within a few hours\n📸 You can send screenshots, videos, files",
        parse_mode="Markdown", reply_markup=mk)

# ── Privacy / Terms ───────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text in ("📜 Privacy Policy","/privacy"))
def msg_privacy(msg):
    if not _guard(msg): return
    send_msg(str(msg.chat.id), PRIVACY_POLICY())

@bot.message_handler(commands=["privacy"])
def cmd_privacy(msg): send_msg(str(msg.chat.id), PRIVACY_POLICY())

@bot.message_handler(func=lambda m: m.text in ("📋 Terms & Conditions","/terms"))
def msg_terms(msg):
    if not _guard(msg): return
    send_msg(str(msg.chat.id), TERMS_CONDITIONS())

@bot.message_handler(commands=["terms"])
def cmd_terms(msg): send_msg(str(msg.chat.id), TERMS_CONDITIONS())

@bot.message_handler(func=lambda m: m.text == "❌ Cancel")
def msg_cancel(msg):
    cid = str(msg.chat.id)
    clear_state(cid)
    send_msg(cid, "❌ *Cancelled.*", reply_markup=kb_main())

# ── KimiPay webhook ───────────────────────────────────────────────────────────
def handle_kimipay_webhook(data: dict) -> str:
    order_sn = data.get("order_sn","")
    status   = data.get("status","")
    if status not in ("success","paid","completed"): return "ok"
    sess = fb.get(f"pending_payments/{order_sn}")
    if not sess or sess.get("delivered"): return "ok"
    fb.patch(f"pending_payments/{order_sn}", {"is_paid": True})
    chat_id = sess.get("chat_id")
    if chat_id: _deliver_license(chat_id, order_sn)
    return "ok"

# ── Broadcast ─────────────────────────────────────────────────────────────────
def broadcast_message(text=None, image_url=None, image_bytes=None,
                      inline_btn_text=None, inline_btn_url=None, chat_ids=None) -> tuple:
    if not chat_ids:
        users = fb.get("users") or {}
        chat_ids = [k for k in users.keys() if k != "_init"]
    ok = fail = 0
    mk = None
    if inline_btn_text and inline_btn_url:
        mk = types.InlineKeyboardMarkup()
        mk.add(types.InlineKeyboardButton(inline_btn_text, url=inline_btn_url))
    for cid in chat_ids:
        try:
            if image_bytes and text:
                import io; f = io.BytesIO(image_bytes); f.name = "img.jpg"
                bot.send_photo(cid, f, caption=text, parse_mode="Markdown", reply_markup=mk)
            elif image_url and text:
                bot.send_photo(cid, image_url, caption=text, parse_mode="Markdown", reply_markup=mk)
            elif image_bytes:
                import io; f = io.BytesIO(image_bytes); f.name = "img.jpg"
                bot.send_photo(cid, f, reply_markup=mk)
            elif image_url:
                bot.send_photo(cid, image_url, reply_markup=mk)
            elif text:
                bot.send_message(cid, text, parse_mode="Markdown", reply_markup=mk)
            ok += 1; time.sleep(0.04)
        except Exception as e:
            print(f"[BROADCAST] {cid}: {e}"); fail += 1
    return ok, fail

def run_bot():
    if not bot: print("❌ Bot not started — BOT_TOKEN missing"); return
    print("🤖 Main bot polling started")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
