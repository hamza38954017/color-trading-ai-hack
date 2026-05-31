"""
support_bot.py — Customer Support Bot (Fixed v2)
Key fix: Notifications sent via BOTH support_bot AND main_bot as fallback.
Admin_chat_id is always notified regardless of whether they started support bot.
Messages stored at /support/{chat_id}/messages/{msg_id}
Meta stored at /support/{chat_id}/meta
"""
import telebot
from telebot import types
import datetime, os, time, io
import firebase_helper as fb
from config import (
    SUPPORT_NOTIFY_CHAT_IDS, ADMIN_CHAT_ID,
    SUPPORT_BOT_TOKEN, SUPPORT_GREETING,
)

def _get_token():
    token = os.environ.get("SUPPORT_BOT_TOKEN", "").strip()
    return token or SUPPORT_BOT_TOKEN()

def _make_bot():
    token = _get_token()
    if not token:
        print("⚠️  SUPPORT_BOT_TOKEN not set"); return None
    return telebot.TeleBot(token, parse_mode=None)

support_bot = _make_bot()

# ── Lazy import of main bot to avoid circular ─────────────────────────────────
_main_bot = None
def _get_main_bot():
    global _main_bot
    if _main_bot is None:
        try:
            import bot as main_bot_module
            _main_bot = main_bot_module.bot
        except Exception as e:
            print(f"[SUPPORT] Could not import main bot: {e}")
    return _main_bot

def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def now_ts():  return int(time.time())

# ── Core notification — sends via support_bot AND main_bot ────────────────────
def send_support_notify(chat_id: str, user_name: str, text: str, msg_type: str = "text"):
    """
    Notify all configured admin chat IDs about a new support message.
    Tries support_bot first, then falls back to main_bot.
    Always includes admin_chat_id from config as a recipient.
    """
    try:
        # Build recipient list: configured IDs + always include admin_chat_id
        ids = list(SUPPORT_NOTIFY_CHAT_IDS())
        admin_id = ADMIN_CHAT_ID()
        if admin_id and admin_id not in ids:
            ids.append(admin_id)
        if not ids:
            print("[SUPPORT NOTIFY] No admin IDs configured")
            return

        panel_url  = fb.cfg("panel_url") or ""
        chat_link  = f"{panel_url.rstrip('/')}/support/{chat_id}" if panel_url else ""
        icon       = {"photo": "🖼️", "video": "🎬", "document": "📄"}.get(msg_type, "💬")
        preview    = (text[:120] + "…" if len(text) > 120 else text) if text else f"[{msg_type}]"

        notify_text = (
            f"📩 *New Support Message*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *User:* {user_name}\n"
            f"🆔 *Chat ID:* `{chat_id}`\n"
            f"{icon} *Message:* {preview}\n"
            f"🕐 *Time:* {now_str()}"
        )
        mk = None
        if chat_link:
            mk = types.InlineKeyboardMarkup()
            mk.add(types.InlineKeyboardButton("🖥️ View in Admin Panel", url=chat_link))

        main_bot = _get_main_bot()

        for aid in ids:
            sent = False
            # 1st attempt: via support_bot (admin must have started it)
            if support_bot:
                try:
                    support_bot.send_message(aid, notify_text, parse_mode="Markdown", reply_markup=mk)
                    sent = True
                except Exception as e:
                    print(f"[NOTIFY via support_bot] {aid}: {e}")
            # 2nd attempt: via main_bot (admin definitely started this)
            if not sent and main_bot:
                try:
                    main_bot.send_message(aid, notify_text, parse_mode="Markdown", reply_markup=mk)
                    sent = True
                except Exception as e:
                    print(f"[NOTIFY via main_bot] {aid}: {e}")
            if not sent:
                print(f"[NOTIFY] Failed to deliver to {aid} via both bots")

    except Exception as e:
        print(f"[NOTIFY] Unexpected error: {e}")


def mark_admin_msgs_read(chat_id: str):
    try:
        msgs = fb.get(f"support/{chat_id}/messages") or {}
        for mid, m in msgs.items():
            if isinstance(m, dict) and m.get("from") == "admin" and not m.get("read"):
                fb.patch(f"support/{chat_id}/messages/{mid}", {"read": True})
    except Exception as e:
        print(f"[MARK_READ] {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────
def send_msg(cid, text, **kw):
    try: support_bot.send_message(cid, text, parse_mode="Markdown", **kw)
    except Exception as e: print(f"[SUPPORT MSG] {cid}: {e}")

def store_message(chat_id, msg_id, data: dict):
    """Store a message in Firebase and update meta."""
    fb.put(f"support/{chat_id}/messages/{msg_id}", data)
    fb.patch(f"support/{chat_id}/meta", {
        "last_message": data.get("text") or data.get("caption") or "[media]",
        "last_time":    data.get("time", now_str()),
        "last_ts":      now_ts(),
        "unread":       (fb.get(f"support/{chat_id}/meta/unread") or 0) + 1,
        "chat_id":      str(chat_id),
        "user_name":    data.get("user_name", ""),
        "username":     data.get("username", ""),
    })

def get_user_photo_url(user_id):
    try:
        photos = support_bot.get_user_profile_photos(user_id, limit=1)
        if photos and photos.photos:
            fid  = photos.photos[0][-1].file_id
            info = support_bot.get_file(fid)
            return f"https://api.telegram.org/file/bot{_get_token()}/{info.file_path}"
    except Exception as e:
        print(f"[PHOTO] {e}")
    return ""

def _get_file_url(file_id):
    try:
        info = support_bot.get_file(file_id)
        return f"https://api.telegram.org/file/bot{_get_token()}/{info.file_path}"
    except:
        return ""

def _is_blocked(cid):
    return bool(fb.get(f"support/{cid}/meta/blocked"))

BLOCKED_MSG = "🚫 You have been blocked from support. Contact the main bot if you believe this is a mistake."


# ── /start ────────────────────────────────────────────────────────────────────
@support_bot.message_handler(commands=["start"])
def cmd_start(msg):
    cid   = str(msg.chat.id)
    fn    = msg.from_user.first_name or "Friend"
    ln    = msg.from_user.last_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {ln}".strip()

    if _is_blocked(cid):
        send_msg(cid, BLOCKED_MSG); return

    photo_url = get_user_photo_url(msg.from_user.id)
    meta = fb.get(f"support/{cid}/meta") or {}
    fb.patch(f"support/{cid}/meta", {
        "chat_id":      cid,
        "user_name":    uname,
        "username":     un,
        "photo_url":    photo_url,
        "started_at":   meta.get("started_at", now_str()),
        "last_message": meta.get("last_message", ""),
        "last_time":    now_str(),
        "last_ts":      now_ts(),
        "unread":       meta.get("unread", 0),
        "blocked":      False,
    })

    greeting = SUPPORT_GREETING()
    support_bot.send_message(cid, greeting, parse_mode="Markdown")


# ── Text ─────────────────────────────────────────────────────────────────────
@support_bot.message_handler(content_types=["text"])
def handle_text(msg):
    cid   = str(msg.chat.id)
    mid   = str(msg.message_id)
    fn    = msg.from_user.first_name or ""
    ln    = msg.from_user.last_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {ln}".strip()

    if _is_blocked(cid):
        send_msg(cid, BLOCKED_MSG); return

    # Update photo_url if not set
    photo_url = fb.get(f"support/{cid}/meta/photo_url") or get_user_photo_url(msg.from_user.id)
    fb.patch(f"support/{cid}/meta", {
        "user_name": uname, "username": un,
        "chat_id": cid, "photo_url": photo_url,
    })

    data = {
        "msg_id":    mid,
        "chat_id":   cid,
        "user_name": uname,
        "username":  un,
        "text":      msg.text,
        "type":      "text",
        "from":      "user",
        "time":      now_str(),
        "ts":        now_ts(),
        "read":      False,
        "delivered": True,
        "edited":    False,
    }
    store_message(cid, mid, data)
    mark_admin_msgs_read(cid)
    send_support_notify(cid, uname, msg.text, "text")

    # Auto-reply if configured
    try:
        auto_reply = fb.cfg("support_auto_reply") or ""
        if auto_reply:
            time.sleep(0.8)
            support_bot.send_chat_action(cid, "typing")
            time.sleep(0.5)
            support_bot.send_message(cid, auto_reply, parse_mode="Markdown")
    except Exception as e:
        print(f"[AUTO_REPLY] {e}")


# ── Photo ────────────────────────────────────────────────────────────────────
@support_bot.message_handler(content_types=["photo"])
def handle_photo(msg):
    cid   = str(msg.chat.id)
    mid   = str(msg.message_id)
    fn    = msg.from_user.first_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {msg.from_user.last_name or ''}".strip()

    if _is_blocked(cid): send_msg(cid, BLOCKED_MSG); return

    photo    = msg.photo[-1]
    file_url = _get_file_url(photo.file_id)
    caption  = msg.caption or ""
    photo_url = fb.get(f"support/{cid}/meta/photo_url") or get_user_photo_url(msg.from_user.id)
    fb.patch(f"support/{cid}/meta", {"user_name": uname, "username": un, "chat_id": cid, "photo_url": photo_url})

    data = {
        "msg_id": mid, "chat_id": cid, "user_name": uname, "username": un,
        "text": caption, "caption": caption,
        "file_id": photo.file_id, "file_url": file_url,
        "type": "photo", "from": "user",
        "time": now_str(), "ts": now_ts(),
        "read": False, "delivered": True, "edited": False,
    }
    store_message(cid, mid, data)
    mark_admin_msgs_read(cid)
    send_support_notify(cid, uname, caption or "[photo]", "photo")


# ── Video ────────────────────────────────────────────────────────────────────
@support_bot.message_handler(content_types=["video"])
def handle_video(msg):
    cid   = str(msg.chat.id)
    mid   = str(msg.message_id)
    fn    = msg.from_user.first_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {msg.from_user.last_name or ''}".strip()

    if _is_blocked(cid): send_msg(cid, BLOCKED_MSG); return

    file_url = _get_file_url(msg.video.file_id)
    caption  = msg.caption or ""
    photo_url = fb.get(f"support/{cid}/meta/photo_url") or get_user_photo_url(msg.from_user.id)
    fb.patch(f"support/{cid}/meta", {"user_name": uname, "username": un, "chat_id": cid, "photo_url": photo_url})

    data = {
        "msg_id": mid, "chat_id": cid, "user_name": uname, "username": un,
        "text": caption, "caption": caption,
        "file_id": msg.video.file_id, "file_url": file_url,
        "type": "video", "from": "user",
        "time": now_str(), "ts": now_ts(),
        "read": False, "delivered": True, "edited": False,
    }
    store_message(cid, mid, data)
    mark_admin_msgs_read(cid)
    send_support_notify(cid, uname, caption or "[video]", "video")


# ── Document ─────────────────────────────────────────────────────────────────
@support_bot.message_handler(content_types=["document"])
def handle_document(msg):
    cid   = str(msg.chat.id)
    mid   = str(msg.message_id)
    fn    = msg.from_user.first_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {msg.from_user.last_name or ''}".strip()

    if _is_blocked(cid): send_msg(cid, BLOCKED_MSG); return

    file_id   = msg.document.file_id
    file_name = msg.document.file_name or "file"
    caption   = msg.caption or ""
    file_url  = _get_file_url(file_id)
    photo_url = fb.get(f"support/{cid}/meta/photo_url") or get_user_photo_url(msg.from_user.id)
    fb.patch(f"support/{cid}/meta", {"user_name": uname, "username": un, "chat_id": cid, "photo_url": photo_url})

    data = {
        "msg_id": mid, "chat_id": cid, "user_name": uname, "username": un,
        "text": caption, "caption": caption,
        "file_id": file_id, "file_url": file_url, "file_name": file_name,
        "type": "document", "from": "user",
        "time": now_str(), "ts": now_ts(),
        "read": False, "delivered": True, "edited": False,
    }
    store_message(cid, mid, data)
    mark_admin_msgs_read(cid)
    send_support_notify(cid, uname, caption or f"[{file_name}]", "document")


# ── Voice / Sticker / Other ───────────────────────────────────────────────────
@support_bot.message_handler(content_types=["voice", "sticker", "location", "contact"])
def handle_other(msg):
    cid   = str(msg.chat.id)
    mid   = str(msg.message_id)
    fn    = msg.from_user.first_name or ""
    un    = msg.from_user.username or ""
    uname = f"{fn} {msg.from_user.last_name or ''}".strip()

    if _is_blocked(cid): send_msg(cid, BLOCKED_MSG); return

    ctype = msg.content_type
    icons = {"voice": "🎤", "sticker": "😀", "location": "📍", "contact": "👤"}
    label = f"[{icons.get(ctype, '📎')}{ctype}]"

    photo_url = fb.get(f"support/{cid}/meta/photo_url") or ""
    fb.patch(f"support/{cid}/meta", {"user_name": uname, "username": un, "chat_id": cid, "photo_url": photo_url})

    data = {
        "msg_id": mid, "chat_id": cid, "user_name": uname, "username": un,
        "text": label, "type": ctype, "from": "user",
        "time": now_str(), "ts": now_ts(),
        "read": False, "delivered": True, "edited": False,
    }
    store_message(cid, mid, data)
    mark_admin_msgs_read(cid)
    send_support_notify(cid, uname, label, ctype)


# ── Admin actions (called by Flask routes) ────────────────────────────────────
def admin_reply(chat_id: str, text: str, image_url: str = "") -> dict:
    if not support_bot: return {"error": "Support bot not configured"}
    try:
        if image_url and text:
            m = support_bot.send_photo(chat_id, image_url, caption=text, parse_mode="Markdown")
        elif image_url:
            m = support_bot.send_photo(chat_id, image_url)
        else:
            m = support_bot.send_message(chat_id, text, parse_mode="Markdown")
        mid = str(m.message_id)
        fb.put(f"support/{chat_id}/messages/admin_{mid}", {
            "msg_id": f"admin_{mid}", "chat_id": chat_id,
            "text": text, "image_url": image_url,
            "type": "photo" if image_url else "text",
            "from": "admin", "time": now_str(), "ts": now_ts(),
            "read": False, "delivered": True, "edited": False,
        })
        fb.patch(f"support/{chat_id}/meta", {
            "last_message": text or "[image]",
            "last_time": now_str(), "last_ts": now_ts(), "unread": 0,
        })
        return {"ok": True, "mid": mid}
    except Exception as e:
        return {"error": str(e)}

def admin_send_file(chat_id: str, file_bytes: bytes, filename: str,
                    mime_type: str, caption: str = "") -> dict:
    if not support_bot: return {"error": "Support bot not configured"}
    try:
        f = io.BytesIO(file_bytes); f.name = filename
        cap = caption or None
        if mime_type.startswith("image/"):
            m = support_bot.send_photo(chat_id, f, caption=cap, parse_mode="Markdown")
            fid = m.photo[-1].file_id; ftype = "photo"
        elif mime_type.startswith("video/"):
            m = support_bot.send_video(chat_id, f, caption=cap, parse_mode="Markdown")
            fid = m.video.file_id; ftype = "video"
        else:
            m = support_bot.send_document(chat_id, f, caption=cap, parse_mode="Markdown")
            fid = m.document.file_id; ftype = "document"
        file_url = _get_file_url(fid)
        mid      = str(m.message_id)
        fb.put(f"support/{chat_id}/messages/admin_{mid}", {
            "msg_id": f"admin_{mid}", "chat_id": chat_id,
            "text": caption, "file_url": file_url, "file_name": filename,
            "type": ftype, "from": "admin",
            "time": now_str(), "ts": now_ts(),
            "read": False, "delivered": True, "edited": False,
        })
        fb.patch(f"support/{chat_id}/meta", {
            "last_message": caption or f"[{ftype}]",
            "last_time": now_str(), "last_ts": now_ts(), "unread": 0,
        })
        return {"ok": True, "mid": mid, "file_url": file_url, "type": ftype}
    except Exception as e:
        return {"error": str(e)}

def block_user(chat_id: str) -> dict:
    fb.patch(f"support/{chat_id}/meta", {"blocked": True})
    try: support_bot.send_message(chat_id, BLOCKED_MSG)
    except: pass
    return {"ok": True}

def unblock_user(chat_id: str) -> dict:
    fb.patch(f"support/{chat_id}/meta", {"blocked": False})
    return {"ok": True}

def admin_edit_message(chat_id: str, admin_mid: str, new_text: str) -> dict:
    if not support_bot: return {"error": "Bot not configured"}
    try:
        real_mid = int(admin_mid.replace("admin_", ""))
        support_bot.edit_message_text(new_text, chat_id, real_mid, parse_mode="Markdown")
        fb.patch(f"support/{chat_id}/messages/{admin_mid}",
                 {"text": new_text, "edited": True, "edited_at": now_str()})
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

def admin_delete_message(chat_id: str, admin_mid: str) -> dict:
    if not support_bot: return {"error": "Bot not configured"}
    try:
        real_mid = int(admin_mid.replace("admin_", ""))
        support_bot.delete_message(chat_id, real_mid)
    except: pass
    fb.delete(f"support/{chat_id}/messages/{admin_mid}")
    return {"ok": True}

def run_support_bot():
    if not support_bot:
        print("❌ Support bot not started — SUPPORT_BOT_TOKEN missing"); return
    print("🎧 Support bot polling started")
    support_bot.infinity_polling(timeout=30, long_polling_timeout=30)
