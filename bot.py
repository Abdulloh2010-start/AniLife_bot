from dotenv import load_dotenv
load_dotenv()

import os
import sqlite3
import threading
import time
import json
import urllib.parse
import requests
import logging

import telebot
from telebot import types
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BOT_TOKEN = "8302142533:AAFubqIIS3JBg4DeQxZW7mom0MsYYUSJsE8"
WEBHOOK_URL = "https://anilife-bot.onrender.com" 
SITE_SEARCH_BASE = "https://anilifetv.vercel.app/relizes?search="

if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set. Exiting.")
    raise SystemExit("Set BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

DB_PATH = os.environ.get("DB_PATH", "bot_subs.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS subs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    last_ids TEXT
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now'))
)
""")
conn.commit()

cache = {}

HELP_TEXT = (
    "👋 <b>AniLife_tv</b>\n\n"
    "Я могу искать аниме, давать быстрые ссылки и подписывать на новинки.\n\n"
    "Команды:\n"
    "/new <название?> — последние релизы (ссылка)\n"
    "/add <название> — подписаться\n"
    "/remove <название> — отписаться\n"
    "/list — показать подписки\n"
    "/history — история действий\n"
    "/random — случайный тайтл\n"
    "/play <название или номер серии + название> — ссылка на просмотр\n"
    "/webapp — открыть WebApp внутри Telegram\n"
    "/help — это сообщение\n"
)

def make_site_link(query: str) -> str:
    q = str(query or "").strip()
    return SITE_SEARCH_BASE + urllib.parse.quote_plus(q)

def log_history(user_id: int, action: str):
    try:
        cur.execute("INSERT INTO history(user_id, action) VALUES(?,?)", (user_id, action))
        conn.commit()
    except Exception:
        logging.exception("log_history failed")

def send_search_result(chat_id: int, query: str, label: str = None):
    """Единая функция для /play и /find — отправляет красивый ответ с инлайн-кнопками."""
    q = (query or "").strip()
    if not q:
        bot.send_message(chat_id, "Неверный запрос — укажи название.")
        return

    url = make_site_link(q)
    title = f"🔎 Результаты по: <b>{q}</b>"

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🌐 Открыть в браузере", url="https://anilifetv.vercel.app/"),
        types.InlineKeyboardButton("🚀 Открыть WebApp", url="https://anilifetv.vercel.app/")
    )
    kb.add(types.InlineKeyboardButton("🔁 Повторить поиск в чате", switch_inline_query_current_chat=q))

    bot.send_message(chat_id, f"{title}\n\nОткрыть результаты поиска по запросу — нажми кнопку ниже.", reply_markup=kb, disable_web_page_preview=False)
    log_history(chat_id, f"{label or '/find'} {q}")

@bot.message_handler(commands=['start', 'help'])
def cmd_start_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)
    log_history(message.chat.id, "/start/help")

@bot.message_handler(commands=['webapp'])
def cmd_webapp(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Открыть WebApp 🚀", web_app=types.WebAppInfo("https://anilifetv.vercel.app/")))
    bot.send_message(message.chat.id, "Нажми кнопку, чтобы открыть WebApp внутри Telegram.", reply_markup=kb)
    log_history(message.chat.id, "/webapp")

@bot.message_handler(commands=['play'])
def cmd_play(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /play <название или номер серии + название>")
        return
    query = parts[1].strip()
    send_search_result(message.chat.id, query, label="/play")

@bot.message_handler(commands=['new'])
def cmd_new(message):
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    url = make_site_link(query)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Открыть релизы", url=url))
    bot.send_message(message.chat.id, f"Последние релизы по «{query or 'всему'}':", reply_markup=kb)
    log_history(message.chat.id, f"/new {query}")

@bot.message_handler(commands=['add'])
def cmd_add(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /add <название>")
        return
    query = parts[1].strip()
    cur.execute("INSERT INTO subs(user_id, query, last_ids) VALUES(?,?,?)", (message.chat.id, query, json.dumps([])))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Подписка на «{query}» создана.")
    log_history(message.chat.id, f"/add {query}")

@bot.message_handler(commands=['remove'])
def cmd_remove(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        bot.send_message(message.chat.id, "Использование: /remove <название>")
        return
    query = parts[1].strip()
    cur.execute("DELETE FROM subs WHERE user_id=? AND query=?", (message.chat.id, query))
    conn.commit()
    bot.send_message(message.chat.id, f"❌ Отписан(а) от «{query}».")
    log_history(message.chat.id, f"/remove {query}")

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

@bot.message_handler(commands=['random'])
def cmd_random(message):
    url = "https://anilifetv.vercel.app/random"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎲 Открыть случайный тайтл", url=url))
    bot.send_message(message.chat.id, "Случайный тайтл:", reply_markup=kb)
    log_history(message.chat.id, "/random")

@bot.message_handler(func=lambda m: True)
def text_handler(message):
    text = (message.text or "").strip()
    if not text:
        return
    if text.startswith("/"):
        return
    kb = types.InlineKeyboardMarkup()
    url = make_site_link(text)
    kb.add(
        types.InlineKeyboardButton("🔎 Открыть результаты", url=url),
        types.InlineKeyboardButton("🚀 Открыть WebApp", url="https://anilifetv.vercel.app/")
    )
    bot.send_message(message.chat.id, f"Найти <b>{text}</b> — открой результат ниже.", reply_markup=kb)
    log_history(message.chat.id, f"search {text}")

def check_subs_loop(interval=1800):
    while True:
        try:
            cur.execute("SELECT id,user_id,query,last_ids FROM subs")
            rows = cur.fetchall()
            for sid, user_id, query, last_ids_json in rows:
                url = make_site_link(query)
                try:
                    bot.send_message(user_id, f"🔔 Новое (или периодическое) уведомление по «{query}»: {url}")
                except Exception:
                    logging.exception("notify err")
                cur.execute("UPDATE subs SET last_ids=? WHERE id=?", (json.dumps([query]), sid))
                conn.commit()
        except Exception:
            logging.exception("subs loop err")
        time.sleep(interval)

threading.Thread(target=check_subs_loop, args=(1800,), daemon=True).start()

app = Flask(__name__)

@app.route("/" + BOT_TOKEN, methods=['POST'])
def receive_update():
    update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
    bot.process_new_updates([update])
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

@app.route("/")
def index():
    return "Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting app on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)