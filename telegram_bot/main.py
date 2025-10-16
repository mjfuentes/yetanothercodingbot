#!/usr/bin/env python3
"""
Telegram Bot for Claude Code Orchestrator
Phase 2: Persistent sessions with conversation history
"""

import asyncio
import logging
import os
import subprocess
from typing import Dict, Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from session import ClaudeCodeSession, SessionManager

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USERS", "").split(",") if uid]
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", os.getcwd())
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global session manager and Claude client
session_manager = SessionManager(timeout_minutes=SESSION_TIMEOUT_MINUTES)
claude_client = ClaudeCodeSession(CLAUDE_CLI_PATH, WORKSPACE_PATH, session_manager)


async def check_authorization(update: Update) -> bool:
    """Check if user is authorized"""
    user_id = update.effective_user.id

    if not ALLOWED_USERS or user_id not in ALLOWED_USERS:
        await update.message.reply_text(
            "⛔ Unauthorized. Please contact the bot owner."
        )
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        return False

    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not await check_authorization(update):
        return

    welcome_message = """
🤖 *Claude Code Orchestrator Bot*

I'm your AI assistant powered by Claude Code. I can:
- Answer questions
- Write and debug code
- Research technologies
- Plan and build projects
- Manage background tasks

*Commands:*
/start - Show this message
/help - Get help
/status - Check running tasks
/clear - Clear conversation

Just send me a message to get started!
    """

    await update.message.reply_text(welcome_message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    if not await check_authorization(update):
        return

    help_text = """
📚 *How to use me:*

*Simple queries:*
"What's 2+2?"
"Explain async/await in Python"

*Code generation:*
"Build a REST API for user management"
"Create a React component for a login form"

*Research & Planning:*
"Research best practices for WebSocket servers"
"Plan a microservices architecture"

*Commands:*
/status - Check background tasks
/clear - Reset conversation
/help - Show this message

💡 Tip: I can handle complex multi-step tasks in the background!
    """

    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    stats = session_manager.get_session_stats(user_id)

    if not stats['exists']:
        await update.message.reply_text("📊 No active session. Send a message to start!")
        return

    message = f"""📊 *Session Status*

💬 Messages: {stats['message_count']}
👤 User messages: {stats['user_messages']}
🤖 Assistant messages: {stats['assistant_messages']}
🕒 Created: {stats['created_at'][:19]}
⏱️ Last activity: {stats['last_activity'][:19]}

Use /clear to reset conversation.
    """

    await update.message.reply_text(message, parse_mode="Markdown")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Clear the session
    session_manager.clear_session(user_id)
    logger.info(f"Cleared session for user {user_id}")

    await update.message.reply_text(
        "🗑️ Conversation cleared! Starting fresh."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    message_text = update.message.text

    logger.info(f"User {user_id}: {message_text}")

    # Show typing indicator
    await update.message.chat.send_action("typing")

    # Send to Claude Code
    response = await claude_client.send_message(user_id, message_text)

    # Send response back to user
    # Telegram has a 4096 character limit, so split if needed
    if len(response) <= 4096:
        await update.message.reply_text(response)
    else:
        # Split into chunks
        chunks = [response[i:i+4096] for i in range(0, len(response), 4096)]
        for chunk in chunks:
            await update.message.reply_text(chunk)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages (Phase 5)"""
    if not await check_authorization(update):
        return

    await update.message.reply_text(
        "🎤 Voice message support coming in Phase 5!"
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

    if update and update.message:
        await update.message.reply_text(
            "❌ An error occurred. Please try again."
        )


async def cleanup_task(context: ContextTypes.DEFAULT_TYPE):
    """Periodic task to cleanup stale sessions"""
    count = session_manager.cleanup_stale_sessions()
    if count > 0:
        logger.info(f"Cleanup task: removed {count} stale sessions")


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment!")
        return

    if not ALLOWED_USERS:
        logger.warning("No ALLOWED_USERS set - bot is open to everyone!")

    logger.info("Starting Telegram bot...")

    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("clear", clear_command))

    # Handle messages
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(
        MessageHandler(filters.VOICE, handle_voice)
    )

    # Error handler
    application.add_error_handler(error_handler)

    # Schedule cleanup task (every 30 minutes)
    job_queue = application.job_queue
    job_queue.run_repeating(cleanup_task, interval=1800, first=1800)
    logger.info("Scheduled cleanup task (every 30 minutes)")

    # Start bot
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
