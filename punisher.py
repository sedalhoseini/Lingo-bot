from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackContext, CommandHandler
import time
import unicodedata

# ==================== PERSONALIZE THESE ====================
import os
BOT_TOKEN = os.getenv("BOT_TOKEN") # <--- Replace with your bot token

FILTER_WORDS = [
    # ======= English =======
    "spam", "advertisement", "ad", "promo", "buy now", "free", "click here",
    "subscribe", "follow me", "visit", "discount", "offer", "sale", "cheap",
    "link", "giveaway", "lottery", "win", "winner", "prize", "bitcoin", "crypto",
    "scam", "fraud", "hack", "cheat", "porn", "sex", "xxx", "nude", "adult",
    "erotic", "gamble", "casino", "loan", "credit card", "debt", "work from home",
    "earn money", "money back", "investment", "rich", "money", "fast cash",
    "online earning", "free gift", "clickbait", "viral", "tiktok", "instagram",
    "followers", "likes", "subscribe now", "join now", "limited offer", "urgent",
    "sale now", "hot deal", "win big", "prize money", "gift card", "free trial",
    "claim prize", "get rich", "make money", "shortcut", "secret", "exclusive",
    "password", "account", "login", "earnings", "crypto scam", "investment scam",
    "fake", "fraudulent", "hacked", "hack account", "illegal", "torrent", "warez",
    "keygen", "crack", "cheating", "exploit", "malware", "virus", "phishing",
    "nsfw", "18+", "erotic content", "sex content", "gambling", "casino online",
    "adult site", "dating site", "escort", "prostitute", "hookup", "drug", "cocaine",
    "marijuana", "heroin", "illegal drug", "alcohol", "gamble online", "pornography",
    
    # ======= Persian / Farsi =======
    "اسپم", "تبلیغ", "خرید", "رایگان", "کلیک کنید", "هدیه", "برنده", "جایزه",
    "فالو", "دنبال کردن", "لینک", "فروش", "ارزان", "تخفیف", "آفر", "بیت کوین",
    "کریپتو", "کلاهبرداری", "هک", "تقلب", "پورن", "سکس", "عکس نیمه برهنه", "xxx",
    "محتوای بزرگسال", "عکسی نامناسب", "قمار", "کازینو", "وام", "کارت اعتباری",
    "بدهی", "کار در خانه", "کسب درآمد", "پول رایگان", "سرمایه گذاری", "ثروتمند",
    "پول", "نقد سریع", "کسب آنلاین", "هدیه رایگان", "ویروسی", "اینستاگرام", "فالوور",
    "لایک", "همین حالا عضو شو", "پیشنهاد محدود", "فوری", "فروش ویژه", "جایزه بزرگ",
    "کارت هدیه", "تجربه رایگان", "دریافت جایزه", "ثروتمند شدن", "پول درآوردن", 
    "راز", "انحصاری", "رمز عبور", "حساب کاربری", "ورود", "کسب درآمد آنلاین", 
    "اسکم کریپتو", "سرمایه گذاری جعلی", "فیک", "هک شده", "غیرقانونی", "تورنت", 
    "کراک", "کیجن", "بد افزار", "ویروس", "فیشینگ", "محتوای غیر اخلاقی", "18+", 
    "محتوای سکسی", "محتوای بزرگسالان", "کازینو آنلاین", "دیتینگ", "آسانسور", 
    "مواد مخدر", "کوکائین", "ماریجوانا", "هروئین", "مواد غیرقانونی", "الکل"
]

ADMIN_USER_ID = 527164608
MAX_MESSAGES_PER_MINUTE = 5
WARNING_LIMIT = 3
LOG_CHANNEL_ID = -1003672042124
WHITELIST_IDS = [527164608]
# ============================================================

# In-memory storage
user_message_times = {}  # {user_id: [timestamps]}
user_warnings = {}       # {user_id: warning_count}
muted_users = {}         # {user_id: unmute_timestamp}

# ====== FUNCTIONS ======
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user_id = msg.from_user.id
    if user_id in WHITELIST_IDS:
        return

    # Delete system messages
    if msg.new_chat_members or msg.left_chat_member:
        await msg.delete()
        if msg.new_chat_members:
            for member in msg.new_chat_members:
                await log_action(f"New member joined: {member.full_name} ({member.id})", context)
        return

    # Spam/profanity filter
    if msg.text:
        text_normalized = unicodedata.normalize("NFC", msg.text.lower())
        for word in FILTER_WORDS:
            if word.lower() in text_normalized:
                await msg.delete()
                await log_action(f"Deleted message from {msg.from_user.full_name} (ID: {user_id}): '{msg.text}'", context)
                await warn_user(msg, context)
                return

    # Flood control
    timestamps = user_message_times.get(user_id, [])
    current_time = time.time()
    timestamps = [t for t in timestamps if current_time - t < 60]
    timestamps.append(current_time)
    user_message_times[user_id] = timestamps

    if len(timestamps) > MAX_MESSAGES_PER_MINUTE:
        await msg.delete()
        await log_action(f"User {msg.from_user.full_name} (ID: {user_id}) spamming messages", context)
        await warn_user(msg, context)

async def warn_user(msg, context: ContextTypes.DEFAULT_TYPE):
    user_id = msg.from_user.id
    warnings = user_warnings.get(user_id, 0) + 1
    user_warnings[user_id] = warnings

    if warnings < WARNING_LIMIT:
        await msg.reply_text(f"{msg.from_user.first_name}, this is warning {warnings}/{WARNING_LIMIT}. Please follow the rules!")
    else:
        # Auto-mute
        unmute_time = int(time.time()) + 600  # 10 minutes
        muted_users[user_id] = unmute_time
        try:
            await msg.chat.restrict_member(
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=unmute_time
            )
            await msg.reply_text(f"{msg.from_user.first_name} has been muted for repeated violations.")
            await log_action(f"User {msg.from_user.full_name} (ID: {user_id}) muted for repeated violations.", context)
            user_warnings[user_id] = 0
        except Exception as e:
            await log_action(f"Failed to mute user {msg.from_user.full_name} (ID: {user_id}): {e}", context)

async def log_action(text, context: ContextTypes.DEFAULT_TYPE):
    try:
        if LOG_CHANNEL_ID:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=text)
    except Exception as e:
        print(f"Logging failed: {e}")

# ====== NEW COMMANDS ======
async def list_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_warnings:
        await update.message.reply_text("No warnings yet.")
        return
    text = "Users with warnings:\n"
    for uid, count in user_warnings.items():
        text += f"ID: {uid} | Warnings: {count}\n"
    await update.message.reply_text(text)

async def list_muted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not muted_users:
        await update.message.reply_text("No users are currently muted.")
        return
    text = "Muted users:\n"
    for uid, unmute_time in muted_users.items():
        text += f"ID: {uid} | Unmute at: {time.ctime(unmute_time)}\n"
    await update.message.reply_text(text)

# ====== BUILD BOT ======
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL, handle_messages))
app.add_handler(CommandHandler("warnings", list_warnings))
app.add_handler(CommandHandler("muted", list_muted))

print("Punisher bot is running...")
app.run_polling()
