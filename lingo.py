import os
import re
import sqlite3
import json
from datetime import datetime, time
import pytz
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup
import requests
from bs4 import BeautifulSoup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

# ================= VERSION INFO =================
BOT_VERSION = "0.3.0"
VERSION_DATE = "2026-01-05"
CHANGELOG = """
• Added Source Priority Settings
• Multiple Parts of Speech are now saved separately
• Added Search Function (Word, Level, Topic)
• Improved Daily Words (Status View + Better Time Check)
"""

# ================= STATES =================
(
    MANUAL_ADD_TOPIC, MANUAL_ADD_LEVEL, MANUAL_ADD_WORD, 
    MANUAL_ADD_DEF, MANUAL_ADD_EX, MANUAL_ADD_PRON, 
    ADD_CHOICE, AI_ADD_INPUT, 
    BROADCAST_MSG, 
    BULK_CHOICE, BULK_MANUAL, BULK_AI,
    LIST_CHOICE,
    DAILY_COUNT, DAILY_TIME, DAILY_LEVEL, DAILY_POS,
    SEARCH_CHOICE, SEARCH_QUERY,
    SETTINGS_CHOICE, SETTINGS_PRIORITY
) = range(21)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "daily_words.db"

client = Groq(api_key=GROQ_API_KEY)
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Default Scraper Order
DEFAULT_SOURCES = ["Cambridge", "Merriam-Webster"]

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        # CLEANUP: Remove old personal table if exists
        c.execute("DROP TABLE IF EXISTS personal_words")
        
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            daily_enabled INTEGER DEFAULT 0,
            daily_count INTEGER,
            daily_time TEXT,
            daily_level TEXT,
            daily_pos TEXT,
            source_prefs TEXT  -- New column for source priority
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            level TEXT,
            source TEXT
        );
        
        CREATE TABLE IF NOT EXISTS sent_words (
            user_id INTEGER,
            word_id INTEGER,
            PRIMARY KEY (user_id, word_id)
        );
        """)
        
        # Migration: Check if source_prefs exists, if not add it
        try:
            c.execute("SELECT source_prefs FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN source_prefs TEXT")

# ================= SCRAPERS (Multi-POS Supported) =================
def empty_word_data(word):
    return {
        "word": word,
        "parts": "Unknown",
        "level": "Unknown",
        "definition": None,
        "example": None,
        "pronunciation": None,
        "source": None,
    }

def scrape_cambridge(word):
    url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    
    # Cambridge often has multiple blocks for different POS
    # We grab the first main one for now, but format it cleanly
    try:
        data = empty_word_data(word)
        data["source"] = "Cambridge"

        pos = soup.select_one(".pos.dpos")
        if pos: data["parts"] = pos.text.strip()

        level = soup.select_one(".epp-xref")
        if level: data["level"] = level.text.strip()

        definition = soup.select_one(".def.ddef_d")
        if definition: data["definition"] = definition.text.strip()

        example = soup.select_one(".examp.dexamp")
        if example: data["example"] = example.text.strip()

        pron = soup.select_one(".ipa")
        if pron: data["pronunciation"] = pron.text.strip()

        if data["definition"]:
            results.append(data)
    except:
        pass
        
    return results

def scrape_webster(word):
    url = f"https://www.merriam-webster.com/dictionary/{word}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    results = []

    try:
        data = empty_word_data(word)
        data["source"] = "Merriam-Webster"

        pos = soup.select_one(".important-blue-link")
        if pos: data["parts"] = pos.text.strip()

        definition = soup.select_one(".sense.has-sn")
        if definition: data["definition"] = definition.text.strip()

        example = soup.select_one(".ex-sent")
        if example: data["example"] = example.text.strip()

        pron = soup.select_one(".pr")
        if pron: data["pronunciation"] = pron.text.strip()

        if data["definition"]:
            results.append(data)
    except:
        pass
        
    return results

# Map string names to functions
SCRAPER_MAP = {
    "Cambridge": scrape_cambridge,
    "Merriam-Webster": scrape_webster
}

def get_words_from_web(word, user_id):
    # Get User Preference
    with db() as c:
        row = c.execute("SELECT source_prefs FROM users WHERE user_id=?", (user_id,)).fetchone()
        
    if row and row["source_prefs"]:
        pref_list = json.loads(row["source_prefs"])
    else:
        pref_list = DEFAULT_SOURCES

    # Iterate in user's preferred order
    for source_name in pref_list:
        scraper = SCRAPER_MAP.get(source_name)
        if scraper:
            results = scraper(word)
            if results: return results # Return first successful source match
            
    # Fallback return empty list
    return []

# ================= AI (Multi-POS Logic) =================
def ai_generate_full_words_list(word: str):
    # This prompt forces AI to output JSON-like blocks we can parse easily
    prompt = f"""
    You are a linguist. Analyze the word: "{word}".
    If it has multiple parts of speech (e.g. 'drink' is a Verb AND a Noun), output them as SEPARATE items.
    
    STRICT FORMAT:
    Item 1
    Word: {word}
    POS: [Noun/Verb/etc]
    Level: [A1-C2]
    Def: [Definition]
    Ex: [Example sentence]
    Pron: [IPA]
    ---
    Item 2 (if exists)
    ...
    """
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return r.choices[0].message.content.strip()

def parse_ai_response(text, original_word):
    # Simple parser to split the AI text block into dictionaries
    items = []
    current = {}
    
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("---") or line.startswith("Item"):
            if current and "definition" in current:
                items.append(current)
            current = {"word": original_word, "source": "AI-Enhanced"}
            continue
            
        if line.startswith("POS:"): current["parts"] = line.replace("POS:", "").strip()
        elif line.startswith("Level:"): current["level"] = line.replace("Level:", "").strip()
        elif line.startswith("Def:"): current["definition"] = line.replace("Def:", "").strip()
        elif line.startswith("Ex:"): current["example"] = line.replace("Ex:", "").strip()
        elif line.startswith("Pron:"): current["pronunciation"] = line.replace("Pron:", "").strip()

    if current and "definition" in current:
        items.append(current)
        
    return items

def ai_fill_missing(data_list):
    # Refines a list of scraped data using AI
    if not data_list: return []
    
    filled_list = []
    for data in data_list:
        missing = [k for k, v in data.items() if v is None]
        if not missing:
            filled_list.append(data)
            continue

        prompt = f"""
        Fill missing fields. Return key:value.
        Word: {data['word']}
        Context: {data}
        """
        try:
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            for line in r.choices[0].message.content.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip().lower()
                    # map keys back
                    key_map = {"def": "definition", "ex": "example", "pron": "pronunciation", "level": "level", "pos": "parts"}
                    for mk, real_k in key_map.items():
                        if mk in k and data.get(real_k) is None:
                            data[real_k] = v.strip()
        except:
            pass
        filled_list.append(data)
        
    return filled_list

# ================= KEYBOARDS =================
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word"],
        ["📚 List Words", "⏰ Daily Words"],
        ["🔍 Search", "⚙️ Settings"]
    ]
    if is_admin:
        kb.append(["📦 Bulk Add", "📣 Broadcast"])
        kb.append(["🗑 Clear Words", "🛡 Backup"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def add_word_choice_keyboard():
    return ReplyKeyboardMarkup([["Manual", "🤖 AI"], ["🏠 Cancel"]], resize_keyboard=True)

def search_keyboard():
    return ReplyKeyboardMarkup([["By Word", "By Level"], ["By Topic", "🏠 Cancel"]], resize_keyboard=True)

def settings_keyboard():
    return ReplyKeyboardMarkup([["🔄 Source Priority", "🏠 Cancel"]], resize_keyboard=True)

def priority_keyboard():
    return ReplyKeyboardMarkup([
        ["Cambridge First", "Webster First"],
        ["🏠 Cancel"]
    ], resize_keyboard=True)

# ================= HELPERS =================
async def common_cancel(update, context):
    context.user_data.clear()
    uid = update.effective_user.id
    await update.message.reply_text("🏠 Main Menu", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    return ConversationHandler.END

async def save_word_list_to_db(word_list, topic="General"):
    with db() as c:
        count = 0
        for w in word_list:
            # Ensure we don't save empty junk
            if not w.get("definition"): continue
            
            # Format word title like "Drink (Verb)"
            parts = w.get("parts", "")
            title = w["word"]
            if parts and parts.lower() != "unknown" and "(" not in title:
                title = f"{title} ({parts})"

            c.execute(
                "INSERT INTO words (topic, word, definition, example, pronunciation, level, source) VALUES (?,?,?,?,?,?,?)",
                (
                    topic,
                    title,
                    w.get("definition", ""),
                    w.get("example", ""),
                    w.get("pronunciation", ""),
                    w.get("level", "Unknown"),
                    w.get("source", "Manual")
                )
            )
            count += 1
    return count

# ================= HANDLERS =================

# --- Main Menu Routing ---
async def main_menu_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS

    if text == "🎯 Get Word":
        # (Same logic as before)
        with db() as c:
            row = c.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
        await send_word(update.message, row)
        return ConversationHandler.END

    if text == "➕ Add Word":
        await update.message.reply_text("Add Method:", reply_markup=add_word_choice_keyboard())
        return ADD_CHOICE

    if text == "⏰ Daily Words":
        # SHOW STATUS
        with db() as c:
            u = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        
        status_msg = "❌ *Currently Disabled*"
        if u and u["daily_enabled"]:
            status_msg = f"✅ *Active*\n📅 {u['daily_count']} words at {u['daily_time']}"
        
        await update.message.reply_text(
            f"{status_msg}\n\nTo change settings, enter new daily count (1-50):",
            reply_markup=ReplyKeyboardMarkup([["🏠 Cancel"]], resize_keyboard=True),
            parse_mode="Markdown"
        )
        return DAILY_COUNT

    if text == "📚 List Words":
        with db() as c:
            rows = c.execute("SELECT topic, level, word FROM words ORDER BY topic, level LIMIT 50").fetchall()
        if rows:
            msg = "\n".join(f"{r['topic']} | {r['level']} | {r['word']}" for r in rows)
        else:
            msg = "Database empty."
        await update.message.reply_text(f"📚 *Words:*\n{msg}", parse_mode="Markdown")
        return ConversationHandler.END

    if text == "🔍 Search":
        await update.message.reply_text("Search by?", reply_markup=search_keyboard())
        return SEARCH_CHOICE

    if text == "⚙️ Settings":
        await update.message.reply_text("Settings:", reply_markup=settings_keyboard())
        return SETTINGS_CHOICE

    # Admin Tools
    if is_admin:
        if text == "📦 Bulk Add":
            await update.message.reply_text("Bulk Type:", reply_markup=add_word_choice_keyboard())
            return BULK_CHOICE
        if text == "📣 Broadcast":
            await update.message.reply_text("Enter message:")
            return BROADCAST_MSG
        if text == "🗑 Clear Words":
            with db() as c: c.execute("DELETE FROM words")
            await update.message.reply_text("Cleared.")
        if text == "🛡 Backup":
            await auto_backup(context) # trigger backup manually

    return ConversationHandler.END

# --- Search Flow ---
async def search_choice(update, context):
    text = update.message.text
    if text == "🏠 Cancel": return await common_cancel(update, context)
    
    context.user_data["search_type"] = text
    await update.message.reply_text(f"Enter {text.replace('By ', '')} to search:")
    return SEARCH_QUERY

async def search_perform(update, context):
    query = update.message.text.strip()
    stype = context.user_data.get("search_type")
    
    sql = ""
    param = f"%{query}%"
    
    if stype == "By Word":
        sql = "SELECT * FROM words WHERE word LIKE ?"
    elif stype == "By Level":
        sql = "SELECT * FROM words WHERE level LIKE ?"
    elif stype == "By Topic":
        sql = "SELECT * FROM words WHERE topic LIKE ?"
    else:
        return await common_cancel(update, context)

    with db() as c:
        rows = c.execute(sql, (param,)).fetchall()
        
    if not rows:
        await update.message.reply_text("No results found.")
    else:
        msg = "\n".join(f"{r['word']} ({r['level']})" for r in rows[:40])
        if len(rows) > 40: msg += "\n...and more."
        await update.message.reply_text(f"🔍 *Results:*\n{msg}", parse_mode="Markdown")
        
    return await common_cancel(update, context)

# --- Settings / Source Priority ---
async def settings_choice(update, context):
    text = update.message.text
    if text == "🔄 Source Priority":
        await update.message.reply_text("Choose preferred dictionary:", reply_markup=priority_keyboard())
        return SETTINGS_PRIORITY
    return await common_cancel(update, context)

async def set_priority(update, context):
    text = update.message.text
    uid = update.effective_user.id
    
    prefs = []
    if text == "Cambridge First":
        prefs = ["Cambridge", "Merriam-Webster"]
    elif text == "Webster First":
        prefs = ["Merriam-Webster", "Cambridge"]
    else:
        return await common_cancel(update, context)
        
    with db() as c:
        c.execute("UPDATE users SET source_prefs=? WHERE user_id=?", (json.dumps(prefs), uid))
        
    await update.message.reply_text(f"Priority saved: {prefs[0]} first.")
    return await common_cancel(update, context)

# --- Daily Words (Improved) ---
async def daily_count_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    try:
        count = int(update.message.text)
        if not (1 <= count <= 50): raise ValueError
        context.user_data["daily_count"] = count
        await update.message.reply_text("Time (HH:MM)? (e.g. 09:30)")
        return DAILY_TIME
    except:
        await update.message.reply_text("Invalid number. 1-50:")
        return DAILY_COUNT

async def daily_time_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    t_str = update.message.text.strip()
    
    # Strict Time Check
    try:
        valid_time = datetime.strptime(t_str, "%H:%M")
        context.user_data["daily_time"] = t_str
    except ValueError:
        await update.message.reply_text("❌ Invalid time. Use HH:MM (00:00 - 23:59):")
        return DAILY_TIME

    kb = ReplyKeyboardMarkup([["A1","A2","B1"],["B2","C1"],["Skip"],["🏠 Cancel"]], resize_keyboard=True)
    await update.message.reply_text("Level?", reply_markup=kb)
    return DAILY_LEVEL

async def daily_level_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    context.user_data["daily_level"] = None if update.message.text == "Skip" else update.message.text
    kb = ReplyKeyboardMarkup([["noun","verb"],["adjective"],["Skip"],["🏠 Cancel"]], resize_keyboard=True)
    await update.message.reply_text("Part of Speech?", reply_markup=kb)
    return DAILY_POS

async def daily_pos_handler(update, context):
    if update.message.text == "🏠 Cancel": return await common_cancel(update, context)
    context.user_data["daily_pos"] = None if update.message.text == "Skip" else update.message.text
    
    uid = update.effective_user.id
    d = context.user_data
    with db() as c:
        c.execute("""
            INSERT INTO users (user_id, daily_enabled, daily_count, daily_time, daily_level, daily_pos)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                daily_enabled=1, daily_count=excluded.daily_count, daily_time=excluded.daily_time,
                daily_level=excluded.daily_level, daily_pos=excluded.daily_pos
        """, (uid, d["daily_count"], d["daily_time"], d["daily_level"], d["daily_pos"]))
        
    await update.message.reply_text("✅ Daily Words Updated!")
    return await common_cancel(update, context)

# --- Add Word (Multi-POS Logic) ---
async def add_choice(update, context):
    text = update.message.text
    if text == "🤖 AI":
        await update.message.reply_text("Send the word to analyze:")
        return AI_ADD_INPUT
    if text == "Manual":
        await update.message.reply_text("Topic?")
        return MANUAL_ADD_TOPIC
    return await common_cancel(update, context)

async def ai_add_process(update, context):
    word = update.message.text.strip()
    uid = update.effective_user.id
    await update.message.reply_text("🔍 Analyzing sources & AI...")

    # 1. Try Scrapers (List)
    scraped_data = get_words_from_web(word, uid)
    
    # 2. If scraper found nothing, OR to enrich, use AI
    if not scraped_data:
        ai_text = ai_generate_full_words_list(word)
        scraped_data = parse_ai_response(ai_text, word)
    else:
        # Fill holes in scraped data
        scraped_data = ai_fill_missing(scraped_data)

    # 3. Save ALL found entries
    count = await save_word_list_to_db(scraped_data)
    
    await update.message.reply_text(f"✅ Saved {count} entries (separate meanings/POS) to Global DB.")
    return await common_cancel(update, context)

async def manual_add_steps(update, context):
    # (Simplified manual add logic - one entry)
    # Mapping simple states 0-5 to dict keys is cleaner, 
    # but strictly sticking to flow:
    current_state = context.user_data.get("manual_step", 0)
    text = update.message.text
    
    keys = ["topic", "level", "word", "definition", "example", "pronunciation"]
    
    context.user_data[keys[current_state]] = text
    
    if current_state < 5:
        prompts = ["Level?", "Word?", "Definition?", "Example?", "Pronunciation?"]
        await update.message.reply_text(prompts[current_state])
        context.user_data["manual_step"] = current_state + 1
        return MANUAL_ADD_TOPIC + current_state + 1
    else:
        # Save
        await save_word_list_to_db([context.user_data], topic=context.user_data["topic"])
        await update.message.reply_text("Saved.")
        return await common_cancel(update, context)

# --- Formatting Helper ---
async def send_word(chat, row):
    if not row:
        await chat.reply_text("No word found.")
        return
    text = (
        f"📖 *{row['word']}*\n"
        f"🏷 {row['level']} | {row['topic']}\n"
        f"💡 {row['definition']}\n"
        f"📝 _Ex: {row['example']}_\n"
        f"🗣 {row['pronunciation']}"
    )
    await chat.reply_text(text, parse_mode="Markdown")

# --- Auto Backup ---
async def auto_backup(context):
    now = datetime.now()
    filename = f"backup_{now.strftime('%Y-%m-%d_%H-%M')}.db"
    for admin_id in ADMIN_IDS:
        try:
            with open(DB_PATH, 'rb') as f:
                await context.bot.send_document(admin_id, f, filename=filename, caption=f"Backup {now}")
        except: pass

# --- Daily Scheduler ---
async def send_daily_scheduler(context):
    tehran = pytz.timezone("Asia/Tehran")
    now_str = datetime.now(tehran).strftime("%H:%M")
    with db() as c:
        users = c.execute("SELECT * FROM users WHERE daily_enabled=1 AND daily_time=?", (now_str,)).fetchall()
    
    for u in users:
        # Logic to pick words matching user preferences (level/pos) could go here
        # For now, picks random global
        for _ in range(u["daily_count"]):
            with db() as c:
                w = c.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
            try: await send_word(context.bot, w) # Send to user
            except: pass

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Jobs
    tehran = pytz.timezone("Asia/Tehran")
    app.job_queue.run_daily(auto_backup, time=time(0,0,0, tzinfo=tehran))
    app.job_queue.run_repeating(send_daily_scheduler, interval=60, first=10)

    # Conversation
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", main_menu_handler),
            CommandHandler("version", version_command),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            ADD_CHOICE: [MessageHandler(filters.TEXT, add_choice)],
            AI_ADD_INPUT: [MessageHandler(filters.TEXT, ai_add_process)],
            
            # Manual Add Loop
            MANUAL_ADD_TOPIC: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_LEVEL: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_WORD: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_DEF: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_EX: [MessageHandler(filters.TEXT, manual_add_steps)],
            MANUAL_ADD_PRON: [MessageHandler(filters.TEXT, manual_add_steps)],

            # Daily
            DAILY_COUNT: [MessageHandler(filters.TEXT, daily_count_handler)],
            DAILY_TIME: [MessageHandler(filters.TEXT, daily_time_handler)],
            DAILY_LEVEL: [MessageHandler(filters.TEXT, daily_level_handler)],
            DAILY_POS: [MessageHandler(filters.TEXT, daily_pos_handler)],

            # Search
            SEARCH_CHOICE: [MessageHandler(filters.TEXT, search_choice)],
            SEARCH_QUERY: [MessageHandler(filters.TEXT, search_perform)],

            # Settings
            SETTINGS_CHOICE: [MessageHandler(filters.TEXT, settings_choice)],
            SETTINGS_PRIORITY: [MessageHandler(filters.TEXT, set_priority)],
        },
        fallbacks=[CommandHandler("cancel", common_cancel), MessageHandler(filters.Regex("^🏠 Cancel$"), common_cancel)]
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()

