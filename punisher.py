import os
import json
import random
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {527164608}
DATA_FILE = "daily_words.json"
TEHRAN = pytz.timezone("Asia/Tehran")

# Load data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = {"topics": {}, "subscriptions": {}}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is alive! Use /subscribe to get daily words.")

# Send a word to a user
async def send_word(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    sub = data["subscriptions"].get(str(user_id))
    if not sub:
        return
    all_words = []
    for words in data["topics"].values():
        all_words.extend(words)
    if not all_words:
        await context.bot.send_message(chat_id=user_id, text="No words available yet.")
        return
    word = random.choice(all_words)
    await context.bot.send_message(chat_id=user_id, text=f"📌 Today's word: {word}")
    print(f"Sent word '{word}' to {user_id}")

# Job: Check every minute for users to send daily words
async def check_daily_words(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TEHRAN)
    for user_id, sub in data["subscriptions"].items():
        user_time = sub.get("time", "08:00")
        hour, minute = map(int, user_time.split(":"))
        if now.hour == hour and now.minute == minute:
            await send_word(int(user_id), context)

# Student commands
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data["subscriptions"].setdefault(user_id, {"time": "08:00"})
    save_data()
    await update.message.reply_text("Subscribed to daily words!")

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or ":" not in context.args[0]:
        await update.message.reply_text("Usage: /settime HH:MM")
        return
    user_id = str(update.effective_user.id)
    data["subscriptions"].setdefault(user_id, {})["time"] = context.args[0]
    save_data()
    await update.message.reply_text(f"Daily word time set to {context.args[0]}.")

# Admin commands
async def addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("Not allowed")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addword <topic> <word>")
        return
    topic = context.args[0]
    word = " ".join(context.args[1:])
    data["topics"].setdefault(topic, []).append(word)
    save_data()
    await update.message.reply_text(f"Added word '{word}' to topic '{topic}'")

# Application
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("subscribe", subscribe))
app.add_handler(CommandHandler("settime", settime))
app.add_handler(CommandHandler("addword", addword))

# Job queue
job_queue: JobQueue = app.job_queue
job_queue.run_repeating(check_daily_words, interval=60, first=5)  # every minute

print("Daily Word Bot is running...")
app.run_polling()
