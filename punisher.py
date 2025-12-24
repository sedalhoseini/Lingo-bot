import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    ConversationHandler, MessageHandler, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_IDS = {527164608}
DB_PATH = "/opt/punisher-bot/db/daily_words.db"

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
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            level TEXT,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS personal_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT,
            level TEXT,
            source TEXT
        );
        """)

# ================= AI GENERATION =================
def ai_generate_full_word(word: str):
    prompt = f"""
You are an English linguist. Provide accurate info for '{word}'.
STRICT FORMAT:
WORD: <word>
LEVEL: <A1/A2/B1/B2/C1/C2>
TOPIC: <topic>
DEFINITION: <definition>
EXAMPLE: <example>
PRONUNCIATION: <IPA or text>
SOURCE: <website>
Separate each block with '---'.
"""
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return r.choices[0].message.content.strip()

# ================= KEYBOARDS =================
def main_menu(is_admin=False):
    buttons = [
        [KeyboardButton("🎯 Get Word"), KeyboardButton("📚 My Words")],
        [KeyboardButton("➕ Add Word (Manual)"), KeyboardButton("🤖 Add Word (AI)")],
    ]
    if is_admin:
        buttons += [
            [KeyboardButton("📦 Bulk Add"), KeyboardButton("📋 List")],
            [KeyboardButton("📣 Broadcast"), KeyboardButton("🗑 Clear Words")]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

# ================= HELPERS =================
async def send_word(chat, row, is_admin=False):
    if not row:
        await chat.reply_text("No word found.", reply_markup=main_menu(is_admin))
        return

    source_text = row["source"]
    if source_text.startswith("http"):  # full URL
        source_display = f"[Source]({source_text})"
    else:
        source_display = f"[{source_text}](https://{source_text.replace('https://','')})"

    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}\n"
        f"*Source:* {source_display}"
    )
    await chat.reply_text(text, parse_mode="Markdown", reply_markup=main_menu(is_admin))

def pick_word_from_db(topic=None, level=None):
    with db() as c:
        q = "SELECT * FROM words"
        params = []
        if topic:
            q += " WHERE topic=?"
            params.append(topic)
            if level:
                q += " AND level=?"
                params.append(level)
        elif level:
            q += " WHERE level=?"
            params.append(level)
        q += " ORDER BY RANDOM() LIMIT 1"
        return c.execute(q, params).fetchone()

# ================= HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS

    # ---------- MAIN MENU ----------
    if text == "🎯 Get Word":
        row = pick_word_from_db()
        await send_word(update.message, row, is_admin)
        return ConversationHandler.END

    elif text == "📚 My Words":
        with db() as c:
            words = c.execute("SELECT * FROM personal_words WHERE user_id=? ORDER BY id", (uid,)).fetchall()
        if not words:
            await update.message.reply_text("You have no personal words.", reply_markup=main_menu(is_admin))
            return ConversationHandler.END

        grouped = {}
        for w in words:
            grouped.setdefault(w["level"], []).append(w)
        msg = ""
        for level, ws in grouped.items():
            msg += f"*Level {level}:*\n"
            for w in ws:
                msg += f"- {w['word']}\n"
            msg += "\n"
        await update.message.reply_text(msg.strip(), reply_markup=main_menu(is_admin))
        return ConversationHandler.END

    elif text == "➕ Add Word (Manual)":
        context.user_data.clear()
        await update.message.reply_text("Topic?")
        return 0

    elif text == "🤖 Add Word (AI)":
        await update.message.reply_text("Send the word only:")
        return 7

    elif text == "📦 Bulk Add" and is_admin:
        await update.message.reply_text("Send bulk lines: topic|level|word|definition|example")
        return 8

    elif text == "📋 List" and is_admin:
        with db() as c:
            words = c.execute("SELECT topic, level, word FROM words ORDER BY topic, level").fetchall()
        if not words:
            await update.message.reply_text("No words yet.", reply_markup=main_menu(is_admin))
            return ConversationHandler.END

        grouped = {}
        for w in words:
            grouped.setdefault(w["topic"], {}).setdefault(w["level"], []).append(w["word"])
        msg = ""
        for topic, levels in grouped.items():
            msg += f"*Topic: {topic}*\n"
            for lvl, ws in levels.items():
                msg += f"  _Level {lvl}:_\n"
                for w in ws:
                    msg += f"    - {w}\n"
            msg += "\n"
        await update.message.reply_text(msg.strip(), reply_markup=main_menu(is_admin))
        return ConversationHandler.END

    elif text == "📣 Broadcast" and is_admin:
        await update.message.reply_text("Send broadcast message:")
        return 9

    elif text == "🗑 Clear Words" and is_admin:
        with db() as c:
            c.execute("DELETE FROM words")
        await update.message.reply_text("All words cleared.", reply_markup=main_menu(is_admin))
        return ConversationHandler.END

    # ---------- MANUAL ADD ----------
    fields = ["topic", "level", "word", "definition", "example"]
    for f in fields:
        if f not in context.user_data:
            context.user_data[f] = text
            next_prompt = {
                "topic": "Level?",
                "level": "Word?",
                "word": "Definition?",
                "definition": "Example?",
                "example": "Send pronunciation text or audio:"
            }[f]
            await update.message.reply_text(next_prompt)
            return fields.index(f)+1

    # ---------- SAVE PRON ----------
    pron = update.message.text or "Audio received"
    d = context.user_data
    with db() as c:
        c.execute(
            "INSERT INTO words VALUES (NULL,?,?,?,?,?,?,?)",
            (d["topic"], d["word"], d["definition"], d["example"], pron, d["level"], "Manual")
        )
    await update.message.reply_text("Word saved.", reply_markup=main_menu(is_admin))
    context.user_data.clear()
    return ConversationHandler.END

# ================= AI ADD =================
async def ai_add(update, context):
    word = update.message.text.strip()
    added_count = 0
    try:
        ai_text = ai_generate_full_word(word)
    except Exception:
        await update.message.reply_text("Failed to generate AI word.", reply_markup=main_menu(True))
        return ConversationHandler.END

    blocks = [b.strip() for b in ai_text.split("---") if b.strip()]
    if not blocks:
        await update.message.reply_text("No word generated.", reply_markup=main_menu(True))
        return ConversationHandler.END

    b = blocks[0]
    lines = {}
    for line in b.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            lines[key.strip().upper()] = value.strip()

    topic_val = lines.get("TOPIC", "General")
    level_val = lines.get("LEVEL", "N/A")
    word_val = lines.get("WORD", word)
    definition_val = lines.get("DEFINITION", "")
    example_val = lines.get("EXAMPLE", "")
    pronunciation_val = lines.get("PRONUNCIATION", "")
    source_val = lines.get("SOURCE", "AI")

    with db() as c:
        c.execute(
            "INSERT INTO words VALUES (NULL,?,?,?,?,?,?,?)",
            (topic_val, word_val, definition_val, example_val, pronunciation_val, level_val, source_val)
        )
        added_count += 1

    await update.message.reply_text(f"AI word added successfully. Total added: {added_count}", reply_markup=main_menu(True))
    return ConversationHandler.END

# ================= BROADCAST =================
async def broadcast(update, context):
    msg = update.message.text
    with db() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    for u in users:
        if u["user_id"] not in ADMIN_IDS:
            try:
                await context.bot.send_message(u["user_id"], msg)
            except:
                continue
    await update.message.reply_text("Broadcast sent.", reply_markup=main_menu(True))
    return ConversationHandler.END

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
    await update.message.reply_text("Main Menu:", reply_markup=main_menu(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            8: [MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
