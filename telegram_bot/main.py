#!/usr/bin/env python3
"""
Telegram Bot for Claude Code Orchestrator
Phase 5: Voice message support with Whisper transcription
"""

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from session import ClaudeCodeSession, SessionManager
from tasks import TaskManager
from claude_interactive import ClaudeSessionPool
from orchestrator import invoke_orchestrator
from formatter import format_telegram_response

# Check if whisper is available
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logging.warning("Whisper not installed. Voice transcription will be limited.")

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USERS", "").split(",") if uid]
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", os.getcwd())
BOT_REPOSITORY = os.getenv("BOT_REPOSITORY", os.getcwd())
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

# Reduce HTTP/Telegram noise in logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Global managers
session_manager = SessionManager(timeout_minutes=SESSION_TIMEOUT_MINUTES)
claude_client = ClaudeCodeSession(CLAUDE_CLI_PATH, WORKSPACE_PATH, session_manager)
task_manager = TaskManager()
claude_pool = ClaudeSessionPool()  # No default workspace - uses task.workspace


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


def get_action_buttons() -> InlineKeyboardMarkup:
    """Create inline keyboard with quick action buttons"""
    keyboard = [
        [
            InlineKeyboardButton("🗑️ Clear Chat", callback_data="clear_conversation"),
            InlineKeyboardButton("📊 Status", callback_data="show_status"),
        ],
        [
            InlineKeyboardButton("📚 Help", callback_data="show_help"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    if not await check_authorization(update):
        return

    # Get recent changes
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-3"],
            cwd=BOT_REPOSITORY,
            capture_output=True,
            text=True,
            timeout=2
        )
        recent_changes = result.stdout.strip() if result.returncode == 0 else None
    except:
        recent_changes = None

    welcome_message = "👋 *Hey!*\n\n"

    if recent_changes:
        welcome_message += "*Recent updates:*\n"
        for line in recent_changes.split('\n')[:2]:  # Show last 2 commits
            # Format: hash message -> • message
            parts = line.split(' ', 1)
            if len(parts) == 2:
                welcome_message += f"• {parts[1]}\n"
        welcome_message += "\n"

    welcome_message += "Send me a message or /help to see what I can do!"

    await update.message.reply_text(
        welcome_message,
        parse_mode="Markdown",
        reply_markup=get_action_buttons()
    )


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

*Multi-repository:*
"in ~/myproject, create a new file"
"for repository /workspace/app, fix bug"
Or use: /cd /path/to/workspace

*Research & Planning:*
"Research best practices for WebSocket servers"
"Plan a microservices architecture"

*Commands:*
/status - Check background tasks
/clear - Reset conversation
/cd - Change workspace directory
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


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /restart command - gracefully restart the bot"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    logger.info(f"Restart requested by user {user_id}")

    # Send acknowledgment
    await update.message.reply_text(
        "🔄 Restarting bot... Back in a moment."
    )

    # Schedule restart after response is sent
    import signal
    import sys

    def restart_bot():
        """Restart the bot process"""
        python = sys.executable
        os.execl(python, python, *sys.argv)

    # Give time for message to send, then restart
    await asyncio.sleep(1)

    # Graceful shutdown then restart
    restart_bot()


async def cd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cd command to change workspace"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Get workspace path from command args
    if not context.args:
        # Show current workspace
        current = session_manager.get_workspace(user_id) or WORKSPACE_PATH
        await update.message.reply_text(
            f"📂 *Current workspace:*\n`{current}`\n\n"
            f"Usage: `/cd /path/to/workspace`",
            parse_mode="Markdown"
        )
        return

    workspace = " ".join(context.args)

    # Expand ~ to home directory
    workspace = os.path.expanduser(workspace)

    # Check if path exists
    if not os.path.exists(workspace):
        await update.message.reply_text(
            f"❌ Path does not exist: `{workspace}`\n\n"
            f"Please create it first or check the path.",
            parse_mode="Markdown"
        )
        return

    # Set workspace
    session_manager.set_workspace(user_id, workspace)

    await update.message.reply_text(
        f"✅ Workspace changed to:\n`{workspace}`\n\n"
        f"All code tasks will now run in this directory.",
        parse_mode="Markdown"
    )


def extract_workspace_from_message(message: str) -> tuple[Optional[str], str]:
    """
    Extract workspace path from message if specified
    Returns: (workspace_path, cleaned_message)

    Supports patterns like:
    - "in /path/to/repo, do X"
    - "in ~/projects/myapp do X"
    - "for repository /path/repo, do X"
    """
    import re

    # Pattern: "in <path>, <rest>" or "in <path> <rest>"
    pattern1 = r'^in\s+([~/\w\-/.]+)[,\s]+(.+)$'
    match = re.match(pattern1, message, re.IGNORECASE)
    if match:
        workspace = os.path.expanduser(match.group(1).strip())
        cleaned = match.group(2).strip()
        return workspace, cleaned

    # Pattern: "for repository <path>, <rest>"
    pattern2 = r'^for\s+(?:repository|repo|project)\s+([~/\w\-/.]+)[,\s]+(.+)$'
    match = re.match(pattern2, message, re.IGNORECASE)
    if match:
        workspace = os.path.expanduser(match.group(1).strip())
        cleaned = match.group(2).strip()
        return workspace, cleaned

    return None, message


def detect_task_type(message: str) -> str:
    """
    Detect if message requires code execution or just chat
    Returns: 'code_task', 'chat', 'status_query'
    """
    message_lower = message.lower()

    # Code task keywords
    code_keywords = [
        'modify', 'change', 'update', 'fix', 'refactor', 'add',
        'create', 'build', 'implement', 'write code', 'edit',
        'commit', 'git', 'file', 'repository', 'repo'
    ]

    # Status query keywords
    status_keywords = ['status', 'progress', 'tasks', 'running']

    # Check for status queries
    if any(kw in message_lower for kw in status_keywords):
        return 'status_query'

    # Check for code tasks
    if any(kw in message_lower for kw in code_keywords):
        return 'code_task'

    return 'chat'


async def execute_code_task(task: "Task", update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute a code task in the background with full tool access"""
    user_id = update.effective_user.id

    try:
        # Update task status
        task_manager.update_task(task.task_id, status="in_progress")
        logger.info(f"Starting task execution: {task.task_id} in {task.workspace}")

        # Execute using Claude session pool with bot context
        success, result, pid = await claude_pool.execute_task(
            task_id=task.task_id,
            description=task.description,
            workspace=Path(task.workspace),
            bot_repo_path=BOT_REPOSITORY,  # Always provide bot context
            model=task.model
        )

        # Store PID for task persistence
        if pid:
            task_manager.update_task(task.task_id, pid=pid)
            logger.info(f"Task {task.task_id} running with PID {pid}")

        # Update task with result
        if success:
            task_manager.update_task(
                task.task_id,
                status="completed",
                result=result
            )
            logger.info(f"Task {task.task_id} completed successfully")

            # Notify user
            notification = (
                f"✅ *Task Complete* (#{task.task_id})\n\n"
                f"📝 {task.description}\n\n"
                f"**Result:**\n{result}"
            )
        else:
            task_manager.update_task(
                task.task_id,
                status="failed",
                error=result
            )
            logger.error(f"Task {task.task_id} failed: {result}")

            # Notify user of failure
            notification = (
                f"❌ *Task Failed* (#{task.task_id})\n\n"
                f"📝 {task.description}\n\n"
                f"**Error:**\n{result}"
            )

        # Send notification (chunk if needed)
        if len(notification) <= 4096:
            await context.bot.send_message(
                chat_id=user_id,
                text=notification,
                parse_mode="Markdown"
            )
        else:
            # Send description + status first
            header = notification.split("**Result:**\n")[0] if success else notification.split("**Error:**\n")[0]
            await context.bot.send_message(chat_id=user_id, text=header, parse_mode="Markdown")

            # Send result/error in chunks
            content = result
            chunks = [content[i:i+4096] for i in range(0, len(content), 4096)]
            for chunk in chunks:
                await context.bot.send_message(chat_id=user_id, text=chunk)

    except Exception as e:
        logger.error(f"Task execution error for {task.task_id}: {e}")
        task_manager.update_task(
            task.task_id,
            status="failed",
            error=str(e)
        )

        # Notify user
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ *Task Failed* (#{task.task_id})\n\n"
                 f"An unexpected error occurred:\n{str(e)}",
            parse_mode="Markdown"
        )


async def show_task_status(user_id: int, update: Update):
    """Show user's task status"""
    # Get active tasks
    active_tasks = task_manager.get_active_tasks(user_id)

    # Get recent completed/failed tasks
    recent_tasks = task_manager.get_user_tasks(user_id, limit=5)
    completed = [t for t in recent_tasks if t.status == 'completed'][:3]
    failed = [t for t in recent_tasks if t.status == 'failed'][:3]

    # Build status message
    message_parts = ["📊 *Task Status*\n"]

    # Active tasks
    if active_tasks:
        message_parts.append(f"\n🔄 *Active Tasks* ({len(active_tasks)}):")
        for task in active_tasks:
            status_icon = "⏳" if task.status == "pending" else "⚙️"
            message_parts.append(
                f"{status_icon} `#{task.task_id}` - {task.description[:50]}..."
            )
    else:
        message_parts.append("\n✨ No active tasks")

    # Recent completed
    if completed:
        message_parts.append(f"\n\n✅ *Recent Completed* ({len(completed)}):")
        for task in completed:
            message_parts.append(
                f"• `#{task.task_id}` - {task.description[:40]}..."
            )

    # Recent failed
    if failed:
        message_parts.append(f"\n\n❌ *Recent Failed* ({len(failed)}):")
        for task in failed:
            message_parts.append(
                f"• `#{task.task_id}` - {task.description[:40]}..."
            )

    message_parts.append("\n\n💡 Use task ID to see details")

    await update.message.reply_text(
        "\n".join(message_parts),
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages using orchestrator"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    message_text = update.message.text

    logger.info(f"User {user_id} (text): {message_text}")

    # Send immediate acknowledgment
    status_msg = await update.message.reply_text("⏳ Working on it...")

    # Show typing indicator continuously in background
    async def keep_typing():
        try:
            while True:
                await update.message.chat.send_action("typing")
                await asyncio.sleep(4)  # Typing indicator lasts ~5s
        except:
            pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        # Get conversation history
        session = session_manager.get_session(user_id)
        history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

        # Invoke orchestrator with text input
        response = await invoke_orchestrator(
        user_query=message_text,
        input_method="text",
        conversation_history=history,
        current_workspace=session_manager.get_workspace(user_id),
        bot_repository=BOT_REPOSITORY,
        workspace_path=WORKSPACE_PATH,
        task_manager=task_manager
    )

        if not response:
            # Fallback to direct Claude response
            logger.warning("Orchestrator failed, using fallback")
            response = await claude_client.send_message(user_id, message_text)

        # Check if response is a BACKGROUND_TASK request
        if response and response.startswith("BACKGROUND_TASK|"):
            parts = response.split("|", 2)
            if len(parts) == 3:
                _, task_desc, user_message = parts

                # Create background task
                workspace = session_manager.get_workspace(user_id) or WORKSPACE_PATH
                task = task_manager.create_task(
                    user_id=user_id,
                    description=task_desc,
                    workspace=workspace,
                    model="sonnet"
                )

                # Execute task in background
                asyncio.create_task(execute_code_task(task, update, context))

                # Send user-facing message
                response = f"🚀 **Background Task Started** (#{task.task_id})\n\n{user_message}\n\nI'll notify you when it's complete!"

        # Add to conversation history
        session_manager.add_message(user_id, "user", message_text)
        session_manager.add_message(user_id, "assistant", response)

        # Delete status message
        await status_msg.delete()

        # Format and send response to user
        formatted_chunks = format_telegram_response(
            response,
            workspace_path=session_manager.get_workspace(user_id)
        )

        for chunk in formatted_chunks:
            await update.message.reply_text(chunk, parse_mode="HTML")

    finally:
        # Stop typing indicator
        typing_task.cancel()


def transcribe_audio(file_path: str) -> Optional[str]:
    """Transcribe audio file using Whisper (sync function)"""
    if not WHISPER_AVAILABLE:
        return None

    try:
        # Load model (tiny for speed, can upgrade to base/small/medium)
        model = whisper.load_model("tiny")

        # Transcribe
        result = model.transcribe(file_path)
        return result["text"].strip()
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return None


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages with Whisper transcription"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    voice_message = update.message.voice

    logger.info(f"User {user_id} sent voice message (duration: {voice_message.duration}s)")

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        # Download voice file
        voice_file = await context.bot.get_file(voice_message.file_id)

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        # Download to temp file
        await voice_file.download_to_drive(tmp_path)
        logger.info(f"Downloaded voice file to {tmp_path}")

        # Transcribe (run in thread to avoid blocking)
        loop = asyncio.get_event_loop()
        transcription = await loop.run_in_executor(None, transcribe_audio, tmp_path)

        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)

        if not transcription:
            await update.message.reply_text(
                "❌ Transcription failed. Please try again or send text."
            )
            return

        logger.info(f"User {user_id} (voice): {transcription}")

        # Send immediate acknowledgment
        status_msg = await update.message.reply_text("⏳ Processing voice message...")

        # Show typing indicator continuously in background
        async def keep_typing():
            try:
                while True:
                    await update.message.chat.send_action("typing")
                    await asyncio.sleep(4)
            except:
                pass

        typing_task = asyncio.create_task(keep_typing())

        try:
            # Get conversation history
            session = session_manager.get_session(user_id)
            history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

            # Invoke orchestrator with VOICE input (be permissive with transcription errors)
            response = await invoke_orchestrator(
            user_query=transcription,
            input_method="voice",  # Important: tells orchestrator to be permissive
            conversation_history=history,
            current_workspace=session_manager.get_workspace(user_id),
            bot_repository=BOT_REPOSITORY,
            workspace_path=WORKSPACE_PATH,
            task_manager=task_manager
        )

            if not response:
                # Fallback to direct Claude response
                logger.warning("Orchestrator failed, using fallback")
                response = await claude_client.send_message(user_id, transcription)

            # Check if response is a BACKGROUND_TASK request
            if response and response.startswith("BACKGROUND_TASK|"):
                parts = response.split("|", 2)
                if len(parts) == 3:
                    _, task_desc, user_message = parts

                    # Create background task
                    workspace = session_manager.get_workspace(user_id) or WORKSPACE_PATH
                    task = task_manager.create_task(
                        user_id=user_id,
                        description=task_desc,
                        workspace=workspace,
                        model="sonnet"
                    )

                    # Execute task in background
                    asyncio.create_task(execute_code_task(task, update, context))

                    # Send user-facing message
                    response = f"🚀 **Background Task Started** (#{task.task_id})\n\n{user_message}\n\nI'll notify you when it's complete!"

            # Add to conversation history
            session_manager.add_message(user_id, "user", transcription)
            session_manager.add_message(user_id, "assistant", response)

            # Delete status message
            await status_msg.delete()

            # Format and send response to user (without showing transcription)
            formatted_chunks = format_telegram_response(
                response,
                workspace_path=session_manager.get_workspace(user_id)
            )

            for chunk in formatted_chunks:
                await update.message.reply_text(chunk, parse_mode="HTML")

        finally:
            # Stop typing indicator
            typing_task.cancel()

    except Exception as e:
        logger.error(f"Voice message handling error: {e}")
        await update.message.reply_text(
            "❌ Error processing voice message. Please try again."
        )


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks from inline keyboard"""
    query = update.callback_query
    user_id = query.from_user.id

    # Answer callback to stop loading animation
    await query.answer()

    # Check authorization
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await query.edit_message_text("⛔ Unauthorized. Please contact the bot owner.")
        return

    callback_data = query.data

    # Handle different button actions
    if callback_data == "clear_conversation":
        # Clear the session
        session_manager.clear_session(user_id)
        logger.info(f"Cleared session for user {user_id} via button")

        await query.edit_message_text(
            "🗑️ Conversation cleared! Starting fresh.\n\nSend me a message to begin.",
            reply_markup=get_action_buttons()
        )

    elif callback_data == "show_status":
        # Get session stats
        stats = session_manager.get_session_stats(user_id)

        if not stats['exists']:
            await query.edit_message_text(
                "📊 No active session. Send a message to start!",
                reply_markup=get_action_buttons()
            )
            return

        message = f"""📊 *Session Status*

💬 Messages: {stats['message_count']}
👤 User messages: {stats['user_messages']}
🤖 Assistant messages: {stats['assistant_messages']}
🕒 Created: {stats['created_at'][:19]}
⏱️ Last activity: {stats['last_activity'][:19]}
        """

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=get_action_buttons()
        )

    elif callback_data == "show_help":
        help_text = """
📚 *How to use me:*

*Simple queries:*
"What's 2+2?"
"Explain async/await in Python"

*Code generation:*
"Build a REST API for user management"
"Create a React component for a login form"

*Multi-repository:*
"in ~/myproject, create a new file"
"for repository /workspace/app, fix bug"
Or use: /cd /path/to/workspace

*Research & Planning:*
"Research best practices for WebSocket servers"
"Plan a microservices architecture"

*Commands:*
/status - Check background tasks
/clear - Reset conversation
/cd - Change workspace directory
/help - Show this message

💡 Tip: I can handle complex multi-step tasks in the background!
        """

        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=get_action_buttons()
        )

    elif callback_data == "show_start":
        # Get recent changes
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-3"],
                cwd=BOT_REPOSITORY,
                capture_output=True,
                text=True,
                timeout=2
            )
            recent_changes = result.stdout.strip() if result.returncode == 0 else None
        except:
            recent_changes = None

        welcome_message = "👋 *Hey!*\n\n"

        if recent_changes:
            welcome_message += "*Recent updates:*\n"
            for line in recent_changes.split('\n')[:2]:
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    welcome_message += f"• {parts[1]}\n"
            welcome_message += "\n"

        welcome_message += "Send me a message or /help to see what I can do!"

        await query.edit_message_text(
            welcome_message,
            parse_mode="Markdown",
            reply_markup=get_action_buttons()
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

    # Set bot commands (updates Telegram menu)
    async def post_init(app: Application):
        await app.bot.set_my_commands([
            BotCommand("start", "Show welcome message"),
            BotCommand("help", "Get help"),
            BotCommand("status", "Check running tasks"),
            BotCommand("clear", "Clear conversation"),
            BotCommand("restart", "Restart the bot"),
            BotCommand("cd", "Change workspace directory"),
        ])

    application.post_init = post_init

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("cd", cd_command))

    # Handle button callbacks
    application.add_handler(CallbackQueryHandler(button_callback_handler))

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
