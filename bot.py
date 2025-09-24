from dotenv import load_dotenv
load_dotenv()
import os
import sqlite3
import threading
import time
import json
import logging
import requests
import urllib.parse
import re
from flask import Flask, request, jsonify
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8302142533:AAFubqIIS3JBg4DeQxZW7mom0MsYYUSJsE8"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or "https://anilife-bot.onrender.com"
SITE_SEARCH_BASE = "https://anilifetv.vercel.app/relizes?search="
ADMIN_CHAT = int(os.environ.get("ADMIN_CHAT") or 1901197148)

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

DB_PATH = os.environ.get("DB_PATH", "bot_subs.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, query TEXT NOT NULL, last_ids TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, created_at INTEGER DEFAULT (strftime('%s','now')))")
conn.commit()

HELP_TEXT = (
    "👋 <b>AniLife_tv</b>\n\n"
    "/find <название> — найти (открыть страницу на сайте)\n"
    "/play <название> — открыть на сайте\n"
    "/new <название?> — последние релизы\n"
    "/add <название> — подписаться\n"
    "/remove <название> — отписаться\n"
    "/list — подписки\n"
    "/history — история\n"
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

def fetch_site_meta(url):
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        html = r.text
        meta = {}
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
        if m:
            meta['image'] = m.group(1)
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
        if m:
            meta['title'] = m.group(1)
        m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
        if m:
            meta['description'] = m.group(1)
        return meta
    except Exception:
        logging.exception("fetch_site_meta failed")
        return {}

def send_card_with_buttons(chat_id, query):
    url = make_site_link(query)
    meta = fetch_site_meta(url)
    title = meta.get('title') or f"Результаты по «{query}»"
    desc = meta.get('description') or ""
    image = meta.get('image')
    caption = f"<b>{title}</b>\n\n{(desc[:700] + '...') if len(desc) > 700 else desc}\n\nОткрыть в браузере: {url}"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("🌐 Открыть на сайте", url=url))
    kb.add(types.InlineKeyboardButton("🔁 Повторить поиск здесь", switch_inline_query_current_chat=query))
    kb.add(types.InlineKeyboardButton("🚀 Открыть WebApp", url="https://anilifetv.vercel.app/"))
    try:
        if image and image.startswith("http"):
            bot.send_photo(chat_id, image, caption=caption, parse_mode='HTML', reply_markup=kb)
        else:
            bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=kb)
    except Exception:
        logging.exception("send_card_with_buttons failed")
        try:
            bot.send_message(chat_id, caption, parse_mode='HTML', reply_markup=kb)
        except Exception:
            logging.exception("send_card fallback failed")

@bot.message_handler(commands=['start','help'])
def cmd_start(message):
    bot.send_message(message.chat.id, HELP_TEXT)
    log_history(message.chat.id, "/start|/help")

@bot.message_handler(commands=['webapp'])
def cmd_webapp(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Открыть WebApp 🚀", web_app=types.WebAppInfo("https://anilifetv.vercel.app/")))
    bot.send_message(message.chat.id, "Открыть WebApp:", reply_markup=kb)
    log_history(message.chat.id, "/webapp")

@bot.message_handler(commands=['play'])
def cmd_play(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /play <название>")
        return
    q = parts[1].strip()
    send_card_with_buttons(message.chat.id, q)
    log_history(message.chat.id, f"/play {q}")

@bot.message_handler(commands=['find','search'])
def cmd_find(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /find <название>")
        return
    q = parts[1].strip()
    bot.send_message(message.chat.id, f"Ищу «{q}»...")
    send_card_with_buttons(message.chat.id, q)
    log_history(message.chat.id, f"/find {q}")

@bot.message_handler(commands=['new'])
def cmd_new(message):
    parts = (message.text or "").split(maxsplit=1)
    q = parts[1].strip() if len(parts) > 1 else ""
    url = make_site_link(q)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Открыть релизы", url=url))
    bot.send_message(message.chat.id, f"Последние релизы по «{q or 'всему'}':", reply_markup=kb)
    log_history(message.chat.id, f"/new {q}")

@bot.message_handler(commands=['add'])
def cmd_add(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /add <название>")
        return
    q = parts[1].strip()
    cur.execute("INSERT INTO subs(user_id, query, last_ids) VALUES(?,?,?)", (message.chat.id, q, json.dumps([])))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Подписка на «{q}» создана.")
    log_history(message.chat.id, f"/add {q}")

@bot.message_handler(commands=['remove'])
def cmd_remove(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /remove <название>")
        return
    q = parts[1].strip()
    cur.execute("DELETE FROM subs WHERE user_id=? AND query=?", (message.chat.id, q))
    conn.commit()
    bot.send_message(message.chat.id, f"❌ Отписан(а) от «{q}».")
    log_history(message.chat.id, f"/remove {q}")

@bot.message_handler(commands=['list'])
def cmd_list(message):
    cur.execute("SELECT query FROM subs WHERE user_id=?", (message.chat.id,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "У тебя нет подписок.")
        return
    bot.send_message(message.chat.id, "📝 Твои подписки:\n" + "\n".join(f"- {r[0]}" for r in rows))
    log_history(message.chat.id, "/list")

@bot.message_handler(commands=['history'])
def cmd_history(message):
    cur.execute("SELECT action, created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 30", (message.chat.id,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "История пустая.")
        return
    txt = "\n".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r[1]))}: {r[0]}" for r in rows)
    bot.send_message(message.chat.id, txt)

@bot.message_handler(func=lambda m: True)
def text_handler(message):
    txt = (message.text or "").strip()
    if not txt or txt.startswith("/"):
        return
    send_card_with_buttons(message.chat.id, txt)
    log_history(message.chat.id, f"search {txt}")

def subs_loop(interval=1800):
    while True:
        try:
            cur.execute("SELECT id,user_id,query,last_ids FROM subs")
            rows = cur.fetchall()
            for sid, user_id, query, last_ids_json in rows:
                url = make_site_link(query)
                try:
                    bot.send_message(user_id, f"🔔 По подписке «{query}»: {url}")
                except Exception:
                    logging.exception("notify failed")
                cur.execute("UPDATE subs SET last_ids=? WHERE id=?", (json.dumps([query]), sid))
                conn.commit()
        except Exception:
            logging.exception("subs loop err")
        time.sleep(interval)

threading.Thread(target=subs_loop, args=(1800,), daemon=True).start()

app = Flask(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

@app.route("/" + BOT_TOKEN, methods=['POST'])
def receive_update():
    payload = request.get_data().decode('utf-8')
    logging.info("INCOMING UPDATE (first 2000 chars): %s", payload[:2000])
    try:
        update = telebot.types.Update.de_json(payload)
        try:
            bot.process_new_updates([update])
        except Exception:
            logging.exception("process_new_updates failed")
            try:
                bot.send_message(ADMIN_CHAT, f"process_new_updates failed. See logs.")
            except Exception:
                logging.exception("notify admin failed")
    except Exception:
        logging.exception("receive_update parse failed")
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

@app.route("/debug_send", methods=['GET'])
def debug_send():
    chat_id = request.args.get("chat_id")
    text = request.args.get("text", "test")
    if not chat_id:
        return "chat_id required", 400
    try:
        bot.send_message(int(chat_id), text)
        return "ok", 200
    except Exception:
        logging.exception("debug_send failed")
        return "error", 500

@app.route("/simulate_update", methods=['POST'])
def simulate_update():
    data = request.get_json(force=True, silent=True) or {}
    logging.info("SIMULATED UPDATE: %s", json.dumps(data)[:2000])
    try:
        update = telebot.types.Update.de_json(json.dumps(data))
        bot.process_new_updates([update])
    except Exception:
        logging.exception("simulate_update failed")
        return "error", 500
    return "ok", 200

@app.route("/")
def index():
    return "Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("Starting on port %s", port)
    app.run(host="0.0.0.0", port=port)