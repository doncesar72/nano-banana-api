#!/usr/bin/env python3
"""Nano Banana — бэкенд v2: каталог + аналитика + платежи"""

import io, json, os, time, logging, requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

KIE_API_KEY     = os.environ.get("KIE_API_KEY", "")
ADMIN_SECRET    = os.environ.get("ADMIN_SECRET", "change_me")
CREDITS_PER_GEN = int(os.environ.get("CREDITS_PER_GEN", "12"))
WELCOME_CREDITS = int(os.environ.get("WELCOME_CREDITS", "12"))

CREDITS_FILE   = "/tmp/credits.json"
ANALYTICS_FILE = "/tmp/analytics.json"
PAYMENTS_FILE  = "/tmp/payments.json"
CATALOG_FILE   = "/tmp/catalog.json"

KIE_API_URL    = "https://api.kie.ai/api/v1"
KIE_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Файловые хелперы ─────────────────────────────────────────
def load_json(path, default=None):
    try:
        with open(path) as f: return json.load(f)
    except: return default if default is not None else {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, ensure_ascii=False, indent=2)

def now_ts(): return int(time.time())
def today_key(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ── Кредиты ───────────────────────────────────────────────────
def get_balance(uid):
    return load_json(CREDITS_FILE).get(str(uid), 0)

def add_credits(uid, amount):
    d = load_json(CREDITS_FILE); k = str(uid)
    d[k] = d.get(k, 0) + amount; save_json(CREDITS_FILE, d); return d[k]

def set_credits(uid, amount):
    d = load_json(CREDITS_FILE); d[str(uid)] = amount
    save_json(CREDITS_FILE, d); return amount

def spend_credits(uid, amount):
    d = load_json(CREDITS_FILE); k = str(uid)
    if d.get(k, 0) < amount: return False
    d[k] -= amount; save_json(CREDITS_FILE, d); return True

def is_new_user(uid): return str(uid) not in load_json(CREDITS_FILE)

# ── Аналитика ─────────────────────────────────────────────────
def track(event, uid="", meta=None):
    data = load_json(ANALYTICS_FILE, {"events": [], "daily": {}, "users": {}})
    day  = today_key()
    data.setdefault("events", []).append({"ts": now_ts(), "event": event, "uid": uid, **(meta or {})})
    data["events"] = data["events"][-2000:]
    d = data.setdefault("daily", {}).setdefault(day, {"generations":0,"new_users":0,"revenue":0,"errors":0})
    if event == "generation_success": d["generations"] = d.get("generations",0) + 1
    elif event == "new_user":         d["new_users"]   = d.get("new_users",0) + 1
    elif event == "payment":          d["revenue"]     = d.get("revenue",0) + (meta or {}).get("amount_rub",0)
    elif event == "generation_error": d["errors"]      = d.get("errors",0) + 1
    if uid:
        u = data.setdefault("users", {}).setdefault(str(uid), {"first_seen":now_ts(),"generations":0,"last_seen":now_ts()})
        u["last_seen"] = now_ts()
        if event == "generation_success": u["generations"] = u.get("generations",0) + 1
    save_json(ANALYTICS_FILE, data)

# ── Каталог ───────────────────────────────────────────────────
DEFAULT_CATALOG = {
    "categories": [
        {"id":"trends",   "title":"🔥 Тренды",           "order":1},
        {"id":"couples",  "title":"💑 Пары и романтика",  "order":2},
        {"id":"status",   "title":"👑 Статус и лайфстайл","order":3},
        {"id":"family",   "title":"👨‍👩‍👧 Семья",             "order":4},
        {"id":"styles",   "title":"🎭 Образы и стили",   "order":5},
        {"id":"holidays", "title":"🎉 Праздники",        "order":6},
        {"id":"tools",    "title":"🛠 Инструменты",      "order":7},
    ],
    "cards": [
        {"id":"bbq_couple","category":"trends","order":1,"title":"Отдых у мангала","short":"Расслабленный стиль","emoji":"🔥","img":"img/ref_01.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Young couple relaxing near BBQ grill, private luxury house backyard, casual black hoodie and grey sweatpants, sunglasses, holding Corona beer, summer vibes, photorealistic, cinematic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"close_eyes","category":"couples","order":1,"title":"Близость","short":"Крупный план лица","emoji":"👁","img":"img/ref_02.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Extreme close-up portrait two faces side by side touching noses, pure black background, dramatic studio lighting, ultra detailed eyes, skin texture, photorealistic 4K, intimate mood","aspect":"9:16","resolution":"2K","active":True},
        {"id":"soldier","category":"family","order":1,"title":"Память поколений","short":"Эмоциональный портрет","emoji":"🎖","img":"img/ref_03.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Military uniform portrait, man holding small child who holds old black and white soldier photograph, dramatic moody lighting, dark warm tones, emotional, photorealistic cinematic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"birthday_kid","category":"holidays","order":1,"title":"День рождения","short":"Студийный портрет","emoji":"🎂","img":"img/ref_04.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Child blowing out birthday number candle on dark velvet cake, pure black background, dramatic side studio lighting, smoke trail from candle, cinematic close-up, photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"couple_bw","category":"couples","order":2,"title":"Пара ч/б заставка","short":"На телефон","emoji":"🖤","img":"img/ref_05.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Couple portrait, black and white photography, pure white studio background, man and woman smiling close together, clean minimal aesthetic, film grain texture, photorealistic 4K wallpaper","aspect":"9:16","resolution":"2K","active":True},
        {"id":"birthday_woman","category":"holidays","order":2,"title":"С детства до сейчас","short":"Творческий портрет","emoji":"🎉","img":"img/ref_06.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Young woman in elegant black blazer holding small birthday cake with number candles, childhood photo projected as glowing halo circle on grey studio background, black and silver balloons, cinematic side lighting, photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"dad_princess","category":"family","order":2,"title":"Папа и принцесса","short":"Семейный портрет","emoji":"👸","img":"img/ref_07.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Young man in crisp white shirt placing sparkling diamond tiara crown on little girl in soft pink satin dress, white studio background, soft warm natural lighting, genuine smile, photorealistic editorial 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"luxury_dinner","category":"status","order":1,"title":"Деловой ужин","short":"Luxury lifestyle","emoji":"🍷","img":"img/ref_08.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Two sophisticated businessmen at luxury fine dining restaurant, white linen tablecloth, holding premium cigars, professional waiter in waistcoat lighting cigar, dark moody upscale interior, expensive watches, cinematic low key lighting, photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"fsb_man","category":"trends","order":2,"title":"Задержание","short":"Вирусный контент","emoji":"💰","img":"img/ref_09.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Stylish young man smiling confidently standing next to matte black BMW XM car hood, special forces officers in black FSB tactical uniforms standing behind, Louis Vuitton duffle bag stuffed with cash bundles on car hood, credit cards and iPhones spread out, overcast dramatic sky, cinematic photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"fsb_woman","category":"trends","order":3,"title":"Богатая и опасная","short":"Вирусный контент","emoji":"👮‍♀️","img":"img/ref_10.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Stunning confident woman in sleek black catsuit smiling, flanked by two FSB special forces officers in full tactical gear, stacks of Russian ruble bills neatly arranged on wooden table, multiple credit cards, MacBook Pro, cinematic photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"sea_couple","category":"couples","order":3,"title":"Романтика у моря","short":"Чёрно-белое кино","emoji":"🌊","img":"img/ref_11.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Romantic couple faces close together almost kissing, dramatic stormy sea beach background, seagulls flying, classic black and white film photography style, wind blowing hair, shallow depth of field, cinematic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"bmw_night","category":"status","order":2,"title":"Ночной город","short":"Luxury lifestyle","emoji":"🚗","img":"img/ref_12.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Young man leaning confidently against polished black BMW luxury car at night, grand illuminated classical palace building background, premium Armani tracksuit, white clean sneakers, wet cobblestone street reflections, moody cinematic lighting, photorealistic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"speeder","category":"trends","order":4,"title":"Камера на трассе","short":"Вирусный контент","emoji":"📸","img":"img/ref_13.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Speed camera aerial drone shot from above capturing black Toyota Land Cruiser on highway at 113 km/h, beautiful girl standing through open sunroof arms raised wind blowing hair tongue out, guy driving with sunglasses giving thumbs up, traffic camera overlay timestamp data, black and white high contrast photography, cinematic 4K","aspect":"9:16","resolution":"2K","active":True},
        {"id":"photobooth","category":"couples","order":4,"title":"Фотобудка пары","short":"Трендовый формат","emoji":"💑","img":"img/ref_14.jpg","prompt":"Use the face from the reference photo exactly, preserve all facial features. Couple photobooth strip collage, four black and white square frames in 2x2 grid: top-left solo portrait smiling, top-right solo portrait looking away, bottom-left couple laughing together, bottom-right couple kissing, white background, authentic film grain, classic photobooth aesthetic, photorealistic 4K","aspect":"1:1","resolution":"2K","active":True},
    ]
}

def load_catalog():
    d = load_json(CATALOG_FILE, None)
    if d is None: save_json(CATALOG_FILE, DEFAULT_CATALOG); return DEFAULT_CATALOG
    return d

def save_catalog(d): save_json(CATALOG_FILE, d)

# ── KIE.AI ────────────────────────────────────────────────────
def kie_h(): return {"Authorization": f"Bearer {KIE_API_KEY}"}

def kie_upload(fb, fn):
    r = requests.post(KIE_UPLOAD_URL, headers=kie_h(),
        files={"file":(fn,io.BytesIO(fb),"image/jpeg")},
        data={"uploadPath":"images/references","fileName":fn}, timeout=60)
    r.raise_for_status(); d=r.json()
    url = d.get("data",{}).get("fileUrl") or d.get("fileUrl")
    if not url: raise ValueError(f"no fileUrl: {d}")
    return url

def kie_task(model, prompt, aspect, resolution, image_input):
    inp = {"prompt":prompt,"aspect_ratio":aspect,"resolution":resolution,"output_format":"jpg"}
    if image_input:
        inp["image_urls" if model=="google/nano-banana-edit" else "image_input"] = image_input
    r = requests.post(f"{KIE_API_URL}/jobs/createTask",
        headers={**kie_h(),"Content-Type":"application/json"},
        json={"model":model,"input":inp}, timeout=30)
    r.raise_for_status(); d=r.json()
    if d.get("code") not in (200,None): raise ValueError(d.get("msg",f"KIE {d.get('code')}"))
    return d["data"]["taskId"]

def kie_check(task_id):
    r = requests.get(f"{KIE_API_URL}/jobs/recordInfo", headers=kie_h(),
        params={"taskId":task_id}, timeout=30)
    r.raise_for_status(); task=r.json().get("data") or {}
    state=(task.get("state") or "").lower(); res={"state":state}
    if state=="success":
        rj=task.get("resultJson") or ""
        if rj:
            urls=json.loads(rj).get("resultUrls") or []
            if urls: res["imageUrl"]=urls[0]
    elif state=="fail": res["failMsg"]=task.get("failMsg") or "failed"
    return res

# ── Auth helper ───────────────────────────────────────────────
def ok_secret():
    d = request.json or {}
    return (d.get("secret") or request.args.get("secret","")) == ADMIN_SECRET

# ══════════════════════════════════════════════════════════════
#  РОУТЫ
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index(): return jsonify({"status":"ok","service":"Nano Banana API v2"})

@app.route("/admin")
@app.route("/admin.html")
def serve_admin():
    """Отдать файл admin.html"""
    from flask import send_from_directory
    base = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base, "admin.html")

@app.route("/app")
@app.route("/app.html")
@app.route("/miniapp")
def serve_app():
    """Отдать файл index.html (мини-апп)"""
    from flask import send_from_directory
    base = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base, "index.html")

@app.route("/img/<path:filename>")
def serve_img(filename):
    """Отдать картинки из папки img/"""
    from flask import send_from_directory
    base = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(os.path.join(base, "img"), filename)

@app.route("/balance")
def balance():
    uid = request.args.get("user_id","")
    if not uid: return jsonify({"error":"user_id required"}),400
    new = is_new_user(uid)
    if new: add_credits(uid, WELCOME_CREDITS); track("new_user", uid)
    return jsonify({"balance":get_balance(uid),"is_new":new})

@app.route("/catalog")
def catalog():
    d = load_catalog()
    cats  = sorted(d.get("categories",[]), key=lambda c:c.get("order",99))
    cards = sorted([c for c in d.get("cards",[]) if c.get("active",True)], key=lambda c:c.get("order",99))
    return jsonify({"categories":cats,"cards":cards})

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f: return jsonify({"error":"no file"}),400
    try: return jsonify({"fileUrl":kie_upload(f.read(), f.filename or "ref.jpg")})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/generate", methods=["POST"])
def generate():
    d=request.json or {}
    uid=str(d.get("user_id","")); prompt=d.get("prompt","").strip()
    model=d.get("model","nano-banana-2"); aspect=d.get("aspect_ratio","9:16")
    resolution=d.get("resolution","2K"); image_input=d.get("image_input") or None
    card_id=d.get("card_id","")
    if not uid or not prompt: return jsonify({"error":"user_id and prompt required"}),400
    if get_balance(uid)<CREDITS_PER_GEN: return jsonify({"error":f"Недостаточно кредитов"}),402
    try:
        task_id=kie_task(model,prompt,aspect,resolution,image_input)
        track("generation_start",uid,{"card_id":card_id})
        return jsonify({"taskId":task_id})
    except Exception as e:
        track("generation_error",uid,{"error":str(e)})
        return jsonify({"error":str(e)}),500

@app.route("/status")
def status():
    task_id=request.args.get("taskId",""); uid=str(request.args.get("user_id",""))
    card_id=request.args.get("card_id","")
    if not task_id: return jsonify({"error":"taskId required"}),400
    try:
        res=kie_check(task_id)
        if res["state"]=="success" and "imageUrl" in res:
            if uid and get_balance(uid)>=CREDITS_PER_GEN:
                spend_credits(uid,CREDITS_PER_GEN)
                track("generation_success",uid,{"card_id":card_id})
            res["balance"]=get_balance(uid)
        if res["state"]=="fail":
            res["error"]=res.pop("failMsg","Generation failed")
            track("generation_error",uid)
        return jsonify(res)
    except Exception as e: return jsonify({"error":str(e)}),500

# ── ADMIN ─────────────────────────────────────────────────────
@app.route("/admin/users")
def admin_users():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    credits=load_json(CREDITS_FILE); meta=load_json(ANALYTICS_FILE,{}).get("users",{})
    users=[{"user_id":k,"balance":v,"generations":meta.get(k,{}).get("generations",0),
            "first_seen":meta.get(k,{}).get("first_seen"),"last_seen":meta.get(k,{}).get("last_seen")}
           for k,v in sorted(credits.items(),key=lambda x:-x[1])]
    return jsonify({"users":users,"total":len(users)})

@app.route("/admin/addcredits", methods=["POST"])
def admin_addcredits():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}; uid=str(d.get("user_id","")); amt=int(d.get("amount",0))
    if not uid or amt<=0: return jsonify({"error":"user_id and amount required"}),400
    return jsonify({"user_id":uid,"added":amt,"balance":add_credits(uid,amt)})

@app.route("/admin/setcredits", methods=["POST"])
def admin_setcredits():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}; uid=str(d.get("user_id","")); amt=int(d.get("amount",0))
    if not uid or amt<0: return jsonify({"error":"invalid"}),400
    return jsonify({"user_id":uid,"balance":set_credits(uid,amt)})

@app.route("/admin/payment", methods=["POST"])
def admin_payment():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}
    uid=str(d.get("user_id","")); rub=int(d.get("amount_rub",0))
    creds=int(d.get("credits",0)); pkg=d.get("package",""); note=d.get("note","")
    if not uid or rub<=0 or creds<=0: return jsonify({"error":"invalid"}),400
    new_bal=add_credits(uid,creds)
    payments=load_json(PAYMENTS_FILE,[])
    payments.append({"id":len(payments)+1,"user_id":uid,"amount_rub":rub,
        "credits":creds,"package":pkg,"note":note,"ts":now_ts(),"date":today_key()})
    save_json(PAYMENTS_FILE,payments)
    track("payment",uid,{"amount_rub":rub,"credits":creds,"package":pkg})
    return jsonify({"user_id":uid,"balance":new_bal,"payment_id":payments[-1]["id"]})

@app.route("/admin/payments")
def admin_payments():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    payments=load_json(PAYMENTS_FILE,[])
    df=request.args.get("date","")
    if df: payments=[p for p in payments if p.get("date")==df]
    return jsonify({"payments":list(reversed(payments)),"total_rub":sum(p["amount_rub"] for p in payments),"count":len(payments)})

@app.route("/admin/analytics")
def admin_analytics():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    data=load_json(ANALYTICS_FILE,{"daily":{},"users":{},"events":[]})
    payments=load_json(PAYMENTS_FILE,[])
    credits=load_json(CREDITS_FILE,{})
    daily=data.get("daily",{}); days=sorted(daily.keys(),reverse=True)[:30]
    today=daily.get(today_key(),{})
    card_hits={}
    for e in data.get("events",[]):
        if e.get("event")=="generation_success" and e.get("card_id"):
            card_hits[e["card_id"]]=card_hits.get(e["card_id"],0)+1
    return jsonify({
        "summary":{"total_users":len(credits),"total_gen":sum(d.get("generations",0) for d in daily.values()),
            "total_revenue":sum(p["amount_rub"] for p in payments),
            "today_gen":today.get("generations",0),"today_new":today.get("new_users",0),
            "today_revenue":today.get("revenue",0),"today_errors":today.get("errors",0)},
        "daily":{d:daily[d] for d in days},
        "top_cards":sorted(card_hits.items(),key=lambda x:-x[1])[:5],
    })

@app.route("/admin/catalog")
def admin_catalog_get():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    return jsonify(load_catalog())

@app.route("/admin/catalog/card", methods=["POST"])
def admin_catalog_card():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}; cid=d.get("id","")
    if not cid: return jsonify({"error":"id required"}),400
    cat=load_catalog(); cards=cat.setdefault("cards",[])
    idx=next((i for i,c in enumerate(cards) if c["id"]==cid),None)
    if idx is not None: cards[idx]={**cards[idx],**d}
    else: cards.append(d)
    save_catalog(cat); return jsonify({"ok":True})

@app.route("/admin/catalog/card/<cid>", methods=["DELETE"])
def admin_catalog_del(cid):
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    cat=load_catalog(); cat["cards"]=[c for c in cat.get("cards",[]) if c["id"]!=cid]
    save_catalog(cat); return jsonify({"ok":True})

@app.route("/admin/catalog/card/<cid>/toggle", methods=["POST"])
def admin_catalog_toggle(cid):
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    cat=load_catalog()
    for c in cat.get("cards",[]):
        if c["id"]==cid:
            c["active"]=not c.get("active",True); save_catalog(cat)
            return jsonify({"ok":True,"active":c["active"]})
    return jsonify({"error":"not found"}),404

@app.route("/admin/catalog/category", methods=["POST"])
def admin_catalog_category():
    if not ok_secret(): return jsonify({"error":"Unauthorized"}),401
    d=request.json or {}
    if not d.get("id") or not d.get("title"): return jsonify({"error":"id and title required"}),400
    cat=load_catalog(); cats=cat.setdefault("categories",[])
    if not any(c["id"]==d["id"] for c in cats): cats.append(d); save_catalog(cat)
    return jsonify({"ok":True})

if __name__ == "__main__":
    port=int(os.environ.get("PORT",8080))
    app.run(host="0.0.0.0",port=port,debug=False)
