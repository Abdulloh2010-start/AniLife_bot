from dotenv import load_dotenv
load_dotenv()
import os, sqlite3, threading, time, json, logging, requests, urllib.parse
from flask import Flask, request
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8302142533:AAFubqIIS3JBg4DeQxZW7mom0MsYYUSJsE8"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or "https://anilife-bot.onrender.com"
SITE_SEARCH_BASE = "https://anilifetv.vercel.app/relizes?search="
API_SEARCH = "https://anilibria.top/api/v1/app/search/releases"

if not BOT_TOKEN:
    logging.error("BOT_TOKEN missing")
    raise SystemExit("BOT_TOKEN missing")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

DB = os.environ.get("DB_PATH", "bot_subs.db")
conn = sqlite3.connect(DB, check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, query TEXT NOT NULL, last_ids TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, created_at INTEGER DEFAULT (strftime('%s','now')))")
conn.commit()

cache = {}

HELP_TEXT = (
    "👋 <b>AniLife_tv</b>\n\n"
    "Команды:\n"
    "/find <название> — поиск (покажу карточку и кнопки)\n"
    "/new <название?> — последние релизы\n"
    "/add <название> — подписаться\n"
    "/remove <название> — отписаться\n"
    "/list — подписки\n"
    "/history — история\n"
    "/play <название> — открыть на сайте\n"
    "/webapp — открыть WebApp\n"
    "/help — это сообщение\n"
)

def log_history(user_id, action):
    try:
        cur.execute("INSERT INTO history(user_id, action) VALUES(?,?)", (user_id, action))
        conn.commit()
    except Exception:
        logging.exception("log_history failed")

def make_site_link(q):
    return SITE_SEARCH_BASE + urllib.parse.quote_plus(str(q or "").strip())

def anilibria_search(query, limit=6):
    try:
        q = (query or "").strip()
        params = {"query": q if q != "" else '"my"', "limit": limit}
        r = requests.get(API_SEARCH, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data[:limit]
        return []
    except Exception:
        logging.exception("anilibria_search error")
        return []

def send_search_as_rich(chat_id, query):
    items = anilibria_search(query, limit=6)
    if not items:
        url = make_site_link(query)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Открыть результаты на сайте", url=url))
        bot.send_message(chat_id, f"Ничего не нашёл через API.\nОткрыть поиск на сайте: {url}", reply_markup=kb)
        return

    cache.setdefault(chat_id, {})
    for it in items:
        aid = str(it.get("id") or it.get("releaseId") or "")
        if aid:
            cache[chat_id][aid] = it

    first = items[0]
    title = first.get("russian") or first.get("name") or (first.get("names", {}) if isinstance(first.get("names"), dict) else {}).get("ru") or "Без названия"
    desc = first.get("description") or first.get("anons") or ""
    poster = first.get("poster") or first.get("cover") or None
    caption = f"<b>{title}</b>\n\n{(desc[:700] + '...') if len(desc) > 700 else desc}"

    kb = types.InlineKeyboardMarkup(row_width=1)
    for it in items:
        aid = str(it.get("id") or it.get("releaseId") or "")
        t = it.get("russian") or it.get("name") or (it.get("names", {}) if isinstance(it.get("names"), dict) else {}).get("ru") or "Без названия"
        kb.add(types.InlineKeyboardButton(text=(t[:45] + ("…" if len(t) > 45 else "")), callback_data=f"det|{aid}|{chat_id}"))
    kb.add(types.InlineKeyboardButton("Открыть поиск на сайте", url=make_site_link(query)))

    try:
        if poster and poster.startswith("http"):
            bot.send_photo(chat_id, poster, caption=caption, parse_mode='HTML', reply_markup=kb)
        else:
            bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=kb)
    except Exception:
        logging.exception("send_search_as_rich send error")
        bot.send_message(chat_id, f"{title}\n{make_site_link(title)}", reply_markup=kb)

@bot.message_handler(commands=['start','help'])
def cmd_start(message):
    bot.send_message(message.chat.id, HELP_TEXT)
    log_history(message.chat.id, "/start|/help")

@bot.message_handler(commands=['webapp'])
def cmd_webapp(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Открыть WebApp", web_app=types.WebAppInfo("https://anilifetv.vercel.app/")))
    bot.send_message(message.chat.id, "Открыть WebApp:", reply_markup=kb)
    log_history(message.chat.id, "/webapp")

@bot.message_handler(commands=['play'])
def cmd_play(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /play <название>")
        return
    q = parts[1].strip()
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Открыть на сайте", url=make_site_link(q)))
    bot.send_message(message.chat.id, f"Открыть: {make_site_link(q)}", reply_markup=kb)
    log_history(message.chat.id, f"/play {q}")

@bot.message_handler(commands=['find','search'])
def cmd_find(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /find <название>")
        return
    q = parts[1].strip()
    bot.send_message(message.chat.id, f"Ищу «{q}»...")
    send_search_as_rich(message.chat.id, q)
    log_history(message.chat.id, f"/find {q}")

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("det|"))
def cb_det(call):
    try:
        _, aid, orig = call.data.split("|")
        orig = int(orig)
    except Exception:
        bot.answer_callback_query(call.id, "Ошибка данных")
        return
    item = cache.get(orig, {}).get(aid) or cache.get(call.message.chat.id, {}).get(aid)
    if not item:
        bot.answer_callback_query(call.id, "Детали не найдены (кеш устарел).")
        return
    title = item.get("russian") or item.get("name") or "Без названия"
    desc = item.get("description") or item.get("anons") or ""
    poster = item.get("poster") or item.get("cover") or None
    text = f"<b>{title}</b>\n\n{(desc[:900] + '...') if len(desc) > 900 else desc}"
    try:
        if poster and poster.startswith("http"):
            bot.send_photo(call.message.chat.id, poster, caption=text, parse_mode='HTML')
        else:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML')
    except Exception:
        bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)
    log_history(call.message.chat.id, f"detail {aid}")

app = Flask(__name__)

def check_subs_loop(interval=1800):
    while True:
        try:
            cur.execute("SELECT id,user_id,query,last_ids FROM subs")
            rows = cur.fetchall()
            for sid, user_id, query, last_ids_json in rows:
                items = anilibria_search(query, limit=6)
                current_ids = [str(it.get("id") or it.get("releaseId") or "") for it in items]
                last_ids = json.loads(last_ids_json or "[]")
                new = [it for it in items if str(it.get("id") or it.get("releaseId") or "") not in last_ids]
                for ni in new:
                    title = ni.get("russian") or ni.get("name") or "Без названия"
                    try:
                        bot.send_message(user_id, f"Новый релиз по подписке «{query}»: {title}\n{make_site_link(title)}")
                    except Exception:
                        logging.exception("notify failed")
                cur.execute("UPDATE subs SET last_ids=? WHERE id=?", (json.dumps(current_ids), sid))
                conn.commit()
        except Exception:
            logging.exception("subs loop err")
        time.sleep(interval)

threading.Thread(target=check_subs_loop, args=(1800,), daemon=True).start()

@app.route("/" + BOT_TOKEN, methods=['POST'])
def receive_update():
    raw = request.get_data().decode('utf-8')
    logging.info("INCOMING UPDATE (first 1000 chars): %s", raw[:1000])
    try:
        update = telebot.types.Update.de_json(raw)
        bot.process_new_updates([update])
    except Exception:
        logging.exception("process update failed")
    return "ok", 200

@app.route("/set_webhook", methods=['GET'])
def set_webhook():
    try:
        bot.remove_webhook()
        url = WEBHOOK_URL.rstrip('/') + '/' + BOT_TOKEN
        success = bot.set_webhook(url=url)
        return ("Webhook set" if success else "Webhook failed"), 200
    except Exception:
        logging.exception("set_webhook error")
        return "error", 500

@app.route("/delete_webhook", methods=['GET'])
def delete_webhook():
    try:
        resp = requests.get(f"{TELEGRAM_API}/deleteWebhook", timeout=10)
        return resp.text, resp.status_code
    except Exception:
        logging.exception("delete_webhook error")
        return "error", 500

@app.route("/webhook_info", methods=['GET'])
def webhook_info():
    try:
        resp = requests.get(f"{TELEGRAM_API}/getWebhookInfo", timeout=10)
        return resp.text, resp.status_code
    except Exception:
        logging.exception("webhook_info error")
        return "error", 500

@app.route("/")
def index():
    return "Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("Starting on port %s", port)
    app.run(host="0.0.0.0", port=port)