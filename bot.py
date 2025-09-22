from dotenv import load_dotenv
load_dotenv()
import os, sqlite3, threading, time, json, requests, urllib.parse
import telebot
from telebot import types
from flask import Flask, request, Response
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
API_SEARCH = "https://anilibria.top/api/v1/app/search/releases"
SITE_SEARCH_BASE = "https://anilifetv.vercel.app/relizes?search="

if not BOT_TOKEN:
    logging.error("ENV BOT_TOKEN is not set. Set BOT_TOKEN and restart.")
    raise SystemExit("Set BOT_TOKEN env var")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

db_path = os.environ.get("DB_PATH", "bot_subs.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS subs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, query TEXT NOT NULL, last_ids TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, created_at INTEGER DEFAULT (strftime('%s','now')))")
conn.commit()

cache = {}

HELP_TEXT = (
    "Привет!\nЯ могу искать аниме, давать ссылки и подписывать на новинки.\n\n"
    "Команды:\n"
    "/find <название> — поиск\n"
    "/new <название?> — последние релизы по запросу\n"
    "/add <название> — подписаться\n"
    "/remove <название> — отписаться\n"
    "/list — показать подписки\n"
    "/history — история действий\n"
    "/random — случайный тайтл\n"
    "/play <название или номер серии + название> — ссылка на просмотр\n"
    "/webapp — открыть WebApp внутри Telegram\n"
    "/help — список команд"
)

def anilibria_search(query, limit=8):
    try:
        q = (query or "").strip()
        params = {"query": q if q != "" else '"my"', "limit": limit} if q == "" else {"query": q, "limit": limit}
        r = requests.get(API_SEARCH, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[:limit]
        if isinstance(data, list) and not data and q:
            try:
                r2 = requests.get(API_SEARCH, params={"query": q.split()[0], "limit": limit}, timeout=8)
                r2.raise_for_status()
                d2 = r2.json()
                if isinstance(d2, list):
                    return d2[:limit]
            except:
                pass
        return []
    except Exception as e:
        logging.exception("search err")
        return []

def make_site_link(query):
    q = str(query or "").strip()
    return SITE_SEARCH_BASE + urllib.parse.quote_plus(q)

def keyboard_for(items, chat_id):
    kb = types.InlineKeyboardMarkup()
    for it in items:
        aid = str(it.get("id") or it.get("releaseId") or "")
        title = it.get("russian") or it.get("name") or ""
        if not title:
            names = it.get("names")
            if isinstance(names, dict):
                title = names.get("ru") or next(iter(names.values()), "")
            elif isinstance(names, list):
                title = names[0] if names else ""
        if not title:
            title = "Без названия"
        row = [
            types.InlineKeyboardButton("Смотреть", url=make_site_link(title)),
            types.InlineKeyboardButton("Подробнее", callback_data=f"det|{aid}|{chat_id}")
        ]
        kb.add(*row)
    return kb

def cache_items(chat_id, items):
    cache.setdefault(chat_id, {})
    for it in items:
        aid = str(it.get("id") or it.get("releaseId") or "")
        if aid:
            cache[chat_id][aid] = it

def log_history(user_id, action):
    try:
        cur.execute("INSERT INTO history(user_id, action) VALUES(?,?)", (user_id, action))
        conn.commit()
    except Exception:
        logging.exception("log_history failed")

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.send_message(message.chat.id, HELP_TEXT)
    log_history(message.chat.id, "/start")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)
    log_history(message.chat.id, "/help")

@bot.message_handler(commands=['webapp'])
def cmd_webapp(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("Открыть WebApp 🚀", web_app=types.WebAppInfo("https://anilifetv.vercel.app/")))
    kb.add(types.KeyboardButton("Закрыть клавиатуру"))
    bot.send_message(message.chat.id, "Нажми кнопку, чтобы открыть WebApp внутри Telegram.", reply_markup=kb)
    log_history(message.chat.id, "/webapp")

@bot.message_handler(func=lambda m: getattr(m, "web_app_data", None) is not None)
def web_app_data_handler(message):
    data = message.web_app_data.data
    try:
        payload = json.loads(data)
        pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    except:
        pretty = data
    bot.send_message(message.chat.id, f"Получил данные из WebApp:\n{pretty}")
    log_history(message.chat.id, f"webapp_data {str(pretty)[:200]}")

@bot.message_handler(commands=['find', 'search'])
def cmd_find(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /find <название релиза>")
        return
    query = parts[1].strip()
    bot.send_message(message.chat.id, f"Ищу «{query}»...")
    items = anilibria_search(query, limit=8)
    if not items:
        simple = query.split()[0] if query else ""
        if simple and simple != query:
            items = anilibria_search(simple, limit=8)
    if not items:
        bot.send_message(message.chat.id, "Ничего не найдено.")
        return
    cache_items(message.chat.id, items)
    kb = keyboard_for(items, message.chat.id)
    bot.send_message(message.chat.id, f"Результаты по «{query}»: ", reply_markup=kb)
    log_history(message.chat.id, f"/find {query}")

@bot.message_handler(commands=['f'])
def cmd_f_short(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /f <название>")
        return
    message.text = "/find " + parts[1]
    bot.process_new_messages([message])

@bot.message_handler(commands=['new'])
def cmd_new(message):
    parts = (message.text or "").split(maxsplit=1)
    q = parts[1].strip() if len(parts) > 1 else ""
    items = anilibria_search(q, limit=8)
    if not items:
        bot.send_message(message.chat.id, "Ничего нового не найдено.")
        return
    cache_items(message.chat.id, items)
    kb = keyboard_for(items, message.chat.id)
    bot.send_message(message.chat.id, f"Последние релизы по «{q or 'всему'}':", reply_markup=kb)
    log_history(message.chat.id, f"/new {q}")

@bot.message_handler(commands=['add'])
def cmd_add(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /add <название>")
        return
    q = parts[1].strip()
    items = anilibria_search(q, limit=8)
    ids = [str(it.get("id") or it.get("releaseId") or "") for it in items]
    cur.execute("INSERT INTO subs (user_id, query, last_ids) VALUES (?,?,?)", (message.chat.id, q, json.dumps(ids)))
    conn.commit()
    bot.send_message(message.chat.id, f"Подписка на «{q}» создана.")
    log_history(message.chat.id, f"/add {q}")

@bot.message_handler(commands=['remove'])
def cmd_remove(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /remove <название>")
        return
    q = parts[1].strip()
    cur.execute("DELETE FROM subs WHERE user_id = ? AND query = ?", (message.chat.id, q))
    conn.commit()
    bot.send_message(message.chat.id, f"Отписан(а) от «{q}».")
    log_history(message.chat.id, f"/remove {q}")

@bot.message_handler(commands=['list'])
def cmd_list(message):
    cur.execute("SELECT query FROM subs WHERE user_id = ?", (message.chat.id,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "У тебя нет подписок.")
        return
    txt = "Твои подписки:\n" + "\n".join(f"- {r[0]}" for r in rows)
    bot.send_message(message.chat.id, txt)
    log_history(message.chat.id, "/list")

@bot.message_handler(commands=['history'])
def cmd_history(message):
    cur.execute("SELECT action, created_at FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 30", (message.chat.id,))
    rows = cur.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "История пустая.")
        return
    txt = "\n".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r[1]))}: {r[0]}" for r in rows)
    bot.send_message(message.chat.id, txt)

@bot.message_handler(commands=['random'])
def cmd_random(message):
    link = "https://anilifetv.vercel.app/random"
    bot.send_message(message.chat.id, f"Случайный тайтл: {link}")
    log_history(message.chat.id, "/random")

@bot.message_handler(commands=['calendar'])
def cmd_calendar(message):
    items = anilibria_search("", 8)
    if not items:
        bot.send_message(message.chat.id, "Не удалось получить расписание.")
        return
    cache_items(message.chat.id, items)
    bot.send_message(message.chat.id, "Последние релизы:", reply_markup=keyboard_for(items, message.chat.id))

@bot.message_handler(commands=['play'])
def cmd_play(message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Использование: /play <номер серии опционально + название релиза>")
        return
    payload = parts[1].strip()
    link = make_site_link(payload)
    bot.send_message(message.chat.id, f"Открыть в браузере: {link}")
    log_history(message.chat.id, f"/play {payload}")

@bot.message_handler(commands=['bug'])
def cmd_bug(message):
    parts = (message.text or "").split(maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""
    log_history(message.chat.id, f"/bug {text}")
    bot.send_message(message.chat.id, "Спасибо! Сообщение принято, админ увидит.")

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("det|"))
def cb_details(call):
    try:
        _, aid, orig_chat = call.data.split("|")
    except:
        bot.answer_callback_query(call.id, "Ошибка данных")
        return
    try:
        orig_chat = int(orig_chat)
    except:
        orig_chat = call.message.chat.id
    item = cache.get(orig_chat, {}).get(aid) or cache.get(call.message.chat.id, {}).get(aid)
    if not item:
        bot.answer_callback_query(call.id, "Детали не найдены (кеш устарел).")
        return
    title = item.get("russian") or item.get("name") or (item.get("names", {}).get("ru") if isinstance(item.get("names"), dict) else None) or "Без названия"
    desc = item.get("description") or item.get("anons") or ""
    poster = item.get("poster") or item.get("cover") or None
    text = f"*{title}*\n\n{desc[:900]}{'...' if len(desc) > 900 else ''}"
    try:
        if poster and poster.startswith("http"):
            bot.send_photo(call.message.chat.id, poster, caption=text, parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    except:
        bot.send_message(call.message.chat.id, text)
    bot.answer_callback_query(call.id)
    log_history(call.message.chat.id, f"detail {aid}")

@bot.message_handler(func=lambda m: True)
def text_handler(message):
    if message.text and message.text.startswith("/"):
        return
    q = (message.text or "").strip()
    if not q:
        bot.send_message(message.chat.id, "Напиши название аниме.")
        return
    items = anilibria_search(q, limit=6)
    if not items:
        bot.send_message(message.chat.id, "Ничего не найдено.")
        return
    cache_items(message.chat.id, items)
    kb = keyboard_for(items, message.chat.id)
    bot.send_message(message.chat.id, f"Результаты по «{q}»: ", reply_markup=kb)
    log_history(message.chat.id, f"search {q}")

def check_subs_loop(interval=1800):
    while True:
        try:
            cur.execute("SELECT id, user_id, query, last_ids FROM subs")
            rows = cur.fetchall()
            for r in rows:
                sid, user_id, query, last_ids_json = r
                last_ids = json.loads(last_ids_json) if last_ids_json else []
                items = anilibria_search(query, limit=8)
                current_ids = [str(it.get("id") or it.get("releaseId") or "") for it in items]
                new_items = [it for it in items if str(it.get("id") or it.get("releaseId") or "") not in last_ids]
                if new_items:
                    for ni in new_items:
                        title = ni.get("russian") or ni.get("name") or (ni.get("names", {}).get("ru") if isinstance(ni.get("names"), dict) else None) or "Без названия"
                        link = make_site_link(title)
                        try:
                            bot.send_message(user_id, f"Новый релиз по подписке «{query}»: {title}\n{link}")
                        except Exception as e:
                            logging.exception("notify err")
                    cur.execute("UPDATE subs SET last_ids = ? WHERE id = ?", (json.dumps(current_ids), sid))
                    conn.commit()
        except Exception:
            logging.exception("subs loop err")
        time.sleep(interval)

t = threading.Thread(target=check_subs_loop, args=(1800,), daemon=True)
t.start()

app = Flask(__name__)

@app.route("/" + BOT_TOKEN, methods=['POST'])
def receive_update():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

@app.route("/set_webhook", methods=['GET'])
def set_webhook():
    try:
        if not WEBHOOK_URL:
            return "Set WEBHOOK_URL env var", 400
        bot.remove_webhook()
        url = WEBHOOK_URL.rstrip('/') + '/' + BOT_TOKEN
        success = bot.set_webhook(url=url)
        return ("Webhook set" if success else "Webhook failed"), 200
    except Exception as e:
        logging.exception("set_webhook error")
        return str(e), 500

@app.route("/")
def index():
    return "Bot is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)