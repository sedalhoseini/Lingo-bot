import os
import random
import sqlite3
import pytz
from datetime import datetime
from gtts import gTTS
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {527164608}  # your Telegram ID
DB_PATH = "/opt/punisher-bot/db/daily_words.db"
DEFAULT_TZ = "Asia/Tehran"

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
            timezone TEXT,
            send_time TEXT,
            last_sent TEXT
        );
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            word TEXT,
            definition TEXT,
            example TEXT,
            pronunciation TEXT
        );
        CREATE TABLE IF NOT EXISTS seen_words (
            user_id INTEGER,
            word_id INTEGER,
            seen_date TEXT,
            PRIMARY KEY(user_id, word_id)
        );
        """)

# ================= HELPERS =================
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("Admin only.")
            return
        return await func(update, context)
    return wrapper

def pick_word(topic=None):
    with db() as c:
        if topic:
            row = c.execute(
                "SELECT * FROM words WHERE topic=? ORDER BY RANDOM() LIMIT 1",
                (topic,)
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM words ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return row

async def send_word(update, context, word_row):
    if not word_row:
        await update.message.reply_text("No words found.")
        return
    text = (
        f"📘 *{word_row['word']}*\n"
        f"{word_row['definition']}\n\n"
        f"_Example:_ {word_row['example']}"
    )
    buttons = [
        [
            InlineKeyboardButton("Mark as Seen", callback_data=f"seen_{word_row['id']}"),
            InlineKeyboardButton("Next Word", callback_data="next_word")
        ]
    ]
    if word_row['pronunciation']:
        buttons[0].append(InlineKeyboardButton("🔊 Pronounce", callback_data=f"pron_{word_row['id']}"))
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def mark_seen(user_id, word_id):
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_words (user_id, word_id, seen_date) VALUES (?, ?, ?)",
            (user_id, word_id, today)
        )

async def send_pronunciation(context, chat_id, word):
    tts = gTTS(word)
    bio = BytesIO()
    tts.write_to_fp(bio)
    bio.seek(0)
    await context.bot.send_audio(chat_id=chat_id, audio=bio, filename=f"{word}.mp3")

# ================= STUDENT HANDLERS =================
START, TOPIC, WORD, DEFN, EXAMPLE, PRON = range(6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Get Random Word", callback_data="random_word")],
        [InlineKeyboardButton("Review Seen Words", callback_data="review_seen")],
        [InlineKeyboardButton("Add Personal Word", callback_data="add_personal")]
    ]
    await update.message.reply_text(
        "Welcome! Choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "random_word" or data == "next_word":
        word = pick_word()
        await send_word(query, context, word)
    elif data.startswith("seen_"):
        word_id = int(data.split("_")[1])
        await mark_seen(user_id, word_id)
        await query.edit_message_text("Marked as seen ✅")
    elif data.startswith("pron_"):
        word_id = int(data.split("_")[1])
        with db() as c:
            row = c.execute("SELECT word FROM words WHERE id=?", (word_id,)).fetchone()
        if row:
            await send_pronunciation(context, user_id, row['word'])
    elif data == "review_seen":
        with db() as c:
            rows = c.execute(
                "SELECT w.* FROM words w JOIN seen_words s ON w.id=s.word_id WHERE s.user_id=?",
                (user_id,)
            ).fetchall()
        if not rows:
            await query.edit_message_text("You have not seen any words yet.")
        else:
            for row in rows:
                await send_word(query, context, row)
    elif data == "add_personal":
        context.user_data['personal'] = {}
        await query.edit_message_text("Enter the topic for your personal word:")
        return TOPIC

async def personal_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['personal']['topic'] = update.message.text.strip()
    await update.message.reply_text("Enter the word:")
    return WORD

async def personal_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['personal']['word'] = update.message.text.strip()
    await update.message.reply_text("Enter the definition:")
    return DEFN

async def personal_defn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['personal']['definition'] = update.message.text.strip()
    await update.message.reply_text("Enter an example sentence:")
    return EXAMPLE

async def personal_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['personal']['example'] = update.message.text.strip()
    await update.message.reply_text("Optional: Enter pronunciation text (or /skip):")
    return PRON

async def personal_pron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pron = update.message.text.strip()
    personal = context.user_data['personal']
    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
            (personal['topic'], personal['word'], personal['definition'], personal['example'], pron)
        )
    await update.message.reply_text("✅ Personal word added successfully!")
    return ConversationHandler.END

async def skip_pron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    personal = context.user_data['personal']
    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example, pronunciation) VALUES (?, ?, ?, ?, ?)",
            (personal['topic'], personal['word'], personal['definition'], personal['example'], None)
        )
    await update.message.reply_text("✅ Personal word added successfully!")
    return ConversationHandler.END

# ================= DAILY JOB =================
async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        users = c.execute("SELECT * FROM users").fetchall()

    for u in users:
        tz = pytz.timezone(u["timezone"])
        now = datetime.now(tz)
        hour, minute = map(int, u["send_time"].split(":"))

        if now.hour != hour or now.minute != minute:
            continue

        today = now.strftime("%Y-%m-%d")
        if u["last_sent"] == today:
            continue

        word = pick_word()
        if not word:
            continue

        text = (
            f"📘 *Word of the Day*\n\n"
            f"*{word['word']}*\n"
            f"{word['definition']}\n\n"
            f"_Example:_ {word['example']}"
        )

        await context.bot.send_message(
            chat_id=u["user_id"],
            text=text,
            parse_mode="Markdown"
        )

        with db() as c:
            c.execute(
                "UPDATE users SET last_sent=? WHERE user_id=?",
                (today, u["user_id"])
            )

# ================= ADMIN COMMANDS =================
@admin_only
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 4:
        await update.message.reply_text("Usage: /addword <topic> <word> <definition> <example>")
        return
    topic, word = context.args[0], context.args[1]
    definition = context.args[2]
    example = " ".join(context.args[3:])
    with db() as c:
        c.execute(
            "INSERT INTO words (topic, word, definition, example) VALUES (?, ?, ?, ?)",
            (topic, word, definition, example)
        )
    await update.message.reply_text("✅ Word added successfully!")

# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Student conversation handler for adding personal word
    personal_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="add_personal")],
        states={
            TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, personal_topic)],
            WORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, personal_word)],
            DEFN: [MessageHandler(filters.TEXT & ~filters.COMMAND, personal_defn)],
            EXAMPLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, personal_example)],
            PRON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, personal_pron),
                CommandHandler("skip", skip_pron)
            ]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(personal_conv)
    app.add_handler(CommandHandler("addword", addword))

    app.job_queue.run_repeating(daily_job, interval=60, first=10)
    app.run_polling()

if __name__ == "__main__":
    main()
