"""
app.py — Flask Application (Updated v2)
Fixes: Support panel 404, wingo proxy, AI prediction, history, win/loss tracking.
"""
from flask import (Flask, request, jsonify, render_template, session,
                   redirect, url_for, send_from_directory, abort, make_response)
from werkzeug.exceptions import HTTPException
from functools import wraps
import datetime, threading, os, time, json, secrets, hashlib, traceback
import requests
import firebase_helper as fb
import kimipay as kp
import security
import bot as main_bot
import support_bot as sb
from config import (
    SECRET_KEY, FLASK_PORT, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_CHAT_ID,
    NOTIFY_CHAT_IDS, LICENSE_PLANS, REFER_COMMISSION, SITE_URL,
)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=16*1024*1024)

@app.errorhandler(Exception)
def handle_api_errors(e):
    """Ensure all API errors return JSON instead of Flask's default HTML."""
    if request.path.startswith("/api/"):
        if isinstance(e, HTTPException):
            return jsonify({"error": f"HTTP Error: {e.name}"}), e.code
        
        # Log the actual python error to console for debugging
        print("[API CRASH]", traceback.format_exc())
        return jsonify({"error": f"Server Error: {str(e)}"}), 500
        
    if isinstance(e, HTTPException):
        return e
    return "Internal Server Error", 500

@app.after_request
def set_security_headers(resp):
    resp.headers.update({"X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","X-XSS-Protection":"1; mode=block"})
    return resp

def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def now_ts():  return int(time.time())
def fmt_inr(v):
    try: return f"₹{float(v):,.0f}"
    except: return f"₹{v}"
def get_ip():
    xff = request.headers.get("X-Forwarded-For","")
    return xff.split(",")[0].strip() if xff else request.remote_addr

_rate_cache = {}
def rate_limit(max_calls,period_secs):
    def decorator(f):
        @wraps(f)
        def wrapper(*args,**kwargs):
            ip=get_ip(); key=f"{f.__name__}:{ip}"; now=time.time()
            h=[t for t in _rate_cache.get(key,[]) if now-t<period_secs]
            if len(h)>=max_calls: return jsonify({"error":"Rate limit exceeded"}),429
            h.append(now); _rate_cache[key]=h
            return f(*args,**kwargs)
        return wrapper
    return decorator

# ── Gemini AI Round-Robin ──────────────────────────────────────────────────────
_rr_idx=0; _rr_lock=threading.Lock()

def get_hf_key():
    """Round-robin across comma-separated HuggingFace API tokens stored in Firebase."""
    global _rr_idx
    keys_raw = fb.cfg("hf_api_keys", "")
    if not keys_raw: return None
    keys = [k.strip() for k in str(keys_raw).split(",") if k.strip()]
    if not keys: return None
    with _rr_lock:
        idx  = _rr_idx % len(keys)
        _rr_idx = (idx + 1) % len(keys)
    return keys[idx]

def ai_predict(last_10, mode):
    """Call DeepSeek-R1 via HuggingFace router — same pattern as working reference code."""
    import re as _re
    from openai import OpenAI as _OAI

    key = get_hf_key()
    if not key:
        return {"error": "no_key", "number": None, "big_small": None}

    system_prompt = (
        "You are an expert AI predictor for the WinGo lottery game. "
        "Analyze the last 10 results and predict the MOST PROBABLE next number (0-9). "
        "Rules: Big = number >= 5, Small = number < 5. "
        "Return ONLY valid JSON — no markdown, no <think> tags, no extra text: "
        '{"number":<integer 0-9>,"big_small":"<Big or Small>","confidence":<integer 1-100>,"reasoning":"<one sentence>"}'
    )
    user_text = (
        f"Last 10 WinGo results (index 0 = most recent):\n{json.dumps(last_10)}\n\n"
        "Each result: number(0-9), big_small(Big>=5/Small<5), color.\n"
        "Predict the next number. Reply ONLY with JSON."
    )

    try:
        client = _OAI(
            base_url="https://router.huggingface.co/v1",
            api_key=key,
        )
        completion = client.chat.completions.create(
            model="deepseek-ai/DeepSeek-R1:novita",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_text},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        raw  = completion.choices[0].message.content or ""
        # Strip <think>...</think> chain-of-thought (DeepSeek-R1 specific)
        text = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        text = text.strip()
        # Extract first JSON object even if surrounded by text
        m = _re.search(r"\{.*?\}", text, _re.DOTALL)
        if m: text = m.group(0)
        data = json.loads(text)
        num  = max(0, min(9, int(data.get("number", 0))))
        return {
            "number":     num,
            "big_small":  "Big" if num >= 5 else "Small",
            "confidence": int(data.get("confidence", 70)),
            "reasoning":  str(data.get("reasoning", ""))[:200],
            "error":      None,
        }
    except Exception as e:
        print(f"[HF-DEEPSEEK] {e}")
        return {"error": str(e), "number": None, "big_small": None}

# ── WinGo Proxy ────────────────────────────────────────────────────────────────
@app.route("/wingo_api")
@rate_limit(60,60)
def wingo_api():
    game=request.args.get("game","WinGo_3M"); dtype=request.args.get("type","current")
    from wingo_proxy import fetch_wingo
    data=fetch_wingo(game,dtype)
    resp=jsonify(data)
    resp.headers["Access-Control-Allow-Origin"]="*"
    resp.headers["Cache-Control"]="no-cache"
    return resp

@app.route("/api/ai_predict",methods=["POST"])
@rate_limit(10,60)
def api_ai_predict():
    data = request.get_json(silent=True) or {}
    
    chat_id   = security.sanitize_str(str(data.get("chat_id","")),20)
    game      = security.sanitize_str(str(data.get("game","WinGo_3M")),20)
    mode      = security.sanitize_str(str(data.get("mode","3min")),20)
    period_id = security.sanitize_str(str(data.get("period_id","")),30)
    last_10   = data.get("last_10",[])
    
    try:
        timer_secs = int(data.get("timer_secs") or 0)
    except (ValueError, TypeError):
        timer_secs = 0

    if not chat_id: return jsonify({"error":"missing_chatid"}),400
    if security.check_key_ban(chat_id,""): return jsonify({"error":"banned"}),403
    if timer_secs<30: return jsonify({"error":"wait","message":"Wait for next round (timer < 30s)"}),400
    
    existing=fb.get(f"ai_predictions/{chat_id}/{period_id}")
    if existing and existing.get("prediction") is not None:
        return jsonify({"cached":True,**existing["prediction"]})
        
    prediction=ai_predict(last_10,mode)
    if prediction.get("error")=="no_key": return jsonify({"error":"AI not configured. Contact admin."}),503
    if prediction.get("error"): return jsonify({"error":f"AI error: {prediction['error'][:100]}"}),500
    
    pred_record={"chat_id":chat_id,"period_id":period_id,"game":game,"mode":mode,"prediction":prediction,"actual":None,"result":None,"time":now_str(),"ts":now_ts()}
    fb.put(f"ai_predictions/{chat_id}/{period_id}",pred_record)
    fb.patch("ai_stats/totals",{"total_predictions":(fb.get("ai_stats/totals/total_predictions") or 0)+1})
    
    return jsonify(prediction)


@app.route("/api/ai_predict_record",methods=["POST"])
@rate_limit(20,60)
def api_ai_predict_record():
    """Lightweight endpoint — just stores prediction for win/loss history. No AI call."""
    data      = request.get_json(silent=True) or {}
    
    chat_id   = security.sanitize_str(str(data.get("chat_id","")),20)
    period_id = security.sanitize_str(str(data.get("period_id","")),30)
    game      = security.sanitize_str(str(data.get("game","WinGo_3M")),20)
    mode      = security.sanitize_str(str(data.get("mode","3min")),20)
    pred      = data.get("prediction",{})
    
    if not chat_id or not period_id: return jsonify({"ok":False}),400
    if security.check_key_ban(chat_id,""): return jsonify({"ok":False}),403
    
    record = {"chat_id":chat_id,"period_id":period_id,"game":game,"mode":mode,
              "prediction":pred,"actual":None,"result":None,"time":now_str(),"ts":now_ts()}
    fb.put(f"ai_predictions/{chat_id}/{period_id}",record)
    fb.patch("ai_stats/totals",{"total_predictions":(fb.get("ai_stats/totals/total_predictions") or 0)+1})
    
    return jsonify({"ok":True})

@app.route("/api/record_result",methods=["POST"])
@rate_limit(20,60)
def api_record_result():
    data=request.get_json(silent=True) or {}
    chat_id=security.sanitize_str(str(data.get("chat_id","")),20)
    period_id=security.sanitize_str(str(data.get("period_id","")),30)
    
    try:
        actual=int(data.get("actual_number",-1))
    except (ValueError, TypeError):
        actual=-1
        
    if not chat_id or actual<0: return jsonify({"ok":False}),400
    
    pred_record=fb.get(f"ai_predictions/{chat_id}/{period_id}")
    if not pred_record: return jsonify({"ok":False,"reason":"no_prediction"})
    
    pred_num=pred_record.get("prediction",{}).get("number")
    if pred_num is None: return jsonify({"ok":False,"reason":"no_number"})
    
    win=(int(pred_num)==int(actual)); result_str="win" if win else "loss"
    fb.patch(f"ai_predictions/{chat_id}/{period_id}",{"actual":actual,"result":result_str})
    ust=fb.get(f"ai_user_stats/{chat_id}") or {"wins":0,"losses":0,"total":0}
    fb.put(f"ai_user_stats/{chat_id}",{"chat_id":chat_id,"wins":ust.get("wins",0)+(1 if win else 0),"losses":ust.get("losses",0)+(0 if win else 1),"total":ust.get("total",0)+1})
    tot=fb.get("ai_stats/totals") or {}
    fb.patch("ai_stats/totals",{"total_wins":tot.get("total_wins",0)+(1 if win else 0),"total_losses":tot.get("total_losses",0)+(0 if win else 1),"total_predictions":tot.get("total_predictions",1)})
    
    return jsonify({"ok":True,"win":win,"result":result_str})

# ── Website ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    bot_username=fb.cfg("bot_username") or "PredictorBot"
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Predictor App</title>
<style>body{{margin:0;background:#050807;color:#00ff41;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid #00ff4155;padding:40px 30px;max-width:400px}}h2{{font-size:22px;margin-bottom:16px}}p{{color:#a0a0a0;margin-bottom:24px;line-height:1.6}}
a{{display:inline-block;background:#00ff41;color:#050807;font-weight:700;padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:2px}}</style>
</head><body><div class="box"><h2>⚠️ BROWSER ACCESS DENIED</h2>
<p>This application can only be accessed through the official Telegram bot.</p>
<a href="https://t.me/{bot_username}">OPEN IN TELEGRAM</a></div></body></html>""",200

@app.route("/app")
@rate_limit(30,60)
def predictor_app():
    chat_id=security.sanitize_str(request.args.get("chatid",""),20)
    token=security.sanitize_str(request.args.get("t",""),60)
    bot_username=fb.cfg("bot_username") or "PredictorBot"
    def err_page(title,msg,color):
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{margin:0;background:#050807;color:#00ff41;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:20px}}
.box{{border:2px solid {color}55;padding:40px 30px;max-width:400px}}h2{{color:{color};font-size:22px;margin-bottom:16px}}p{{color:#a0a0a0;margin-bottom:24px;line-height:1.6}}
a{{display:inline-block;background:#00ff41;color:#050807;font-weight:700;padding:14px 28px;text-decoration:none;font-size:14px;letter-spacing:2px}}</style>
</head><body><div class="box"><h2>{title}</h2><p>{msg}</p><a href="https://t.me/{bot_username}">OPEN TELEGRAM BOT</a></div></body></html>""",403
    if not chat_id or not token: return err_page("⚠️ ACCESS DENIED","Access via Telegram bot only.","#ff0033")
    if not security.verify_site_token(token,chat_id): return err_page("⏳ LINK EXPIRED","Get a new link from the bot → License Key.","orange")
    if security.check_key_ban(chat_id,""): return err_page("🚫 BANNED","Your account has been permanently banned.","#ff0033")
    user=fb.get(f"users/{chat_id}") or {}
    display_name=user.get("first_name") or user.get("full_name") or chat_id
    site_settings=fb.get("settings") or {}
    cfg_data=fb.get_config() or {}
    from bot import _get_active_license
    lic=_get_active_license(chat_id) or {}
    # Pass ALL gemini keys — browser will round-robin client-side
    gemini_keys_raw = fb.cfg("hf_api_keys","") or ""
    gemini_keys_list = [k.strip() for k in gemini_keys_raw.split(",") if k.strip()]
    return render_template("predictor.html",chat_id=chat_id,display_name=display_name,
        site_settings=json.dumps(site_settings),cfg=json.dumps(cfg_data),
        expiry_str=lic.get("expiry_str",""),
        gemini_keys=json.dumps(gemini_keys_list))

@app.route("/api/validate_key",methods=["POST"])
@rate_limit(10,60)
def api_validate_key():
    data=request.get_json(silent=True) or {}
    key_raw=security.sanitize_str(data.get("key",""),25).upper().strip()
    chat_id=security.sanitize_str(data.get("chat_id",""),20)
    device_fp=security.sanitize_str(data.get("device_fp",""),100)
    ip=get_ip(); ua=request.headers.get("User-Agent","")
    if not key_raw or not chat_id: return jsonify({"error":"missing_params"}),400
    if security.check_key_ban(chat_id,device_fp): return jsonify({"error":"banned","message":"Account banned."}),403
    if not security.validate_license_key_format(key_raw): return jsonify({"error":"invalid_format"}),400
    fb_key=key_raw.replace("-","_"); lic=fb.get(f"licenses/{fb_key}")
    if not lic:
        r=security.record_wrong_key(chat_id,device_fp,"","",ip)
        if r["banned"]: return jsonify({"error":"banned","message":"Permanently banned (5 wrong keys)."}),403
        return jsonify({"error":"not_found","attempts":r["attempts"]}),404
    if not lic.get("active"):
        r=security.record_wrong_key(chat_id,device_fp,"","",ip)
        if r["banned"]: return jsonify({"error":"banned"}),403
        return jsonify({"error":"inactive","attempts":r["attempts"]}),403
    if lic.get("expiry",0)<now_ts(): return jsonify({"error":"expired"}),403
    if lic.get("chat_id") and str(lic["chat_id"])!=str(chat_id):
        r=security.record_wrong_key(chat_id,device_fp,"","",ip)
        if r["banned"]: return jsonify({"error":"banned"}),403
        return jsonify({"error":"device_mismatch","message":"Key registered on another account.","attempts":r["attempts"]}),403
    if not lic.get("device_fp") and device_fp: fb.patch(f"licenses/{fb_key}",{"device_fp":device_fp,"chat_id":chat_id})
    expiry_str=datetime.datetime.fromtimestamp(lic["expiry"]).strftime("%Y-%m-%d %H:%M")
    fb.put(f"access_logs/{now_ts()}_{chat_id}",{"chat_id":chat_id,"ip":ip,"user_agent":ua[:200],"device_type":security.detect_device_type(ua),"time":now_str(),"ts":now_ts(),"action":"key_validated"})
    today=datetime.datetime.now().strftime("%Y-%m-%d")
    fb.patch(f"daily_stats/{today}",{"returning_visits":(fb.get(f"daily_stats/{today}/returning_visits") or 0)+1,"date":today})
    fb.delete(f"wrong_key_attempts/{chat_id}")
    return jsonify({"success":True,"client_name":lic.get("full_name") or lic.get("username") or chat_id,"expiry_str":expiry_str,"plan":lic.get("plan_label","")})

@app.route("/api/log_access",methods=["POST"])
@rate_limit(20,60)
def api_log_access():
    data=request.get_json(silent=True) or {}
    chat_id=security.sanitize_str(data.get("chat_id",""),20)
    if not chat_id: return jsonify({"ok":False}),400
    user=fb.get(f"users/{chat_id}") or {}
    fb.put(f"access_logs/{now_ts()}_{chat_id}",{"chat_id":chat_id,"username":user.get("username",""),"full_name":user.get("full_name",""),"ip":get_ip(),"user_agent":request.headers.get("User-Agent","")[:200],"device_type":security.detect_device_type(request.headers.get("User-Agent","")),"time":now_str(),"ts":now_ts(),"action":"page_view"})
    return jsonify({"ok":True})

@app.route("/kimipay_webhook",methods=["POST"])
@rate_limit(60,60)
def kimipay_webhook():
    data=request.get_json(silent=True) or request.form.to_dict()
    main_bot.handle_kimipay_webhook(data)
    return "ok",200

# ── Admin Panel ────────────────────────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def wrapper(*args,**kwargs):
        if not session.get("admin_logged_in"): return redirect(url_for("admin_login"))
        return f(*args,**kwargs)
    return wrapper

@app.route("/admin/login",methods=["GET","POST"])
@rate_limit(20,60)
def admin_login():
    ip=get_ip(); locked,_=security.check_admin_lockout(ip)
    if locked:
        if request.method=="POST": return jsonify({"error":"API service unavailable."}),503
        return render_template("admin_login.html",error="⚠️ API service temporarily unavailable.",locked=True)
    if request.method=="GET": return render_template("admin_login.html",error="",locked=False)
    uname=security.sanitize_str(request.form.get("username",""),50)
    passwd=security.sanitize_str(request.form.get("password",""),100)
    chat_id=security.sanitize_str(request.form.get("chat_id",""),20)
    if uname==ADMIN_USERNAME() and passwd==ADMIN_PASSWORD() and str(chat_id)==str(ADMIN_CHAT_ID()):
        security.clear_admin_fails(ip); session["admin_logged_in"]=True; session["admin_ip"]=ip
        return redirect(url_for("admin_dashboard"))
    attempts=security.record_admin_fail(ip); rem=max(0,security.ADMIN_MAX_ATTEMPTS-attempts)
    return render_template("admin_login.html",error=f"❌ Invalid credentials. {rem} attempts remaining.",locked=False)

@app.route("/admin/logout")
def admin_logout():
    session.clear(); return redirect(url_for("admin_login"))

@app.route("/admin")
@app.route("/admin/")
@admin_required
def admin_dashboard(): return render_template("admin_panel.html")

@app.route("/admin/api/dashboard")
@admin_required
@rate_limit(30,60)
def api_dashboard():
    users=fb.get("users") or {}; licenses=fb.get("licenses") or {}
    payments=fb.get("pending_payments") or {}; withdrawals=fb.get("withdrawals") or {}
    today=datetime.datetime.now().strftime("%Y-%m-%d"); today_stats=fb.get(f"daily_stats/{today}") or {}
    ai_totals=fb.get("ai_stats/totals") or {}
    total_income=sum(p.get("amount",0) for p in payments.values() if isinstance(p,dict) and p.get("is_paid"))
    pending_wds=sum(1 for w in withdrawals.values() if isinstance(w,dict) and w.get("status")=="pending")
    paid_count=sum(1 for p in payments.values() if isinstance(p,dict) and p.get("is_paid"))
    active_lic=sum(1 for l in licenses.values() if isinstance(l,dict) and l.get("active") and l.get("expiry",0)>now_ts())
    banned=fb.get("banned_users") or {}
    tp=ai_totals.get("total_predictions",0); tw=ai_totals.get("total_wins",0)
    return jsonify({"total_users":len(users),"total_licenses":len(licenses),"active_licenses":active_lic,"total_income_inr":fmt_inr(total_income),"paid_count":paid_count,"pending_withdrawals":pending_wds,"banned_users":len(banned),"new_users_today":today_stats.get("new_users",0),"visits_today":today_stats.get("returning_visits",0),"income_raw":total_income,"ai_total_preds":tp,"ai_wins":tw,"ai_losses":ai_totals.get("total_losses",0),"ai_accuracy":round(tw/tp*100,1) if tp>0 else 0})

@app.route("/admin/api/users")
@admin_required
@rate_limit(20,60)
def api_users():
    users=fb.get("users") or {}; result=[]
    for cid,u in users.items():
        if not isinstance(u,dict): continue
        ai_st=fb.get(f"ai_user_stats/{cid}") or {}
        result.append({"chat_id":cid,"full_name":u.get("full_name",""),"username":u.get("username",""),"wallet":u.get("wallet",0),"total_spent":u.get("total_spent",0),"refer_count":u.get("refer_count",0),"purchase_count":u.get("purchase_count",0),"created_at":u.get("created_at",""),"last_seen":u.get("last_seen",""),"banned":bool(fb.get(f"banned_users/{cid}")),"ai_wins":ai_st.get("wins",0),"ai_losses":ai_st.get("losses",0),"ai_total":ai_st.get("total",0)})
    result.sort(key=lambda x:x.get("created_at",""),reverse=True)
    return jsonify(result)

@app.route("/admin/api/users/<cid>",methods=["GET","PATCH"])
@admin_required
@rate_limit(20,60)
def api_user(cid):
    if request.method=="GET":
        u=fb.get(f"users/{cid}")
        return jsonify(u) if u else (jsonify({"error":"not found"}),404)
    data=request.get_json(silent=True) or {}
    update={k:v for k,v in data.items() if k in {"full_name","username","wallet","referred_by"}}
    if update: fb.patch(f"users/{cid}",update)
    return jsonify({"ok":True})

@app.route("/admin/api/users/<cid>/ban",methods=["POST"])
@admin_required
def api_ban_user(cid):
    u=fb.get(f"users/{cid}") or {}
    fb.put(f"banned_users/{cid}",{"chat_id":cid,"username":u.get("username",""),"full_name":u.get("full_name",""),"banned_at":now_str(),"reason":security.sanitize_str((request.json or {}).get("reason","Admin ban"),200)})
    return jsonify({"ok":True})

@app.route("/admin/api/users/<cid>/unban",methods=["POST"])
@admin_required
def api_unban_user(cid):
    fb.delete(f"banned_users/{cid}"); fb.delete(f"wrong_key_attempts/{cid}"); return jsonify({"ok":True})

@app.route("/admin/api/users/<cid>/history")
@admin_required
@rate_limit(20,60)
def api_user_history(cid):
    preds=fb.get(f"ai_predictions/{cid}") or {}
    result=sorted([v for v in preds.values() if isinstance(v,dict)],key=lambda x:x.get("ts",0),reverse=True)
    return jsonify(result)

@app.route("/admin/api/licenses")
@admin_required
@rate_limit(20,60)
def api_licenses():
    lics=fb.get("licenses") or {}; result=[]
    for lid,l in lics.items():
        if not isinstance(l,dict): continue
        exp=l.get("expiry",0); expired=exp<now_ts()
        result.append({"_id":lid,"key":l.get("key",""),"chat_id":l.get("chat_id",""),"username":l.get("username",""),"full_name":l.get("full_name",""),"plan_label":l.get("plan_label",""),"amount":l.get("amount",0),"amount_str":fmt_inr(l.get("amount",0)),"active":l.get("active",False) and not expired,"expired":expired,"expiry_str":datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M") if exp else "?","purchase_date":l.get("purchase_date",""),"created_by":l.get("created_by","")})
    result.sort(key=lambda x:x.get("purchase_date",""),reverse=True)
    return jsonify(result)

@app.route("/admin/api/licenses/create",methods=["POST"])
@admin_required
@rate_limit(10,60)
def api_create_license():
    from bot import gen_key
    data=request.get_json(silent=True) or {}
    chat_id=security.sanitize_str(str(data.get("chat_id","")),20)
    username=security.sanitize_str(data.get("username",""),50)
    full_name=security.sanitize_str(data.get("full_name",""),100)
    plan_id=security.sanitize_str(data.get("plan_id","7day"),20)
    plan=LICENSE_PLANS.get(plan_id,LICENSE_PLANS["7day"])
    key=gen_key()
    while fb.get(f"licenses/{key.replace('-','_')}"): key=gen_key()
    exp_ts=now_ts()+plan["days"]*86400; exp_str=datetime.datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d %H:%M")
    ld={"key":key,"chat_id":chat_id,"username":username,"full_name":full_name,"plan_id":plan_id,"plan_label":plan["label"],"amount":plan["amount"],"validity_days":plan["days"],"purchase_date":now_str(),"expiry":exp_ts,"expiry_str":exp_str,"active":True,"device_fp":"","created_by":"admin"}
    fb.put(f"licenses/{key.replace('-','_')}",ld)
    if chat_id: fb.put(f"user_licenses/{chat_id}/{key.replace('-','_')}",ld); fb.patch(f"users/{chat_id}",{"active_license":key})
    return jsonify({"ok":True,"key":key,"expiry_str":exp_str})

@app.route("/admin/api/licenses/<lid>",methods=["PATCH"])
@admin_required
@rate_limit(20,60)
def api_update_license(lid):
    data=request.get_json(silent=True) or {}
    update={k:v for k,v in data.items() if k in {"active","full_name","username","chat_id","expiry","plan_label","amount"}}
    if update: fb.patch(f"licenses/{lid}",update)
    return jsonify({"ok":True})

@app.route("/admin/api/licenses/<lid>/revoke",methods=["POST"])
@admin_required
def api_revoke_license(lid):
    fb.patch(f"licenses/{lid}",{"active":False}); return jsonify({"ok":True})

@app.route("/admin/api/payments")
@admin_required
@rate_limit(20,60)
def api_payments():
    payments=fb.get("pending_payments") or {}
    result=[{"order_sn":p.get("order_sn",""),"chat_id":p.get("chat_id",""),"username":p.get("username",""),"full_name":p.get("full_name",""),"amount":p.get("amount",0),"amount_str":fmt_inr(p.get("amount",0)),"is_paid":p.get("is_paid",False),"payment_url":p.get("payment_url",""),"plan_label":p.get("plan_label",""),"created_at":p.get("created_at","")} for p in payments.values() if isinstance(p,dict)]
    result.sort(key=lambda x:x.get("created_at",""),reverse=True)
    return jsonify(result)

@app.route("/admin/api/withdrawals")
@admin_required
@rate_limit(20,60)
def api_withdrawals():
    wds=fb.get("withdrawals") or {}
    result=[{"_id":w.get("wd_id",""),"chat_id":w.get("chat_id",""),"username":w.get("username",""),"full_name":w.get("full_name",""),"amount":w.get("amount",0),"amount_str":fmt_inr(w.get("amount",0)),"account":w.get("account",""),"status":w.get("status","pending"),"created_at":w.get("created_at","")} for w in wds.values() if isinstance(w,dict)]
    result.sort(key=lambda x:x.get("created_at",""),reverse=True)
    return jsonify(result)

@app.route("/admin/api/withdrawals/<wid>",methods=["PATCH"])
@admin_required
@rate_limit(10,60)
def api_update_withdrawal(wid):
    data=request.get_json(silent=True) or {}
    ns=security.sanitize_str(data.get("status",""),20)
    if ns not in ("pending","approved","rejected"): return jsonify({"error":"invalid status"}),400
    wd=fb.get(f"withdrawals/{wid}") or {}
    fb.patch(f"withdrawals/{wid}",{"status":ns,"updated_at":now_str()})
    cid=wd.get("chat_id")
    if cid:
        u=fb.get(f"users/{cid}") or {}
        if ns=="rejected": fb.patch(f"users/{cid}",{"wallet":u.get("wallet",0)+wd.get("amount",0)})
        try: main_bot.bot.send_message(cid,f"{'✅' if ns=='approved' else '❌'} *Withdrawal {ns.upper()}*\n💰 Amount: {fmt_inr(wd.get('amount',0))}\n🔖 ID: `{wid}`",parse_mode="Markdown")
        except: pass
    return jsonify({"ok":True})

@app.route("/admin/api/banned")
@admin_required
@rate_limit(20,60)
def api_banned():
    return jsonify(list((fb.get("banned_users") or {}).values()))

@app.route("/admin/api/logs")
@admin_required
@rate_limit(10,60)
def api_logs():
    logs=fb.get("access_logs") or {}
    return jsonify(sorted([v for v in logs.values() if isinstance(v,dict)],key=lambda x:x.get("ts",0),reverse=True)[:200])

@app.route("/admin/api/referrals")
@admin_required
@rate_limit(20,60)
def api_referrals():
    refs=fb.get("referrals") or {}; result=[]
    for oid,referrals in refs.items():
        if not isinstance(referrals,dict): continue
        owner=fb.get(f"users/{oid}") or {}
        for rid,rd in referrals.items():
            if not isinstance(rd,dict): continue
            result.append({"owner_id":oid,"owner_name":owner.get("full_name",""),"ref_id":rid,"ref_name":rd.get("name",""),"status":rd.get("status","pending"),"earned":rd.get("earned",0),"earned_str":fmt_inr(rd.get("earned",0)),"joined_at":rd.get("joined_at","")})
    result.sort(key=lambda x:x.get("joined_at",""),reverse=True)
    return jsonify(result)

@app.route("/admin/api/daily_stats")
@admin_required
@rate_limit(20,60)
def api_daily_stats():
    stats=fb.get("daily_stats") or {}
    return jsonify(sorted([v for v in stats.values() if isinstance(v,dict) and v.get("date")],key=lambda x:x.get("date",""),reverse=True))

@app.route("/admin/api/ai_stats")
@admin_required
@rate_limit(20,60)
def api_ai_stats():
    totals=fb.get("ai_stats/totals") or {}; user_stats=fb.get("ai_user_stats") or {}; result=[]
    for cid,st in user_stats.items():
        if not isinstance(st,dict): continue
        u=fb.get(f"users/{cid}") or {}; t=st.get("total",0); w=st.get("wins",0)
        result.append({"chat_id":cid,"full_name":u.get("full_name",""),"username":u.get("username",""),"wins":w,"losses":st.get("losses",0),"total":t,"accuracy":round(w/t*100,1) if t>0 else 0})
    result.sort(key=lambda x:x.get("total",0),reverse=True)
    tp=totals.get("total_predictions",0); tw=totals.get("total_wins",0)
    return jsonify({"totals":{"total_predictions":tp,"total_wins":tw,"total_losses":totals.get("total_losses",0),"accuracy":round(tw/tp*100,1) if tp>0 else 0},"users":result[:50]})

@app.route("/admin/api/settings",methods=["GET","POST"])
@admin_required
@rate_limit(20,60)
def api_settings():
    if request.method=="GET": return jsonify(fb.get_config())
    data=request.get_json(silent=True) or {}
    allowed={"bot_token","support_bot_token","bot_username","support_bot_username","channel_id","channel_invite","admin_chat_id","admin_username","admin_password","notify_chat_ids","support_notify_chat_ids","site_url","panel_url","kimipay_app_id","kimipay_api_key","kimipay_base_url","refer_commission","min_withdrawal","max_withdrawal","privacy_policy","terms_conditions","support_greeting","support_auto_reply","hf_api_keys","game_55club_image","wingo_game_image","maintenanceMode","maintenanceMessage","tickerText","protocols","homeVersionBadge","homeTitleWord","homeTitleNum","homeSubtitle","appMainTitle","appMainSub","joinChannelUrl","contactUrl","serverStatus","predictionLimit"}
    for k,v in data.items():
        if k in allowed: fb.put(f"config/{k}",v)
    return jsonify({"ok":True})

@app.route("/admin/api/website_settings",methods=["GET","POST"])
@admin_required
@rate_limit(20,60)
def api_website_settings():
    if request.method=="GET": return jsonify(fb.get("settings") or {})
    data=request.get_json(silent=True) or {}
    for k,v in data.items(): fb.patch("settings",{k:v})
    return jsonify({"ok":True})

@app.route("/admin/api/broadcast",methods=["POST"])
@admin_required
@rate_limit(2,60)
def api_broadcast():
    text=security.sanitize_str(request.form.get("text",""),4000)
    image_url=security.sanitize_str(request.form.get("image_url",""),500)
    btn_text=security.sanitize_str(request.form.get("btn_text",""),100)
    btn_url=security.sanitize_str(request.form.get("btn_url",""),500)
    target=request.form.get("target","main"); image_bytes=None
    if "image" in request.files:
        f=request.files["image"]
        if f and f.filename: image_bytes=f.read()
    if not text and not image_url and not image_bytes: return jsonify({"error":"No content"}),400
    ok=fail=0
    if target in ("main","both"):
        o,f_=main_bot.broadcast_message(text=text,image_url=image_url or None,image_bytes=image_bytes,inline_btn_text=btn_text or None,inline_btn_url=btn_url or None)
        ok+=o; fail+=f_
    if target in ("support","both"):
        from telebot.types import InlineKeyboardMarkup,InlineKeyboardButton
        mk=None
        if btn_text and btn_url: mk=InlineKeyboardMarkup(); mk.add(InlineKeyboardButton(btn_text,url=btn_url))
        for cid in [k for k in (fb.get("support") or {}).keys() if k!="_init"]:
            try:
                if image_bytes:
                    import io; f2=io.BytesIO(image_bytes); f2.name="img.jpg"
                    sb.support_bot.send_photo(cid,f2,caption=text or None,parse_mode="Markdown",reply_markup=mk)
                elif image_url: sb.support_bot.send_photo(cid,image_url,caption=text or None,reply_markup=mk)
                elif text: sb.support_bot.send_message(cid,text,parse_mode="Markdown",reply_markup=mk)
                ok+=1; time.sleep(0.04)
            except Exception as e: print(f"[BC] {cid}: {e}"); fail+=1
    return jsonify({"ok":True,"sent":ok,"failed":fail})

# ── Support Routes (FIXED — no target="_blank" needed, session-aware) ──────────
@app.route("/support")
@app.route("/support/")
@admin_required
def support_list():
    raw=fb.get("support") or {}; chats=[]
    for k,d in raw.items():
        if k=="_init" or not isinstance(d,dict): continue
        meta=d.get("meta",{})
        if meta: chats.append(meta)
    chats.sort(key=lambda c:c.get("last_ts",0),reverse=True)
    return render_template("support.html",chats=chats)

@app.route("/support/<cid>")
@admin_required
def support_chat(cid):
    meta=fb.get(f"support/{cid}/meta") or {}
    raw=fb.get(f"support/{cid}/messages") or {}
    msgs=sorted([v for v in raw.values() if isinstance(v,dict)],key=lambda m:m.get("ts",0))
    for mid,m in raw.items():
        if isinstance(m,dict) and m.get("from")=="user" and not m.get("read"):
            fb.patch(f"support/{cid}/messages/{mid}",{"read":True})
    fb.patch(f"support/{cid}/meta",{"unread":0})
    return render_template("support_chat.html",cid=cid,meta=meta,messages=msgs)

@app.route("/support/<cid>/send",methods=["POST"])
@admin_required
@rate_limit(30,60)
def support_send(cid):
    return jsonify(sb.admin_reply(cid,security.sanitize_str(request.form.get("text",""),4000),security.sanitize_str(request.form.get("image_url",""),500)))

@app.route("/support/<cid>/send_file",methods=["POST"])
@admin_required
@rate_limit(10,60)
def support_send_file(cid):
    f=request.files.get("file")
    if not f: return jsonify({"error":"No file"}),400
    return jsonify(sb.admin_send_file(cid,f.read(),f.filename or "file",f.content_type or "application/octet-stream",security.sanitize_str(request.form.get("text",""),1000)))

@app.route("/support/<cid>/block",methods=["POST"])
@admin_required
def support_block(cid): return jsonify(sb.block_user(cid))

@app.route("/support/<cid>/unblock",methods=["POST"])
@admin_required
def support_unblock(cid): return jsonify(sb.unblock_user(cid))

@app.route("/support/<cid>/messages")
@admin_required
@rate_limit(60,60)
def support_messages(cid):
    raw=fb.get(f"support/{cid}/messages") or {}
    return jsonify(sorted([v for v in raw.values() if isinstance(v,dict)],key=lambda m:m.get("ts",0)))

@app.route("/support/<cid>/message/<mid>/edit",methods=["POST"])
@admin_required
@rate_limit(20,60)
def support_edit(cid,mid): return jsonify(sb.admin_edit_message(cid,mid,security.sanitize_str(request.form.get("text",""),4000)))

@app.route("/support/<cid>/message/<mid>/delete",methods=["POST"])
@admin_required
@rate_limit(20,60)
def support_delete_msg(cid,mid): return jsonify(sb.admin_delete_message(cid,mid))

@app.route("/support/<cid>/clear",methods=["POST"])
@admin_required
def support_clear(cid):
    fb.delete(f"support/{cid}/messages"); fb.patch(f"support/{cid}/meta",{"last_message":"","unread":0})
    return jsonify({"ok":True})

@app.route("/support/unread_count")
@admin_required
@rate_limit(60,60)
def support_unread_count():
    raw=fb.get("support") or {}
    total=sum(d.get("meta",{}).get("unread") or 0 for k,d in raw.items() if k!="_init" and isinstance(d,dict))
    return jsonify({"count":total})

@app.route("/website/<path:filename>")
def website_static(filename): return send_from_directory("website",filename)

def _start_bots():
    threading.Thread(target=main_bot.run_bot,daemon=True).start()
    threading.Thread(target=sb.run_support_bot,daemon=True).start()

_start_bots()
if __name__=="__main__": app.run(host="0.0.0.0",port=FLASK_PORT,debug=False)
