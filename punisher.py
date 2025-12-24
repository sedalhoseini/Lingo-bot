import os
import sqlite3
from datetime import datetime
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
def main_keyboard_bottom(is_admin=False):
    kb = [
        ["🎯 Get Word", "➕ Add Word (Manual)"],
        ["🤖 Add Word (AI)", "📚 My Words"]
    ]
    if is_admin:
        kb.append(["📦 Bulk Add", "📋 List"])
        kb.append(["📣 Broadcast", "🗑 Clear Words"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def list_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("By Topic", callback_data="list_topic")],
        [InlineKeyboardButton("By Level", callback_data="list_level")],
        [InlineKeyboardButton("Just Words", callback_data="list_words")],
        [InlineKeyboardButton("🏠 Close List", callback_data="close_list")]
    ])

def paginate_keyboard(page, total_pages, prefix):
    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅ Previous", callback_data=f"{prefix}_{page-1}"))
    if page < total_pages - 1:
        kb.append(InlineKeyboardButton("Next ➡", callback_data=f"{prefix}_{page+1}"))
    kb.append(InlineKeyboardButton("🏠 Close", callback_data="close_list"))
    return InlineKeyboardMarkup([kb])

# ================= HELPERS =================
async def send_word(chat, row, is_admin=False):
    if not row:
        await chat.reply_text("No word found.")
        return

    source_text = row["source"]
    if source_text.startswith("http"):
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
    await chat.reply_text(text, parse_mode="Markdown")

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

# ================= MAIN MENU HANDLER =================
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    # 🎯 Get Word
    if text == "🎯 Get Word":
        row = pick_word_from_db()
        await send_word(update.message, row, uid in ADMIN_IDS)
        return ConversationHandler.END

    # ➕ Add Word (Manual)
    if text == "➕ Add Word (Manual)":
        await update.message.reply_text("Send topic first:")
        context.user_data.clear()
        return 0

    # 🤖 Add Word (AI)
    if text == "🤖 Add Word (AI)":
        await update.message.reply_text("Send the word to generate via AI:")
        context.user_data.clear()
        return 7

    # 📚 My Words
    if text == "📚 My Words":
        with db() as c:
            words = c.execute("SELECT * FROM personal_words WHERE user_id=?", (uid,)).fetchall()
        if not words:
            await update.message.reply_text("You have no personal words.")
            return ConversationHandler.END

        page_size = 10
        total_pages = (len(words) + page_size - 1) // page_size
        page_words = words[:page_size]
        text_msg = ""
        for row in page_words:
            source_display = f"[{row['source']}](https://{row['source'].replace('https://','')})"
            text_msg += (
                f"*Word:* {row['word']}\n"
                f"*Level:* {row['level']}\n"
                f"*Definition:* {row['definition']}\n"
                f"*Example:* {row['example']}\n"
                f"*Pronunciation:* {row['pronunciation']}\n"
                f"*Source:* {source_display}\n\n"
            )
        await update.message.reply_text(
            text_msg.strip(),
            parse_mode="Markdown",
            reply_markup=paginate_keyboard(0, total_pages, "my_words")
        )
        return ConversationHandler.END

    # 📦 Bulk Add (admin)
    if text == "📦 Bulk Add" and uid in ADMIN_IDS:
        await update.message.reply_text("Send words in format: topic|level|word|definition|example")
        return 8

    # 📋 List (admin)
    if text == "📋 List" and uid in ADMIN_IDS:
        await update.message.reply_text("Choose list type:", reply_markup=list_keyboard())
        return ConversationHandler.END

    # 📣 Broadcast (admin)
    if text == "📣 Broadcast" and uid in ADMIN_IDS:
        await update.message.reply_text("Send message to broadcast:")
        return 9

    # 🗑 Clear Words (admin)
    if text == "🗑 Clear Words" and uid in ADMIN_IDS:
        with db() as c:
            c.execute("DELETE FROM words")
        await update.message.reply_text("All words cleared.", reply_markup=main_keyboard_bottom(True))
        return ConversationHandler.END

    # fallback
    await update.message.reply_text("Unknown action.", reply_markup=main_keyboard_bottom(uid in ADMIN_IDS))
    return ConversationHandler.END

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "close_list":
        await q.message.delete()
        return ConversationHandler.END

    # MY WORDS PAGINATION
    if d.startswith("my_words"):
        page = int(d.split("_")[2]) if len(d.split("_")) > 2 else 0
        with db() as c:
            words = c.execute("SELECT * FROM personal_words WHERE user_id=? ORDER BY id", (uid,)).fetchall()
        if not words:
            await q.message.edit_text("You have no personal words.")
            return ConversationHandler.END

        page_size = 10
        total_pages = (len(words) + page_size - 1) // page_size
        start = page * page_size
        end = start + page_size
        page_words = words[start:end]

        text = ""
        for row in page_words:
            source_display = f"[{row['source']}](https://{row['source'].replace('https://','')})"
            text += (
                f"*Word:* {row['word']}\n"
                f"*Level:* {row['level']}\n"
                f"*Definition:* {row['definition']}\n"
                f"*Example:* {row['example']}\n"
                f"*Pronunciation:* {row['pronunciation']}\n"
                f"*Source:* {source_display}\n\n"
            )
        await q.message.edit_text(text.strip(), parse_mode="Markdown", reply_markup=paginate_keyboard(page, total_pages, "my_words"))
        return ConversationHandler.END

    # PICK WORD
    if d == "pick_word":
        row = pick_word_from_db()
        await send_word(q.message, row, uid in ADMIN_IDS)
        return ConversationHandler.END

    # ADMIN LIST
    if d == "admin_list" and uid in ADMIN_IDS:
        await q.message.reply_text("Choose list type:", reply_markup=list_keyboard())
        return ConversationHandler.END

    # LIST HANDLERS
    if d == "list_topic":
        with db() as c:
            topics = c.execute("SELECT DISTINCT topic FROM words").fetchall()
        text = "\n".join([t["topic"] for t in topics]) or "Empty"
        await q.message.edit_text(text)
        return ConversationHandler.END

    if d == "list_level":
        with db() as c:
            levels = c.execute("SELECT DISTINCT level FROM words").fetchall()
        text = ""
        for l in levels:
            level = l["level"]
            words = c.execute("SELECT word FROM words WHERE level=? ORDER BY word", (level,)).fetchall()
            text += f"*Level {level}:*\n" + ", ".join([w["word"] for w in words]) + "\n\n"
        await q.message.edit_text(text, parse_mode="Markdown")
        return ConversationHandler.END

    if d == "list_words":
        with db() as c:
            words = c.execute("SELECT word FROM words ORDER BY word").fetchall()
        await q.message.edit_text("\n".join([w["word"] for w in words]) or "Empty")
        return ConversationHandler.END

    return ConversationHandler.END

# ================= OTHER HANDLERS =================
# manual_add, save_pron, ai_add, bulk_add, broadcast remain unchanged
# (copy them as in your code, no changes needed)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
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
            MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            CallbackQueryHandler(button_handler)
        ],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_add)],
            5: [MessageHandler(filters.ALL, save_pron)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, ai_add)],
            8: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_add)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
