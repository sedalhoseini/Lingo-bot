import json
import os
import random
import pytz
from datetime import datetime, time as dt_time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = {527164608}
DATA_FILE = "daily_words.json"
TIMEZONE = pytz.timezone("Asia/Tehran")

# ===== STORAGE =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"words": {}, "students": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("❌ Not allowed")
            print(f"User {user.id} tried admin command")
            return
        return await func(update, context)
    return wrapper

def pick_word(words, topic=None):
    if topic:
        topic_words = words.get(topic, [])
    else:
        topic_words = [w for t in words.values() for w in t]
    if not topic_words:
        return None
    return random.choice(topic_words)

# ===== ADMIN COMMAND =====
@admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addword <topic> <word1,word2,...>")
        return
    topic = context.args[0]
    words_list = " ".join(context.args[1:]).split(",")
    words_list = [w.strip() for w in words_list if w.strip()]
    data = load_data()
    if topic not in data["words"]:
        data["words"][topic] = []
    data["words"][topic].extend(words_list)
    save_data(data)
    await update.message.reply_text(f"✅ Added to {topic}: {', '.join(words_list)}")
    print(f"Admin added words to {topic}: {words_list}")

# ===== STUDENT COMMANDS =====
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    time_str = "09:00"
    topic = None
    if context.args:
        for arg in context.args:
            if arg.startswith("time="):
                time_str = arg.split("=")[1]
            elif arg.startswith("topic="):
                topic = arg.split("=")[1]
    data = load_data()
    data["students"][user_id] = {"time": time_str, "topic": topic}
    save_data(data)
    await update.message.reply_text(f"✅ Subscribed at {time_str}, topic: {topic or 'any'}")
    print(f"User {user_id} subscribed at {time_str}, topic: {topic}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    data = load_data()
    if user_id in data["students"]:
        data["students"].pop(user_id)
        save_data(data)
        await update.message.reply_text("✅ Unsubscribed")
        print(f"User {user_id} unsubscribed")
    else:
        await update.message.reply_text("❌ You were not subscribed")

# ===== GET WORD COMMAND =====
async def get_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    data = load_data()
    student = data["students"].get(user_id)
    if not student:
        await update.message.reply_text("❌ You are not subscribed")
        return
    topic = student.get("topic")
    word = pick_word(data["words"], topic)
    if not word:
        await update.message.reply_text("❌ No words yet")
        return
    await update.message.reply_text(f"📝 Word: {word}")
    print(f"Sent word '{word}' to {user_id}")

# ===== DEBUG =====
async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Debug received: {update.message.text}")
    print(f"Debug: {update.message.from_user.id} -> {update.message.text}")

# ===== DAILY TASK =====
async def send_daily_word(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    data = load_data()
    for user_id, info in data["students"].items():
        try:
            sub_time = info.get("time", "09:00")
            topic = info.get("topic")
            hour, minute = map(int, sub_time.split(":"))
            if now.hour == hour and now.minute == minute:
                word = pick_word(data["words"], topic)
                if word:
                    await context.bot.send_message(chat_id=int(user_id), text=f"📌 Today's word: {word}")
                    print(f"Sent word '{word}' to {user_id}")
                else:
                    await context.bot.send_message(chat_id=int(user_id), text="❌ No words available")
        except Exception as e:
            print(f"Error sending to {user_id}: {e}")

# ===== BOT SETUP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Commands
app.add_handler(CommandHandler("addword", add_word))
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("unsubscribe", unsubscribe))
app.add_handler(CommandHandler("getword", get_word))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug))

# JobQueue: check every minute
app.job_queue.run_repeating(send_daily_word, interval=60, first=1)

print("✅ Daily Word Bot running...")
app.run_polling()
