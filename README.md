# Predictor 4.0 — Full System

A complete Telegram bot + web predictor app + admin panel built in **Python + Flask + Firebase Realtime Database**.

---

## 📦 Project Structure

```
predictor4/
├── app.py                  ← Flask server (website + admin panel + webhooks)
├── bot.py                  ← Main Telegram bot
├── support_bot.py          ← Customer support bot
├── config.py               ← Live config helper (reads from Firebase)
├── firebase_helper.py      ← Firebase REST client (no SDK needed)
├── kimipay.py              ← KimiPay payment gateway
├── security.py             ← Rate limiting, bans, token auth
├── requirements.txt
├── Procfile                ← Gunicorn for Render/Railway
├── .env.example            ← Environment variables template
├── firebase_setup.py       ← Run in Google Colab to init database
├── templates/
│   ├── admin_login.html
│   ├── admin_panel.html    ← Full SPA admin panel
│   ├── predictor.html      ← Predictor website (exact Predictor4 UI)
│   ├── support.html        ← Support chat list
│   └── support_chat.html   ← Individual support chat
└── website/
    └── assets/
        └── images/
            └── logo.png    ← Replace with your real logo
```

---

## 🚀 Quick Setup (10 Steps)

### Step 1 — Firebase Realtime Database

1. Go to [Firebase Console](https://console.firebase.google.com) → **Add Project**
2. Navigate to **Build → Realtime Database → Create Database**
3. Choose any region, start in **Test Mode** (public rules)
4. Copy the database URL (looks like `https://your-project-default-rtdb.firebaseio.com`)

**Database Rules (paste in Firebase Console → Rules tab):**
```json
{
  "rules": {
    ".read": true,
    ".write": true
  }
}
```
> For production, tighten rules after setup. The app uses server-side validation.

---

### Step 2 — Run Firebase Setup in Google Colab

1. Open [Google Colab](https://colab.research.google.com)
2. Create a new notebook
3. Copy the contents of `firebase_setup.py` into a cell
4. Replace `FIREBASE_URL` with your database URL
5. Run the cell — it creates all required nodes and default config

---

### Step 3 — Create Telegram Bots

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. `/newbot` → set name → get **Main Bot Token**
3. `/newbot` again → set name (e.g. YourAppSupport) → get **Support Bot Token**
4. For your main bot, also run: `/setmenubutton` (optional)
5. Note down both tokens

---

### Step 4 — Deploy to Render (Free)

1. Push this folder to a GitHub repository
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your GitHub repo
4. Set **Build Command**: `pip install -r requirements.txt`
5. Set **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
6. Add **Environment Variables**:

| Key | Value |
|-----|-------|
| `FIREBASE_URL` | `https://your-project-default-rtdb.firebaseio.com` |
| `SECRET_KEY` | Any random 64-character string |
| `BOT_TOKEN` | Main bot token from BotFather |
| `SUPPORT_BOT_TOKEN` | Support bot token from BotFather |

7. Click **Deploy** — wait for it to go live
8. Copy your app URL (e.g. `https://predictor4.onrender.com`)

---

### Step 5 — Configure via Admin Panel

1. Open `https://your-app.onrender.com/admin/login`
2. Login:
   - **Username**: `admin`
   - **Password**: `Admin@2026`
   - **Chat ID**: Your Telegram numeric Chat ID
     *(Send `/start` to [@userinfobot](https://t.me/userinfobot) to find it)*
3. Go to **⚙️ Bot Settings** and fill in:
   - **Bot Token** & **Support Bot Token**
   - **Bot Username** (without @)
   - **Support Bot Username** (without @)
   - **Channel ID** (e.g. `-1001234567890`)
   - **Channel Invite Link**
   - **Admin Chat ID** (your numeric Telegram ID)
   - **Site URL** (your Render URL)
   - **Panel URL** (same as Site URL)
   - **KimiPay App ID** & **API Key**
4. Save Settings

---

### Step 6 — Configure Website Settings

1. In Admin Panel → **🌐 Website Settings**
2. Customise all text fields (title, subtitle, ticker, protocols, etc.)
3. Save

---

### Step 7 — Upload Your Logo

Replace `website/assets/images/logo.png` with your actual logo image.
The placeholder is a simple green SVG. Your logo should be ~200×200px PNG.

---

### Step 8 — Test the Bot

1. Open your main bot in Telegram
2. Send `/start`
3. Join the required channel
4. Try purchasing a license key via **🔑 License Key** menu

---

### Step 9 — Test the Website

1. In Telegram, tap **🔑 License Key** (after purchasing)
2. Tap **🚀 Open Predictor App**
3. The app opens with your chatid pre-authenticated via a one-time token

---

### Step 10 — Change Admin Password

1. Admin Panel → **⚙️ Bot Settings**
2. Fill in **Admin Password** field with your new password
3. Save — takes effect immediately

---

## 🔐 Security Features

| Feature | Details |
|---------|---------|
| Admin login lockout | 5 failed attempts → 60 min lockout (server-side, per IP) |
| Admin chatid check | Password alone is not enough — must match admin chat ID |
| Website access | Requires chatid + one-time token (expires 10 min, single-use) |
| Browser direct access | Shows "Use from Telegram" error page — no app access |
| Wrong key banning | 5 wrong license keys → permanent ban (chatid + device fingerprint) |
| Device fingerprint | Browser fingerprint stored, mismatches logged |
| Payment rate limiting | 1st: generate → 2nd within 15min: wait → 3rd+: try yesterday |
| Input sanitisation | All inputs sanitised, max-length enforced server-side |
| Rate limiting | Every API endpoint has per-IP rate limits |
| Security headers | X-Content-Type-Options, X-Frame-Options, X-XSS-Protection |
| SQL injection | No SQL used — Firebase REST only |
| XSS | All user input escaped in templates |
| CSRF | Session-based admin, SameSite cookie |
| Access logs | IP, device type, user agent, chatid, timestamp stored |

---

## 💰 License Key Plans

| Plan | Duration | Price |
|------|----------|-------|
| 7 Days | 7 days | ₹2,000 |
| 15 Days | 15 days | ₹5,000 |
| 1 Month | 30 days | ₹8,000 |

---

## 🤝 Referral System

- Every user gets a unique referral link: `https://t.me/YourBot?start=REFCODE`
- When a referred user purchases any license: referrer earns **10%** commission
- Commission goes straight to wallet
- Minimum withdrawal: ₹100 (configurable)
- Withdrawal requests shown in admin panel with approve/reject

---

## 📞 Customer Support Bot

- Users open support from the bot menu **📞 Customer Support**
- They're directed to the support bot
- Messages stored in Firebase under `/support/{chatid}/messages/`
- Admin notified instantly in Telegram when new message arrives
- Admin panel `/support` shows all chats sorted by latest message
- Admin can: reply text, send images/files, edit messages, delete messages, block/unblock users

---

## 📢 Broadcast System

Admin Panel → **📢 Broadcast**:
- Send to **Main Bot users**, **Support Bot users**, or **Both**
- Supports text, image (URL or upload), optional inline button with redirect URL
- All in Markdown format

---

## 🗄️ Firebase Database Structure

```
/config/              ← All settings (bot tokens, KimiPay, etc.)
/settings/            ← Website UI settings
/users/{chatid}/      ← User data (wallet, referrals, etc.)
/licenses/{key}/      ← License key records
/user_licenses/{chatid}/{key}/ ← Per-user license lookup
/pending_payments/{order_sn}/  ← KimiPay payment records
/withdrawals/{wd_id}/ ← Withdrawal requests
/referrals/{owner}/{ref_chatid}/ ← Referral records
/refer_codes/{code}/  ← Referral code → chatid mapping
/support/{chatid}/    ← Support chat data
  /meta/              ← User info, last message, unread count
  /messages/{msg_id}/ ← Individual messages
/banned_users/{chatid}/   ← Permanent bans
/banned_devices/{fp}/     ← Device fingerprint bans
/wrong_key_attempts/{chatid}/ ← Failed key attempt counter
/payment_attempts/{chatid}/   ← Payment link rate limit
/admin_lockouts/{ip}/         ← Admin login lockout
/site_tokens/{token}/         ← One-time website access tokens
/access_logs/{id}/            ← Visitor logs (IP, device, action)
/daily_stats/{date}/          ← New users + visits per day
```

---

## 🔄 KimiPay Integration

1. Register at [kimipay.in](https://kimipay.in)
2. Get **App ID** and **API Key** from your dashboard
3. Enter them in Admin Panel → Settings
4. Set **Webhook URL** in KimiPay dashboard to: `https://your-app.onrender.com/kimipay_webhook`
5. Payments auto-deliver license keys via webhook

---

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start bot / rejoin after channel check |
| `/privacy` | Show Privacy Policy |
| `/terms` | Show Terms & Conditions |

**Menu Buttons:**
- 🏠 Home — Account overview
- 🔑 License Key — View active key or purchase
- 🎁 Refer & Earn — Referral link + stats
- 👥 My Refer — List of referred users
- 💰 Wallet — Balance, withdraw, history
- 📞 Customer Support — Opens support bot
- 📜 Privacy Policy
- 📋 Terms & Conditions

---

## ⚙️ Admin Panel Sections

| Section | Features |
|---------|---------|
| Dashboard | Total users, active licenses, income (₹), paid orders, withdrawals, bans, new users today, site visits today |
| All Users | View/edit/ban/unban all users |
| Banned Users | View bans, unban |
| Referrals | Full referral report with commissions |
| License Keys | View/edit/revoke all keys, search by key/chatid/name |
| Create License | Manually create keys (chatid, username, full name, plan) |
| Payments | All KimiPay payment records with status |
| Withdrawals | Approve/reject withdrawals (notifies user via bot) |
| Support Chats | Full support interface (identical to OwnShop) |
| Broadcast | Send to main bot, support bot, or both |
| Access Logs | IP, device, chatid, action, timestamp |
| Daily Stats | New users + site visits per day |
| Bot Settings | All config editable (tokens, KimiPay, commission, legal text) |
| Website Settings | All UI text editable (title, ticker, protocols, maintenance mode) |

---

## 🐛 Troubleshooting

**Bot not responding:**
- Check `BOT_TOKEN` env var is set correctly
- Ensure bot is not blocked
- Check Render logs for errors

**Website shows "Use from Telegram":**
- This is correct behaviour — access via bot only
- Tap 🔑 License Key in bot → tap Open Predictor App

**KimiPay payments not delivering:**
- Verify App ID and API Key in Settings
- Check webhook URL is set in KimiPay dashboard
- User can manually tap "I've Paid – Verify" in bot

**Admin login locked:**
- Wait 60 minutes (server-side per IP)
- Or clear `/admin_lockouts/` node in Firebase Console

**License key shows "registered on another device":**
- Key is bound to a specific Telegram chatid
- Contact admin to re-bind or create a new key

---

## 📄 License

This software is for personal use. Do not redistribute or resell.
