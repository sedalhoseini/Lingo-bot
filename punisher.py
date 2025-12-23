from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

async def debug_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(f"Received your message: {update.message.text}")
    except Exception as e:
        await update.message.reply_text(f"Error in debug handler: {e}")

# Bot token must be a string
app = ApplicationBuilder().token("8537616205:AAHQLsfnbQa-PqxmgouwUWMl4eGKw3LvWKY").build()

# Catch-all handler for any text
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, debug_echo))

print("Debug bot running...")
app.run_polling()
