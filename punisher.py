import os
import sqlite3
import asyncio
import pytz
import textwrap
from datetime import datetime
from groq import Groq

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler,
    MessageHandler, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ADMIN_IDS = {527164608}
DB_PATH = "/opt/punisher-bot/db/daily_words.db"
DEFAULT_TZ = "Asia/Tehran"

client = Groq(api_key=GROQ_API_KEY)

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            daily_time TEXT
        );

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            level TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT
        );

        CREATE TABLE IF NOT EXISTS personal_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            level TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT
        );
        """)

# ================= AI =================
def ai_generate_full_word(word: str):
    prompt = (
        "You are an English linguist.\n\n"
        f'For the word: "{word}"\n\n'
        "Return ALL parts of speech if multiple exist.\n\n"
        "Format STRICTLY like this:\n"
        "LEVEL: A1/A2/B1/B2/C1/C2\n"
        "TOPIC: ...\n"
        "WORD: ...\n"
        "DEFINITION: ...\n"
        "EXAMPLE: ...\n"
        "PRONUNCIATION: IPA or text\n"
        "---\n"
        "(repeat if another part of speech exists)"
    )

    r = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    return r.choices[0].message.content.strip()

# ================= HELPERS =================
def pick_word(topic=None, level=None):
    with db() as c:
        q = "SELECT * FROM words"
        params = []

        if topic or level:
            q += " WHERE"
        if topic:
            q += " topic=?"
            params.append(topic)
        if level:
            if topic:
                q += " AND"
            q += " level=?"
            params.append(level)

        q += " ORDER BY RANDOM() LIMIT 1"
        return c.execute(q, params).fetchone()

async def send_word(chat, row):
    if not row:
        await chat.send_message("No word found.")
        return

    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}"
    )

    await chat.send_message(text, parse_mode="Markdown")

# ================= KEYBOARDS =================
def main_keyboard(is_admin=False):
    kb = [
        [InlineKeyboardButton("🎯 Get Word", callback_data="pick_word")],
        [InlineKeyboardButton("➕ Add Word (Manual)", callback_data="add_manual")],
        [InlineKeyboardButton("🤖 Add Word (AI)", callback_data="add_ai")],
        [InlineKeyboardButton("📚 My Words", callback_data="my_words")],
    ]
    if is_admin:
        kb += [
            [InlineKeyboardButton("📦 Bulk Add", callback_data="bulk_add")],
            [InlineKeyboardButton("📋 List", callback_data="admin_list")],
            [InlineKeyboardButton("📣 Broadcast", callback_data="broadcast")],
            [InlineKeyboardButton("🗑 Clear Words", callback_data="clear_words")],
        ]
    return InlineKeyboardMarkup(kb)

def list_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("By Topic", callback_data="list_topic")],
        [InlineKeyboardButton("By Level", callback_data="list_level")],
        [InlineKeyboardButton("Just Words", callback_data="list_words")],
    ])

# ================= STATES =================
(
    ADD_TOPIC, ADD_LEVEL, ADD_WORD, ADD_DEF, ADD_EX,
    ADD_PRON, AI_WORD, BULK_ADD, BROADCAST
) = range(9)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users VALUES (?, NULL)", (uid,))
    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "pick_word":
        w = pick_word()
        await send_word(q.message, w)

    elif d == "add_manual":
        context.user_data.clear()
        await q.message.reply_text("Topic?")
        return ADD_TOPIC

    elif d == "add_ai":
        await q.message.reply_text("Send the word only:")
        return AI_WORD

    elif d == "bulk_add":
        await q.message.reply_text("Send bulk lines: topic|level|word|definition|example")
        return BULK_ADD

    elif d == "admin_list":
        await q.message.reply_text("Choose list type:", reply_markup=list_keyboard())

    elif d == "list_words":
        with db() as c:
            w = c.execute("SELECT word FROM words").fetchall()
        await q.message.reply_text("\n".join([x["word"] for x in w]) or "Empty")

    elif d == "list_level":
        with db() as c:
            l = c.execute("SELECT DISTINCT level FROM words").fetchall()
        await q.message.reply_text("\n".join([x["level"] for x in l]) or "Empty")

    elif d == "list_topic":
        with db() as c:
            t = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        await q.message.reply_text("\n".join([x["topic"] for x in t]) or "Empty")

    elif d == "clear_words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await q.message.reply_text("All words cleared.")

    elif d == "broadcast":
        await q.message.reply_text("Send broadcast message:")
        return BROADCAST

    return ConversationHandler.END

# ================= MANUAL ADD =================
async def manual_add(update, context):
    text = update.message.text.strip()

    if "topic" not in context.user_data:
        context.user_data["topic"] = text
        await update.message.reply_text("Level?")
        return ADD_LEVEL
    if "level" not in context.user_data:
        context.user_data["level"] = text
        await update.message.reply_text("Word?")
        return ADD_WORD
    if "word" not in context.user_data:
        context.user_data["word"] = text
        await update.message.reply_text("Definition?")
        return ADD_DEF
    if "definition" not in context.user_data:
        context.user_data["definition"] = text
        await update.message.reply_text("Example?")
        return ADD_EX
    if "example" not in context.user_data:
        context.user_data["example"] = text
        await update.message.reply_text("Send pronunciation text or audio:")
        return ADD_PRON

async def save_pron(update, context):
    pron = update.message.text if update.message.text else "Audio received"
    d = context.user_data
    with db() as c:
        c.execute(
            "INSERT INTO words VALUES (NULL,?,?,?,?,?,?)",
            (d["topic"], d["level"], d["word"], d["definition"], d["example"], pron)
        )
    await update.message.reply_text("Word saved.")
    context.user_data.clear()
    return ConversationHandler.END

# ================= AI ADD =================
async def ai_add(update, context):
    word = update.message.text.strip()
    ai_text = ai_generate_full_word(word)

    blocks = ai_text.split("---")
    with db() as c:
        for b in blocks:
            lines = {l.split(":",1)[0]:l.split(":",1)[1].strip() for l in b.splitlines() if ":" in l}
            c.execute(
                "INSERT INTO words VALUES (NULL,?,?,?,?,?,?)",
                (
                    lines.get("TOPIC"),
                    lines.get("LEVEL"),
                    lines.get("WORD"),
                    lines.get("DEFINITION"),
                    lines.get("EXAMPLE"),
                    lines.get("PRONUNCIATION"),
                )
            )

    await update.message.reply_text("AI word(s) added successfully.")
    return ConversationHandler.END

# ================= BULK =================
async def bulk_add(update, context):
    ok = 0
    with db() as c:
        for l in update.message.text.splitlines():
            try:
                t, lv, w, d, e = l.split("|")
                c.execute(
                    "INSERT INTO words VALUES (NULL,?,?,?,?,?,?)",
                    (t, lv, w, d, e, "")
                )
                ok += 1
            except:
                pass
    await update.message.reply_text(f"Added {ok} words.")
    return ConversationHandler.END

# ================= BROADCAST =================
async def broadcast(update, context):
    msg = update.message.text
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    for u in users:
        try:
            await context.bot.send_message(u["user_id"], msg)
        except:
            pass
    await update.message.reply_text("Broadcast sent.")
    return ConversationHandler.END

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler), CommandHandler("start", start)],
        states={
            ADD_TOPIC: [MessageHandler(filters.TEXT, manual_add)],
            ADD_LEVEL: [MessageHandler(filters.TEXT, manual_add)],
            ADD_WORD: [MessageHandler(filters.TEXT, manual_add)],
            ADD_DEF: [MessageHandler(filters.TEXT, manual_add)],
            ADD_EX: [MessageHandler(filters.TEXT, manual_add)],
            ADD_PRON: [MessageHandler(filters.ALL, save_pron)],
            AI_WORD: [MessageHandler(filters.TEXT, ai_add)],
            BULK_ADD: [MessageHandler(filters.TEXT, bulk_add)],
            BROADCAST: [MessageHandler(filters.TEXT, broadcast)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))

    app.run_polling()

if __name__ == "__main__":
    main()
