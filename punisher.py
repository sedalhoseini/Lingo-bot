from telegram import Update, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ChatMemberHandler,
)
import re, time, os, unicodedata, json
from datetime import datetime, timedelta, time as dtime
import pytz

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = {527164608}

LOG_CHANNEL_ID = -1003672042124
MESSAGES_CHANNEL_ID = -1003299270448
SUBS_FILE = "subscriptions.json"

# Spam patterns
FILTER_PATTERNS = re.compile(
    r"(spam|advertisement|ad|promo|buy\s*now|free|click\s*here|https?://)", re.IGNORECASE
)

TEHRAN = pytz.timezone("Asia/Tehran")
last_user_messages = {}  # {user_id: (text, timestamp)}

# ===== HELPERS =====
def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_USER_IDS:
            if update.message:
                await update.message.reply_text("You are not allowed to use this command.")
            elif update.callback_query:
                await update.callback_query.answer("Not allowed", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def user_link(user):
    return f'<a href="tg://user?id={user.id}">{user.full_name or "User"}</a>'

def get_user_mention(user):
    return f"@{user.username}" if user.username else user_link(user)

def load_subscriptions():
    if os.path.exists(SUBS_FILE):
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_subscriptions(data):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def log_action(text, context, channel_id=LOG_CHANNEL_ID):
    try:
        await context.bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"Logging failed: {e}")

# ===== MEDIA FORWARDING =====
async def forward_media(msg, channel_id, context):
    try:
        user_mention = f"@{msg.from_user.username}" if msg.from_user.username else f'<a href="tg://user?id={msg.from_user.id}">{msg.from_user.full_name}</a>'
        caption = f"{user_mention}: {msg.caption}" if getattr(msg, "caption", None) else user_mention

        if msg.photo:
            file_id = msg.photo[-1].file_id
            await context.bot.send_photo(chat_id=channel_id, photo=file_id, caption=caption, parse_mode="HTML")
            return
        if msg.video:
            await context.bot.send_video(chat_id=channel_id, video=msg.video.file_id, caption=caption, parse_mode="HTML")
            return
        if msg.animation:
            await context.bot.send_animation(chat_id=channel_id, animation=msg.animation.file_id, caption=caption, parse_mode="HTML")
            return
        if msg.document:
            await context.bot.send_document(chat_id=channel_id, document=msg.document.file_id, caption=caption, parse_mode="HTML")
            return
        if msg.audio:
            await context.bot.send_audio(chat_id=channel_id, audio=msg.audio.file_id, caption=caption, parse_mode="HTML")
            return
        if msg.voice:
            await context.bot.send_voice(chat_id=channel_id, voice=msg.voice.file_id, caption=caption, parse_mode="HTML")
            return
        if msg.sticker:
            await context.bot.send_sticker(chat_id=channel_id, sticker=msg.sticker.file_id)
            await context.bot.send_message(chat_id=channel_id, text=user_mention, parse_mode="HTML")
            return
    except Exception as e:
        print(f"Media forwarding failed: {e}")

# ===== HANDLE MESSAGES =====
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return

    # ----- PRIVATE MESSAGE FORWARDING -----
    if msg.chat.type == "private":
        if msg.text and not msg.text.startswith("/"):
            user_mention = f"@{msg.from_user.username}" if msg.from_user.username else f'<a href="tg://user?id={msg.from_user.id}">{msg.from_user.full_name}</a>'
            await context.bot.send_message(
                chat_id=MESSAGES_CHANNEL_ID,
                text=f"{user_mention}: {msg.text}",
                parse_mode="HTML"
            )
        if msg.photo or msg.video or msg.animation or msg.document or msg.audio or msg.voice or msg.sticker:
            await forward_media(msg, MESSAGES_CHANNEL_ID, context)

    # ----- DELETE JOIN / LEAVE MESSAGES -----
    if msg.new_chat_members or msg.left_chat_member:
        try:
            await msg.delete()
        except:
            pass
        return

    # ----- ADVANCED SPAM FILTER -----
    if msg.chat.type in ("group", "supergroup"):
        normalized = unicodedata.normalize("NFC", msg.text or "")
        user_id = msg.from_user.id
        now = int(time.time())

        if FILTER_PATTERNS.search(normalized):
            try:
                await msg.delete()
            except:
                pass
            return

        last_msg, last_time = last_user_messages.get(user_id, ("", 0))
        if normalized == last_msg and now - last_time < 10:
            try:
                await msg.delete()
            except:
                pass
            return
        last_user_messages[user_id] = (normalized, now)

# ===== CHAT MEMBER HANDLER =====
async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm or cm.chat.type != "channel":
        return
    if cm.old_chat_member.status in ("left", "kicked") and cm.new_chat_member.status == "member":
        user = cm.new_chat_member.user
        await log_action(f"{user_link(user)}, Joined.", context)

# ===== COMMANDS =====
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("درود! به چنل خودتون خوش اومدید.")
    except:
        pass

async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("@SedAl_Hoseini")

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
    elif context.args:
        arg = context.args[0].lstrip("@")
        try:
            user = await context.bot.get_chat(arg)
        except:
            await msg.reply_text("User not found.")
            return
    else:
        user = msg.from_user
    username = f"@{user.username}" if user.username else "None"
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    text = (
        f"<b>Name:</b> {full_name}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>Bot:</b> {'Yes' if user.is_bot else 'No'}"
    )
    await msg.reply_text(text, parse_mode="HTML")

# ===== GROUP MODERATION =====
async def resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
    elif context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            arg = arg[1:]
        try:
            user = await context.bot.get_chat(arg)
        except:
            try:
                user_id = int(arg)
                user = await context.bot.get_chat(user_id)
            except:
                await msg.reply_text("Cannot find user.")
                return None
    else:
        await msg.reply_text("You must reply to a user or provide username/ID.")
        return None
    return user

@admin_only
async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return
    duration = 3600
    if len(context.args) > 1:
        try:
            duration = int(context.args[1])
        except:
            pass
    try:
        await context.bot.restrict_chat_member(
            chat_id=msg.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.utcnow() + timedelta(seconds=duration)
        )
        await msg.reply_text(f"{user_link(user)} muted for {duration} seconds.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to mute: {e}")

@admin_only
async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True
        )
        await context.bot.restrict_chat_member(chat_id=msg.chat_id, user_id=user.id, permissions=permissions)
        await msg.reply_text(f"{user_link(user)} has been unmuted.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to unmute: {e}")

@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = await resolve_user(update, context)
    if not user:
        return
    try:
        await context.bot.ban_chat_member(chat_id=msg.chat_id, user_id=user.id)
        await msg.reply_text(f"{user_link(user)} has been banned.", parse_mode="HTML")
    except Exception as e:
        await msg.reply_text(f"Failed to ban: {e}")

@admin_only
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not context.args:
        await msg.reply_text("Provide user ID to unban.")
        return
    try:
        user_id = int(context.args[0])
        await context.bot.unban_chat_member(chat_id=msg.chat_id, user_id=user_id)
        await msg.reply_text(f"User {user_id} has been unbanned.")
    except Exception as e:
        await msg.reply_text(f"Failed to unban: {e}")

# ===== DAILY WORD FEATURE =====
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_subscriptions()
    data.setdefault("users", {})
    data["users"][user_id] = data["users"].get(user_id, {"subscribed": True, "last_sent_index": -1, "last_sent_date": "", "send_time":"09:00","topic_mode":None})
    data["users"][user_id]["subscribed"] = True
    save_subscriptions(data)
    await update.message.reply_text("You are now subscribed to daily words!")

async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_subscriptions()
    if "users" in data and user_id in data["users"]:
        data["users"][user_id]["subscribed"] = False
        save_subscriptions(data)
    await update.message.reply_text("You have unsubscribed from daily words.")

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = get_next_word_for_user(update.effective_user.id)
    await update.message.reply_text(f"Today's word: {word}")

@admin_only
async def cmd_addwords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Provide topic name first.")
        return
    topic = context.args[0]
    lines = update.message.text.split("\n")[1:]
    data = load_subscriptions()
    data.setdefault("words", [])
    for line in lines:
        if "—" in line:
            word, meaning = map(str.strip, line.split("—", 1))
            data["words"].append({"word": word, "meaning": meaning, "topic": topic})
    save_subscriptions(data)
    await update.message.reply_text(f"Added {len(lines)} words to topic '{topic}'.")

async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.split(" ",1)[1] if " " in update.message.text else ""
    if re.match(r"^\d{1,2}:\d{2}$", msg):
        h, m = map(int, msg.split(":"))
        user_id = str(update.effective_user.id)
        data = load_subscriptions()
        data.setdefault("users", {})
        user_data = data["users"].get(user_id, {"subscribed": True, "last_sent_index": -1, "last_sent_date": ""})
        user_data["send_time"] = f"{h:02d}:{m:02d}"
        data["users"][user_id] = user_data
        save_subscriptions(data)
        await update.message.reply_text(f"Your daily word time is set to {h:02d}:{m:02d}.")
    else:
        await update.message.reply_text("Time format invalid. Use HH:MM (24-hour).")

async def cmd_topicmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Provide topic name or 'random'.")
        return
    topic = context.args[0].strip()
    user_id = str(update.effective_user.id)
    data = load_subscriptions()
    data.setdefault("users", {})
    user_data = data["users"].get(user_id, {"subscribed": True, "last_sent_index": -1, "last_sent_date": ""})
    user_data["topic_mode"] = topic if topic.lower() != "random" else None
    data["users"][user_id] = user_data
    save_subscriptions(data)
    await update.message.reply_text(f"Your daily words will be from topic: {topic}")

def get_next_word_for_user(user_id):
    user_id_str = str(user_id)
    data = load_subscriptions()
    user_data = data["users"].get(user_id_str, {"last_sent_index": -1, "last_sent_date": ""})
    topic = user_data.get("topic_mode")
    words_list = [w for w in data.get("words", []) if w["topic"] == topic] if topic else data.get("words", [])
    if not words_list:
        return "No words available for your selection."
    last_index = user_data.get("last_sent_index", -1)
    next_index = (last_index + 1) % len(words_list)
    user_data["last_sent_index"] = next_index
    user_data["last_sent_date"] = str(datetime.now(TEHRAN).date())
    data["users"][user_id_str] = user_data
    save_subscriptions(data)
    word_entry = words_list[next_index]
    return f"{word_entry['word']} — {word_entry['meaning']}"

async def send_daily_words(context):
    now = datetime.now(TEHRAN)
    data = load_subscriptions()
    for user_id, info in data.get("users", {}).items():
        if not info.get("subscribed"):
            continue
        send_time = info.get("send_time", "09:00")
        h, m = map(int, send_time.split(":"))
        if now.hour == h and now.minute == m:
            today = str(now.date())
            if info.get("last_sent_date") == today:
                continue
            word = get_next_word_for_user(user_id)
            try:
                await context.bot.send_message(chat_id=int(user_id), text=f"Today's word: {word}")
            except Exception as e:
                print(f"Failed to send daily word to {user_id}: {e}")

# ===== APPLICATION =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

# ---- CHAT MEMBER HANDLER ----
app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))

# ---- COMMAND HANDLERS ----
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("myid", cmd_myid))
app.add_handler(CommandHandler("userinfo", cmd_userinfo))
app.add_handler(CommandHandler("mute", cmd_mute))
app.add_handler(CommandHandler("unmute", cmd_unmute))
app.add_handler(CommandHandler("ban", cmd_ban))
app.add_handler(CommandHandler("unban", cmd_unban))

app.add_handler(CommandHandler("subscribe", cmd_subscribe))
app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
app.add_handler(CommandHandler("today", cmd_today))
app.add_handler(CommandHandler("addwords", cmd_addwords))
app.add_handler(CommandHandler("settime", cmd_settime))
app.add_handler(CommandHandler("topicmode", cmd_topicmode))

# ---- MESSAGE HANDLER ----
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

# ---- SCHEDULE DAILY WORD JOB ----
job_queue = app.job_queue
job_queue.run_repeating(send_daily_words, interval=60)

print("Punisher bot with full moderation and daily words is running...")
app.run_polling()
