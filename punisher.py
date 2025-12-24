import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
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
            daily_time TEXT,
            username TEXT
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

# ================= AI =================
def ai_generate_full_word(word: str):
    prompt = f"""
You are an English linguist. Provide accurate info for '{word}'.
STRICT FORMAT:
WORD:
LEVEL:
TOPIC:
DEFINITION:
EXAMPLE:
PRONUNCIATION:
SOURCE:
---
"""
    r = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return r.choices[0].message.content.strip()

# ================= KEYBOARDS =================
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word"],
        ["📚 List Words"]
    ]
    if is_admin:
        kb.append(["📦 Bulk Add"])
        kb.append(["📣 Broadcast", "🗑 Clear Words"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def add_word_choice_keyboard():
    return ReplyKeyboardMarkup(
        [["Manual", "🤖 AI"], ["🏠 Cancel"]],
        resize_keyboard=True
    )

def list_keyboard_bottom():
    return ReplyKeyboardMarkup(
        [["Words", "My Words"], ["🧹 Clear My Words"], ["🏠 Cancel"]],
        resize_keyboard=True
    )

# ================= HELPERS =================
async def send_word(chat, row):
    if not row:
        await chat.reply_text("No word found.")
        return
    text = (
        f"*Word:* {row['word']}\n"
        f"*Level:* {row['level']}\n"
        f"*Definition:* {row['definition']}\n"
        f"*Example:* {row['example']}\n"
        f"*Pronunciation:* {row['pronunciation']}\n"
        f"*Source:* {row['source']}"
    )
    await chat.reply_text(text, parse_mode="Markdown")

def pick_word_from_db():
    with db() as c:
        return c.execute(
            "SELECT * FROM words ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

# ================= MAIN MENU =================
async def main_menu_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🎯 Get Word":
        await send_word(update.message, pick_word_from_db())
        return ConversationHandler.END

    if text == "➕ Add Word":
        context.user_data.clear()
        await update.message.reply_text(
            "Choose how to add the word:",
            reply_markup=add_word_choice_keyboard()
        )
        return 6

    if text == "📚 List Words":
        await update.message.reply_text(
            "Choose list type:",
            reply_markup=list_keyboard_bottom()
        )
        return 20

    if text == "📦 Bulk Add" and uid in ADMIN_IDS:
        await update.message.reply_text(
            "Choose bulk add type:",
            reply_markup=add_word_choice_keyboard()
        )
        return 10

    if text == "📣 Broadcast" and uid in ADMIN_IDS:
        await update.message.reply_text("Send message to broadcast:")
        return 9

    if text == "🗑 Clear Words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await update.message.reply_text(
            "All words cleared.",
            reply_markup=main_keyboard_bottom(True)
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= LIST =================
async def list_handler(update, context):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🏠 Cancel":
        await update.message.reply_text(
            "Main Menu:",
            reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
        )
        return ConversationHandler.END

    with db() as c:
        if text == "Words":
            rows = c.execute("SELECT word FROM words LIMIT 30").fetchall()
            msg = "\n".join(r["word"] for r in rows)

        elif text == "My Words":
            rows = c.execute(
                "SELECT word FROM personal_words WHERE user_id=? ORDER BY id DESC LIMIT 30",
                (uid,)
            ).fetchall()
            msg = "\n".join(r["word"] for r in rows)

        elif text == "🧹 Clear My Words":
            c.execute(
                "DELETE FROM personal_words WHERE user_id=?",
                (uid,)
            )
            await update.message.reply_text(
                "Your personal words have been cleared.",
                reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
            )
            return ConversationHandler.END

        else:
            msg = "No data."

    await update.message.reply_text(
        msg or "No words found.",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
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
    await update.message.reply_text(
        "Broadcast sent.",
        reply_markup=main_keyboard_bottom(True)
    )
    return ConversationHandler.END

# ================= START =================
async def start(update, context):
    uid = update.effective_user.id
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (uid,)
        )
    await update.message.reply_text(
        "Main Menu:",
        reply_markup=main_keyboard_bottom(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
        ],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            5: [MessageHandler(filters.ALL, save_pron)],
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_word_choice_handler)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
            10: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_choice)],
            11: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_manual)],
            12: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add_ai)],
            20: [MessageHandler(filters.TEXT & ~filters.COMMAND, list_handler)],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
