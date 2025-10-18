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
from formatter import format_telegram_response
from pathlib import Path

from claude_api import ask_claude
from claude_interactive import ClaudeSessionPool
from cost_tracker import CostTracker
from dotenv import load_dotenv
from git_tracker import get_git_tracker
from log_claude_escalation import LogClaudeEscalation, UserConfirmationManager
from log_monitor import LogMonitorManager, MonitoringConfig
from message_queue import MessageQueueManager
from orchestrator import discover_repositories
from rate_limiter import RateLimiter
from session import ClaudeCodeSession, SessionManager
from tasks import Task, TaskManager
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from tool_usage_tracker import ToolUsageTracker
from worker_pool import WorkerPool

# Check if whisper is available
try:
    import whisper

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = [int(uid) for uid in os.getenv("ALLOWED_USERS", "").split(",") if uid]
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
WORKSPACE_PATH = os.getenv("WORKSPACE_PATH", os.getcwd())
BOT_REPOSITORY = os.getenv("BOT_REPOSITORY", os.getcwd())

# Setup logging (BEFORE any log calls to avoid duplicate handlers)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        # NOTE: No StreamHandler when running under launchd - it captures stdout/stderr automatically
        # to avoid duplicate log entries
    ],
    force=True,  # Replace any existing handlers
)
logger = logging.getLogger(__name__)

# Reduce HTTP/Telegram noise in logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Log whisper availability after logging is configured
if not WHISPER_AVAILABLE:
    logger.warning("Whisper not installed. Voice transcription will be limited.")

# Global managers
session_manager = SessionManager()
claude_client = ClaudeCodeSession(CLAUDE_CLI_PATH, WORKSPACE_PATH, session_manager)
task_manager = TaskManager()
tool_usage_tracker = ToolUsageTracker()  # Track tool usage and agent status
claude_pool = ClaudeSessionPool(usage_tracker=tool_usage_tracker)  # No default workspace - uses task.workspace
cost_tracker = CostTracker()  # Track API costs
rate_limiter = RateLimiter()  # Rate limiting
queue_manager = MessageQueueManager()  # Message queue per user
worker_pool = WorkerPool(max_workers=3)  # Bounded worker pool for background tasks

# Log monitoring system
log_monitor_config = MonitoringConfig(
    log_path="logs/bot.log",
    check_interval_seconds=300,  # Check every 5 minutes
    analysis_window_hours=1,  # Analyze last hour
    notify_on_critical=True,
    notify_on_warning=False,  # Only notify on critical initially
    max_notifications_per_check=3,
)
log_monitor_manager = LogMonitorManager(log_monitor_config)
log_escalation = LogClaudeEscalation(BOT_REPOSITORY)
user_confirmations = UserConfirmationManager()


# Register tool usage tracking hooks
def log_tool_start(task_id: str, tool_name: str, parameters: dict):
    """Hook: Log when a tool starts"""
    logger.debug(f"Tool started: {task_id} - {tool_name}")


def log_tool_complete(task_id: str, tool_name: str, duration_ms: float, success: bool, error: str | None):
    """Hook: Log when a tool completes"""
    status = "success" if success else "failed"
    logger.info(f"Tool completed: {task_id} - {tool_name} ({duration_ms:.2f}ms, {status})")


def log_status_change(task_id: str, status: str, message: str | None):
    """Hook: Log agent status changes"""
    logger.info(f"Agent status: {task_id} - {status} {f'({message})' if message else ''}")


# Register hooks with tracker
tool_usage_tracker.register_tool_start_hook(log_tool_start)
tool_usage_tracker.register_tool_complete_hook(log_tool_complete)
tool_usage_tracker.register_status_change_hook(log_status_change)


async def send_formatted_response(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, response: str, workspace_path: str | None = None
):
    """
    Send a formatted response to the user, either as text chunks or as a document attachment
    if the response is too long.

    Args:
        context: Telegram context
        user_id: User ID to send to
        response: Raw response text
        workspace_path: Optional workspace path for context
    """
    formatted_result = format_telegram_response(response, workspace_path=workspace_path)

    # Check if result is a tuple (document mode) or list (normal chunks)
    if isinstance(formatted_result, tuple):
        # Document mode: send summary + attached file
        summary, document_path = formatted_result
        await context.bot.send_message(chat_id=user_id, text=summary, parse_mode="HTML")

        # Send the markdown document
        try:
            with open(document_path, "rb") as doc:
                await context.bot.send_document(chat_id=user_id, document=doc, filename="response.md")
        finally:
            # Clean up temporary file
            Path(document_path).unlink(missing_ok=True)
    else:
        # Normal mode: send chunks
        for chunk in formatted_result:
            await context.bot.send_message(chat_id=user_id, text=chunk, parse_mode="HTML")


# Async wrapper functions for delegating writes to worker pool
async def _async_add_session_message(user_id: int, role: str, content: str):
    """Async wrapper for session write - queued to worker pool"""
    session_manager.add_message(user_id, role, content)
    logger.debug(f"Queued session write: user {user_id}, role {role}")


async def _async_record_usage(user_id: int, model: str, input_tokens: int, output_tokens: int, request_type: str):
    """Async wrapper for cost tracking write - queued to worker pool"""
    cost_tracker.record_usage(
        user_id=user_id, model=model, input_tokens=input_tokens, output_tokens=output_tokens, request_type=request_type
    )
    logger.debug(f"Queued cost tracking: user {user_id}, model {model}")


async def check_authorization(update: Update) -> bool:
    """Check if user is authorized"""
    user_id = update.effective_user.id

    if not ALLOWED_USERS or user_id not in ALLOWED_USERS:
        await update.message.reply_text("Unauthorized. Please contact the bot owner.")
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        return False

    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - priority command that executes immediately"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Clear conversation history on /start (executes immediately, bypassing queue)
    session_manager.clear_session(user_id)
    cost_tracker.reset_session(user_id)  # Reset session cost tracking
    logger.info(f"Priority /start: Cleared session for user {user_id}")

    # Get recent changes
    try:
        result = subprocess.run(["git", "log", "--oneline", "-3"], cwd=BOT_REPOSITORY, capture_output=True, text=True)
        recent_changes = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        recent_changes = None

    welcome_message = "<b>Started fresh</b>\n\n"

    if recent_changes:
        welcome_message += "<b>Recent updates:</b>\n"
        for line in recent_changes.split("\n")[:2]:  # Show last 2 commits
            # Format: hash message -> • message
            parts = line.split(" ", 1)
            if len(parts) == 2:
                welcome_message += f"• {parts[1]}\n"
        welcome_message += "\n"

    welcome_message += "Send me a message to get started!"

    await update.message.reply_text(welcome_message, parse_mode="HTML")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show active tasks and errors in compact format"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Clean up stale pending tasks (older than 1 hour) to prevent clutter
    task_manager.cleanup_stale_pending_tasks(max_age_hours=1)

    # Clean up old failed tasks (older than 24 hours) to prevent clutter
    task_manager.clear_old_failed_tasks(user_id, older_than_hours=24)

    # Get active tasks only
    active_tasks = task_manager.get_active_tasks(user_id)

    # Get recent failed tasks (last 1 hour only, exclude repetitive failures)
    from datetime import datetime, timedelta

    recent_tasks = task_manager.get_user_tasks(user_id, limit=50)
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)

    failed_tasks = []
    seen_errors = set()
    for task in recent_tasks:
        if task.status != "failed":
            continue

        # Only show failures from last hour
        try:
            task_time = datetime.fromisoformat(task.created_at)
            if task_time < one_hour_ago:
                continue
        except ValueError:
            # Skip tasks with invalid timestamp format
            continue

        # Skip repetitive "Find todos" failures
        if "Find todos" in task.description:
            continue

        # Skip if we've seen this exact error before
        error_key = (task.description[:50], task.error[:100] if task.error else "")
        if error_key in seen_errors:
            continue

        seen_errors.add(error_key)
        failed_tasks.append(task)

        if len(failed_tasks) >= 3:
            break

    # Build compact status message (plain text - formatter will convert to HTML)
    message_parts = ["Status\n"]

    # Active Tasks - only show if there are any
    if active_tasks:
        message_parts.append(f"Active Tasks ({len(active_tasks)})")
        for task in active_tasks[:5]:  # Show up to 5 active tasks
            status_icon = "🔄" if task.status == "pending" else "▶️"
            message_parts.append(f"{status_icon} #{task.task_id} {task.description[:50]}")

            # Show latest activity if available
            latest_activity = task.get_latest_activity(limit=1)
            if latest_activity:
                activity = latest_activity[0]
                # Parse timestamp to show relative time
                from datetime import datetime

                try:
                    activity_time = datetime.fromisoformat(activity["timestamp"])
                    now = datetime.now()
                    elapsed = (now - activity_time).total_seconds()

                    if elapsed < 60:
                        time_str = f"{int(elapsed)}s ago"
                    elif elapsed < 3600:
                        time_str = f"{int(elapsed / 60)}m ago"
                    else:
                        time_str = f"{int(elapsed / 3600)}h ago"

                    message_parts.append(f"   └─ {activity['message'][:60]} ({time_str})")
                except Exception:
                    message_parts.append(f"   └─ {activity['message'][:60]}")

        message_parts.append("")

    # Failed tasks - only show if there are any
    if failed_tasks:
        message_parts.append(f"\nRecent Errors ({len(failed_tasks)})")
        for task in failed_tasks:
            error_preview = task.error[:60] if task.error else "Unknown error"
            message_parts.append(f"❌ #{task.task_id} {error_preview}")

    # If nothing to show
    if not active_tasks and not failed_tasks:
        message_parts.append("\n✓ No active tasks or errors")

    # Format and send using HTML formatter (handles entities properly)
    message = "\n".join(message_parts)
    await send_formatted_response(context, user_id, message)


async def usage_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /usage command - show detailed API usage and costs"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Get cost stats
    cost_stats = cost_tracker.get_usage_stats(user_id)

    # Get rate limit stats
    rate_stats = rate_limiter.get_user_stats(user_id)

    # Build detailed message (plain text - formatter will convert to HTML)
    message = f"""API Usage & Costs

Total Usage
• Total requests: {cost_stats['total_requests']}
• Total cost: ${cost_stats['total_cost']:.4f}
• Recent (24h): {cost_stats['recent_24h']} requests

Current Session"""

    # Add session info if available
    if cost_stats.get("session_cost", 0) > 0:
        message += f"\n• Session ({cost_stats.get('session_duration', '0m')}): ${cost_stats['session_cost']:.4f}"
    else:
        message += "\n• No session started yet"

    message += f"""

Current Period
• Weekly: ${cost_stats.get('weekly_cost', 0):.4f}
• Daily: ${cost_stats['daily_cost']:.4f} / ${cost_stats['daily_limit']:.2f} ({cost_stats['daily_percentage']:.1f}%)
• Monthly: ${cost_stats['monthly_cost']:.4f} / ${cost_stats['monthly_limit']:.2f} ({cost_stats['monthly_percentage']:.1f}%)

Rate Limits
• Last minute: {rate_stats['requests_last_minute']} / {rate_stats['limit_per_minute']} ({rate_stats['minute_percentage']:.0f}%)
• Last hour: {rate_stats['requests_last_hour']} / {rate_stats['limit_per_hour']} ({rate_stats['hour_percentage']:.0f}%)"""

    if rate_stats["in_cooldown"]:
        message += f"\n• Cooldown: {rate_stats['cooldown_remaining']}s remaining"

    # Add model breakdown if available with enhanced display
    if cost_stats["model_breakdown"]:
        message += "\n\nBy Model"
        # Sort by cost (descending) for better visibility
        sorted_models = sorted(cost_stats["model_breakdown"].items(), key=lambda x: x[1]["cost"], reverse=True)

        for model, stats in sorted_models:
            # Calculate token totals
            total_tokens = stats["input_tokens"] + stats["output_tokens"]
            avg_tokens_per_req = total_tokens / stats["requests"] if stats["requests"] > 0 else 0

            # Format model name for display
            model_display = model.capitalize()

            message += f"\n• {model_display}: {stats['requests']} requests, ${stats['cost']:.4f}"
            message += (
                f"\n  └─ Tokens: {stats['input_tokens']:,} in + {stats['output_tokens']:,} out = {total_tokens:,} total"
            )
            message += f"\n  └─ Avg per request: {avg_tokens_per_req:,.0f} tokens"

    # Add pricing info footer
    message += f"""

Pricing Info
• Haiku 4.5: $0.80/1M input, $4.00/1M output
• Sonnet 4.5: $3.00/1M input, $15.00/1M output

Last reset: {cost_stats['last_reset'][:19]}"""

    # Format and send using HTML formatter
    await send_formatted_response(context, user_id, message)


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /retry command - retry failed tasks"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Check if task ID was provided
    if context.args and len(context.args) > 0:
        # Retry specific task
        task_id = context.args[0].lstrip("#")  # Remove # if present

        # Check if task exists and belongs to user
        task = task_manager.get_task(task_id)
        if not task:
            message = f"Task #{task_id} not found."
            await send_formatted_response(context, user_id, message)
            return

        if task.user_id != user_id:
            await update.message.reply_text("You don't have permission to retry this task.")
            return

        if task.status != "failed":
            message = f"Task #{task_id} is not failed (status: {task.status})."
            await send_formatted_response(context, user_id, message)
            return

        # Retry the task
        new_task = task_manager.retry_task(task_id)
        if new_task:
            # Submit task to worker pool
            await worker_pool.submit(execute_code_task, new_task, update, context)

            message = f"Task Retry Started #{new_task.task_id}\n\n"
            message += f"Retrying: {task.description}\n"
            message += f"Original: #{task_id}\n"
            message += f"Previous error: {task.error[:80] if task.error else 'Unknown'}"

            await send_formatted_response(context, user_id, message)
        else:
            await update.message.reply_text("Failed to retry task. Please try again.")

    else:
        # Show list of failed tasks
        failed_tasks = task_manager.get_failed_tasks(user_id, limit=10)

        if not failed_tasks:
            await update.message.reply_text("No failed tasks to retry! 🎉")
            return

        message = "Failed Tasks\n\n"
        message += f"Found {len(failed_tasks)} failed task(s):\n\n"

        for task in failed_tasks[:5]:  # Show up to 5
            error_preview = task.error[:60] if task.error else "Unknown error"
            message += f"❌ #{task.task_id} - {task.description[:50]}\n"
            message += f"   Error: {error_preview}\n\n"

        if len(failed_tasks) > 5:
            message += f"... and {len(failed_tasks) - 5} more\n\n"

        message += "\nUse /retry <task_id> to retry a specific task\n"
        message += "Example: /retry " + failed_tasks[0].task_id

        await send_formatted_response(context, user_id, message)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - stop a running task"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Check if task ID was provided
    if not context.args or len(context.args) == 0:
        # No task ID provided - show usage
        active_tasks = task_manager.get_active_tasks(user_id)

        if not active_tasks:
            await update.message.reply_text("No active tasks to stop.")
            return

        message = "Active Tasks\n\n"
        message += "Use /stop <task_id> to stop a specific task\n\n"

        for task in active_tasks[:5]:  # Show up to 5 active tasks
            status_icon = "🔄" if task.status == "pending" else "▶️"
            message += f"{status_icon} #{task.task_id} - {task.description[:50]}\n"

        if len(active_tasks) > 5:
            message += f"\n... and {len(active_tasks) - 5} more"

        message += f"\n\nExample: /stop {active_tasks[0].task_id}"

        await send_formatted_response(context, user_id, message)
        return

    # Stop specific task
    task_id = context.args[0].lstrip("#")  # Remove # if present

    # Check if task exists and belongs to user
    task = task_manager.get_task(task_id)
    if not task:
        message = f"Task #{task_id} not found."
        await send_formatted_response(context, user_id, message)
        return

    if task.user_id != user_id:
        await update.message.reply_text("You don't have permission to stop this task.")
        return

    # Stop the task
    success, message = task_manager.stop_task(task_id)

    if success:
        message = f"Task Stopped #{task_id}\n\n{task.description}\n\nYou can retry it later with /retry {task_id}"

    await send_formatted_response(context, user_id, message)


async def stopall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stopall command - stop all active tasks"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Get active tasks
    active_tasks = task_manager.get_active_tasks(user_id)

    if not active_tasks:
        await update.message.reply_text("No active tasks to stop.")
        return

    # Stop all active tasks
    stopped_count, failed_count, failed_task_ids = task_manager.stop_all_tasks(user_id)

    # Build response message
    message = f"Stopped {stopped_count} task(s)"

    if failed_count > 0:
        message += f"\n\nFailed to stop {failed_count} task(s):"
        for task_id in failed_task_ids:
            message += f"\n• #{task_id}"

    if stopped_count > 0:
        message += "\n\nYou can retry stopped tasks with /retry"

    await send_formatted_response(context, user_id, message)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command - priority command that executes immediately"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id

    # Check if user wants to clear errors specifically
    if context.args and len(context.args) > 0 and context.args[0].lower() == "errors":
        # Clear all failed tasks immediately
        all_failed = task_manager.get_failed_tasks(user_id, limit=1000)
        cleared_count = 0
        for task in all_failed:
            if task.task_id in task_manager.tasks:
                del task_manager.tasks[task.task_id]
                cleared_count += 1

        if cleared_count > 0:
            task_manager._save_tasks()
            logger.info(f"Manually cleared {cleared_count} failed tasks for user {user_id}")
            await update.message.reply_text(f"Cleared {cleared_count} failed task(s) from history.")
        else:
            await update.message.reply_text("No failed tasks to clear!")
        return

    # Clear the session immediately (bypasses queue)
    session_manager.clear_session(user_id)
    logger.info(f"Priority /clear: Cleared session for user {user_id}")

    await update.message.reply_text("Conversation cleared! Starting fresh.")


async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /restart command - gracefully restart the bot"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    logger.info(f"Restart requested by user {user_id}")

    # Send acknowledgment and wait for it to complete
    restart_msg = None
    try:
        restart_msg = await update.message.reply_text("🔄 Restarting...")
        logger.info(f"Sent restart message to user {user_id}")
    except Exception as e:
        logger.error(f"Failed to send restart acknowledgment: {e}")
        # Don't restart if we can't even send the message
        await update.message.reply_text("Failed to initiate restart. Please try again.")
        return

    # Save restart state immediately (synchronously)
    import json
    import time

    restart_state = {
        "user_id": user_id,
        "chat_id": chat_id,
        "message_id": restart_msg.message_id if restart_msg else None,
        "timestamp": time.time(),  # Use Unix timestamp, not event loop time
    }

    restart_state_path = Path("data/restart_state.json")
    restart_state_path.parent.mkdir(exist_ok=True)
    with open(restart_state_path, "w") as f:
        json.dump(restart_state, f)

    logger.info(f"Saved restart state for user {user_id}")

    # Schedule exit after ensuring message is sent
    async def delayed_exit():
        # Give more time for the message to be fully delivered
        await asyncio.sleep(1.0)
        logger.info("Exiting for restart...")
        import os

        # Monitoring server runs independently via launchd, will auto-restart
        # Flush logs before exit
        for handler in logging.root.handlers:
            handler.flush()

        # Exit with non-zero code to trigger launchd restart
        os._exit(42)  # Exit code 42 = intentional restart (launchd auto-restarts on non-zero)

    asyncio.create_task(delayed_exit())


def is_priority_command(message_text: str) -> bool:
    """
    Check if message is a priority command that should bypass the queue.
    Priority commands: /restart, /start, /clear

    These need immediate execution even if bot is processing something.
    """
    if not message_text:
        return False

    text_lower = message_text.lower().strip()
    priority_commands = ["/restart", "restart", "/start", "start", "/clear", "clear"]

    return any(text_lower == cmd or text_lower.startswith(cmd + " ") for cmd in priority_commands)


def extract_workspace_from_message(message: str) -> tuple[str | None, str]:
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
    pattern1 = r"^in\s+([~/\w\-/.]+)[,\s]+(.+)$"
    match = re.match(pattern1, message, re.IGNORECASE)
    if match:
        workspace = os.path.expanduser(match.group(1).strip())
        cleaned = match.group(2).strip()
        return workspace, cleaned

    # Pattern: "for repository <path>, <rest>"
    pattern2 = r"^for\s+(?:repository|repo|project)\s+([~/\w\-/.]+)[,\s]+(.+)$"
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
        "modify",
        "change",
        "update",
        "fix",
        "refactor",
        "add",
        "create",
        "build",
        "implement",
        "write code",
        "edit",
        "commit",
        "git",
        "file",
        "repository",
        "repo",
    ]

    # Status query keywords
    status_keywords = ["status", "progress", "tasks", "running"]

    # Check for status queries
    if any(kw in message_lower for kw in status_keywords):
        return "status_query"

    # Check for code tasks
    if any(kw in message_lower for kw in code_keywords):
        return "code_task"

    return "chat"


async def execute_code_task(task: "Task", update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute a code task in the background with full tool access"""
    user_id = update.effective_user.id

    try:
        # Update task status
        task_manager.update_task(task.task_id, status="running")
        logger.info(f"Starting task execution: {task.task_id} in {task.workspace}")

        # Define PID callback to save PID immediately when process starts
        def save_pid_immediately(pid: int):
            """Called by claude_pool as soon as process starts"""
            task_manager.update_task(task.task_id, pid=pid)
            logger.info(f"Task {task.task_id} process started with PID {pid}")

        # Define progress callback to log activity (no user updates)
        def send_progress_update(status_message: str, elapsed_seconds: int):
            """Called periodically with progress updates"""
            # Log activity to task manager for visibility in status/dashboard
            # Extract output line count if present in message
            output_lines = None
            if "output lines" in status_message:
                import re

                match = re.search(r"(\d+) output lines", status_message)
                if match:
                    output_lines = int(match.group(1))

            # Log to task manager (stored for status queries and dashboard)
            task_manager.log_activity(task.task_id, status_message, output_lines, save=True)

        # Execute using Claude session pool with bot context
        success, result, pid = await claude_pool.execute_task(
            task_id=task.task_id,
            description=task.description,
            workspace=Path(task.workspace),
            bot_repo_path=BOT_REPOSITORY,  # Always provide bot context
            model=task.model,
            agent=task.worker_type,  # Use worker_type as agent name (e.g., 'frontend_worker', 'code_worker')
            pid_callback=save_pid_immediately,  # Save PID immediately when process starts
            progress_callback=send_progress_update,  # Log activity for status/dashboard
        )

        # Update task with result
        if success:
            task_manager.update_task(task.task_id, status="completed", result=result)
            logger.info(f"Task {task.task_id} completed successfully")

            # Notify user with minimal inline message + MD attachment
            notification = f"Task Complete #{task.task_id}\n\n{task.description}\n\n📄 Full response attached..."
            full_response = f"{task.description}\n\n{result}"
        else:
            task_manager.update_task(task.task_id, status="failed", error=result)
            logger.error(f"Task {task.task_id} failed: {result}")

            # Notify user of failure with minimal inline message + MD attachment
            notification = f"Task Failed #{task.task_id}\n\n{task.description}\n\n📄 Error details attached..."
            full_response = f"{task.description}\n\n{result}"

        # Send minimal inline notification
        await send_formatted_response(context, user_id, notification)

        # Send full result as markdown document attachment
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, prefix=f"task_{task.task_id}_") as tmp:
            tmp.write(full_response)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as doc:
                await context.bot.send_document(
                    chat_id=user_id, document=doc, filename=f"task_{task.task_id}_result.md"
                )
        finally:
            # Clean up temporary file
            Path(tmp_path).unlink(missing_ok=True)

    except Exception as e:
        logger.error(f"Task execution error for {task.task_id}: {e}")
        task_manager.update_task(task.task_id, status="failed", error=str(e))

        # Notify user with minimal inline message + MD attachment
        notification = f"Task Failed #{task.task_id}\n\n{task.description}\n\n📄 Error details attached..."
        full_response = f"{task.description}\n\nUnexpected error: {str(e)}"

        # Send minimal inline notification
        await send_formatted_response(context, user_id, notification)

        # Send error details as markdown document attachment
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, prefix=f"task_{task.task_id}_") as tmp:
            tmp.write(full_response)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as doc:
                await context.bot.send_document(chat_id=user_id, document=doc, filename=f"task_{task.task_id}_error.md")
        finally:
            # Clean up temporary file
            Path(tmp_path).unlink(missing_ok=True)


async def show_task_status(user_id: int, update: Update):
    """Show user's task status"""
    # Get active tasks
    active_tasks = task_manager.get_active_tasks(user_id)

    # Get recent completed/failed tasks
    recent_tasks = task_manager.get_user_tasks(user_id, limit=5)
    completed = [t for t in recent_tasks if t.status == "completed"][:3]
    failed = [t for t in recent_tasks if t.status == "failed"][:3]

    # Build status message (plain text - formatter will convert to HTML)
    message_parts = ["Task Status\n"]

    # Active tasks
    if active_tasks:
        message_parts.append(f"\nActive Tasks ({len(active_tasks)}):")
        for task in active_tasks:
            status_icon = "[P]" if task.status == "pending" else "[R]"
            message_parts.append(f"{status_icon} #{task.task_id} - {task.description[:50]}...")
    else:
        message_parts.append("\nNo active tasks")

    # Recent completed
    if completed:
        message_parts.append(f"\n\nRecent Completed ({len(completed)}):")
        for task in completed:
            message_parts.append(f"• #{task.task_id} - {task.description[:40]}...")

    # Recent failed
    if failed:
        message_parts.append(f"\n\nRecent Failed ({len(failed)}):")
        for task in failed:
            message_parts.append(f"• #{task.task_id} - {task.description[:40]}...")

    message_parts.append("\n\nUse task ID to see details")

    # Format and send using HTML formatter
    message = "\n".join(message_parts)
    formatted_chunks = format_telegram_response(message, max_length=4000)
    for chunk in formatted_chunks:
        await update.message.reply_text(chunk, parse_mode="HTML")


async def process_message_async(
    user_id: int,
    message_text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ack_message_id: int | None = None,
):
    """Process message asynchronously in background"""
    try:
        # Get conversation history
        session = session_manager.get_session(user_id)
        history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

        # Get workspace and discover repositories
        current_workspace = session_manager.get_workspace(user_id)
        available_repos = discover_repositories(WORKSPACE_PATH)

        # Check for uncommitted changes blocking work
        git_tracker = get_git_tracker()
        target_repo = current_workspace or WORKSPACE_PATH
        blocking_msg = git_tracker.get_blocking_message(target_repo)

        if blocking_msg:
            response = blocking_msg
            background_task_info = None
        else:
            # Get active tasks info
            all_tasks = task_manager.tasks.values()
            active_tasks_info = [
                {"task_id": t.task_id, "description": t.description, "status": t.status, "workspace": t.workspace}
                for t in all_tasks
                if t.status in ["pending", "running"]
            ]

            # Ask Claude via API (fast, no file tools needed for routing)
            response, background_task_info, usage_info = await ask_claude(
                user_query=message_text,
                input_method="text",
                conversation_history=history,
                current_workspace=current_workspace,
                bot_repository=BOT_REPOSITORY,
                workspace_path=WORKSPACE_PATH,
                available_repositories=available_repos,
                active_tasks=active_tasks_info,
            )

        # Delete acknowledgment message if it exists
        if ack_message_id:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=ack_message_id)
            except Exception as e:
                logger.debug(f"Could not delete acknowledgment message: {e}")

        if not response:
            # Fallback to direct Claude response
            logger.warning("Claude API returned empty response, using fallback")
            response = await claude_client.send_message(user_id, message_text)
            background_task_info = None

        # Check if background task should be created
        if background_task_info:
            task_desc = background_task_info["description"]
            user_message = background_task_info["user_message"]

            # Create background task - ALWAYS use orchestrator (it delegates to sub-workers)
            workspace = current_workspace or WORKSPACE_PATH
            task = task_manager.create_task(
                user_id=user_id, description=task_desc, workspace=workspace, model="sonnet", worker_type="orchestrator"
            )

            # Submit task to worker pool (non-blocking)
            logger.info(f"Submitted orchestrator task {task.task_id} to worker pool")
            await worker_pool.submit(execute_code_task, task, update, context)

            # Send user-facing message
            response = f"Task #{task.task_id} started.\n\n{user_message}"

        # Queue session writes to worker pool (non-blocking)
        await worker_pool.submit(_async_add_session_message, user_id, "user", message_text)
        await worker_pool.submit(_async_add_session_message, user_id, "assistant", response)

        # Queue cost tracking to worker pool (non-blocking)
        # Use actual token counts from API if available, otherwise estimate
        if usage_info:
            input_tokens = usage_info.get("input_tokens", cost_tracker.estimate_tokens(message_text))
            output_tokens = usage_info.get("output_tokens", cost_tracker.estimate_tokens(response))
        else:
            input_tokens = cost_tracker.estimate_tokens(message_text)
            output_tokens = cost_tracker.estimate_tokens(response)
        await worker_pool.submit(_async_record_usage, user_id, "haiku", input_tokens, output_tokens, "chat")

        # Format and send response to user (uses helper that handles document attachment)
        await send_formatted_response(context, user_id, response, workspace_path=session_manager.get_workspace(user_id))

    except Exception as e:
        logger.error(f"Error in async message processing for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id, text="An error occurred while processing your message. Please try again."
        )


async def _handle_message_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Implementation of message handling (called from queue)"""
    user_id = update.effective_user.id
    message_text = update.message.text

    logger.info(f"User {user_id} (text): {message_text}")

    # Check rate limits
    allowed, error_msg = rate_limiter.check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(error_msg)
        return

    # Check cost limits
    allowed, warning_msg = cost_tracker.check_limits(user_id)
    if not allowed:
        await update.message.reply_text(warning_msg)
        return

    # Record rate limit request
    rate_limiter.record_request(user_id)

    # Send warning if approaching limits (but don't block)
    if warning_msg:
        await update.message.reply_text(warning_msg)

    # Send acknowledgment message
    ack_message = await update.message.reply_text("Thinking")
    ack_message_id = ack_message.message_id

    # Launch background task for orchestrator processing (no await)
    # This allows the function to return immediately while work happens async
    asyncio.create_task(process_message_async(user_id, message_text, update, context, ack_message_id))

    logger.info(f"Queued async processing for user {user_id}: {message_text[:60]}...")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue text messages for sequential processing, with priority for commands"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    message_text = update.message.text or ""

    # Check if this is a priority command (should not normally happen since
    # CommandHandler catches /start, /clear, etc., but good defensive check)
    if is_priority_command(message_text):
        logger.info(f"Priority text command detected: {message_text[:50]}")
        # Queue with high priority
        await queue_manager.enqueue_message(
            user_id=user_id,
            update=update,
            context=context,
            handler=_handle_message_impl,
            handler_name="priority_text_command",
            priority=10,
        )
    else:
        # Queue with normal priority (no acknowledgment - orchestrator responds fast with Haiku)
        await queue_manager.enqueue_message(
            user_id=user_id,
            update=update,
            context=context,
            handler=_handle_message_impl,
            handler_name="text_message",
            priority=0,
        )


def transcribe_audio(file_path: str) -> str | None:
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


async def process_document_async(
    user_id: int, message_text: str, tmp_path: str, update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Process document asynchronously in background"""
    try:
        # Get conversation history
        session = session_manager.get_session(user_id)
        history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

        # Get workspace and repos
        current_workspace = session_manager.get_workspace(user_id)
        available_repos = discover_repositories(WORKSPACE_PATH)

        # Check git
        git_tracker = get_git_tracker()
        target_repo = current_workspace or WORKSPACE_PATH
        blocking_msg = git_tracker.get_blocking_message(target_repo)

        if blocking_msg:
            response = blocking_msg
            background_task_info = None
        else:
            # Get active tasks
            all_tasks = task_manager.tasks.values()
            active_tasks_info = [
                {"task_id": t.task_id, "description": t.description, "status": t.status, "workspace": t.workspace}
                for t in all_tasks
                if t.status in ["pending", "running"]
            ]

            # Ask Claude API
            response, background_task_info, usage_info = await ask_claude(
                user_query=message_text,
                input_method="text",
                conversation_history=history,
                current_workspace=current_workspace,
                bot_repository=BOT_REPOSITORY,
                workspace_path=WORKSPACE_PATH,
                available_repositories=available_repos,
                active_tasks=active_tasks_info,
            )

        if not response:
            logger.warning("Claude API returned empty response (document), using fallback")
            response = await claude_client.send_message(user_id, message_text)
            background_task_info = None

        # Check if background task should be created
        if background_task_info:
            task_desc = background_task_info["description"]
            user_message = background_task_info["user_message"]
            workspace = current_workspace or WORKSPACE_PATH
            task = task_manager.create_task(
                user_id=user_id, description=task_desc, workspace=workspace, model="sonnet", worker_type="orchestrator"
            )
            logger.info(f"Submitted orchestrator task {task.task_id} to worker pool (document)")
            await worker_pool.submit(execute_code_task, task, update, context)
            response = f"Task #{task.task_id} started.\n\n{user_message}"

        # Queue session writes to worker pool (non-blocking)
        await worker_pool.submit(_async_add_session_message, user_id, "user", message_text)
        await worker_pool.submit(_async_add_session_message, user_id, "assistant", response)

        # Format and send response to user (uses helper that handles document attachment)
        await send_formatted_response(context, user_id, response, workspace_path=session_manager.get_workspace(user_id))

    except Exception as e:
        logger.error(f"Error in async document processing for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id, text="An error occurred while processing your document. Please try again."
        )
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


async def _handle_document_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Implementation of document handling (called from queue)"""
    user_id = update.effective_user.id
    document = update.message.document
    caption = update.message.caption or ""

    logger.info(f"User {user_id} sent document: {document.file_name} ({document.mime_type})")

    # Check file size (limit to 20MB for safety)
    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("File too large. Maximum size is 20MB.")
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        # Download file
        file = await context.bot.get_file(document.file_id)

        # Create temp file with original extension
        file_ext = Path(document.file_name).suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
            tmp_path = tmp.name

        # Download to temp file
        await file.download_to_drive(tmp_path)
        logger.info(f"Downloaded document to {tmp_path}")

        # Read file content (text-based files only)
        try:
            with open(tmp_path, encoding="utf-8") as f:
                file_content = f.read()
        except UnicodeDecodeError:
            # Binary file (PDF, images, etc.) - just provide path
            file_content = f"[Binary file: {document.file_name}]"
            logger.info(f"Binary file detected: {document.file_name}")

        # Build message with file context
        if caption:
            message_text = f"{caption}\n\n[Attached file: {document.file_name}]\n{file_content[:2000]}"
        else:
            message_text = f"I've uploaded a file: {document.file_name}\n\n{file_content[:2000]}"

        if len(file_content) > 2000:
            message_text += f"\n\n... (file truncated, total {len(file_content)} chars)"

        logger.info(f"User {user_id} (document): {message_text[:100]}...")

        # Launch background task for processing (no await)
        asyncio.create_task(process_document_async(user_id, message_text, tmp_path, update, context))

        logger.info(f"Queued async processing for document from user {user_id}")

    except Exception as e:
        logger.error(f"Document download/prep error: {e}")
        await update.message.reply_text("Error downloading file. Please try again.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue document uploads for sequential processing"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    await queue_manager.enqueue_message(
        user_id=user_id, update=update, context=context, handler=_handle_document_impl, handler_name="document"
    )


async def process_photo_async(
    user_id: int, message_text: str, tmp_path: str, update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Process photo asynchronously in background"""
    try:
        # Get conversation history
        session = session_manager.get_session(user_id)
        history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

        # Get workspace and repos
        current_workspace = session_manager.get_workspace(user_id)
        available_repos = discover_repositories(WORKSPACE_PATH)

        # Check git
        git_tracker = get_git_tracker()
        target_repo = current_workspace or WORKSPACE_PATH
        blocking_msg = git_tracker.get_blocking_message(target_repo)

        if blocking_msg:
            response = blocking_msg
            background_task_info = None
        else:
            # Get active tasks
            all_tasks = task_manager.tasks.values()
            active_tasks_info = [
                {"task_id": t.task_id, "description": t.description, "status": t.status, "workspace": t.workspace}
                for t in all_tasks
                if t.status in ["pending", "running"]
            ]

            # Ask Claude API with image
            response, background_task_info, usage_info = await ask_claude(
                user_query=message_text,
                input_method="text",
                conversation_history=history,
                current_workspace=current_workspace,
                bot_repository=BOT_REPOSITORY,
                workspace_path=WORKSPACE_PATH,
                available_repositories=available_repos,
                active_tasks=active_tasks_info,
                image_path=tmp_path,  # Pass image file path
            )

        if not response:
            logger.warning("Claude API returned empty response (photo), using fallback")
            response = await claude_client.send_message(user_id, message_text)
            background_task_info = None

        # Check if background task should be created
        if background_task_info:
            task_desc = background_task_info["description"]
            user_message = background_task_info["user_message"]
            workspace = current_workspace or WORKSPACE_PATH
            task = task_manager.create_task(
                user_id=user_id, description=task_desc, workspace=workspace, model="sonnet", worker_type="orchestrator"
            )
            logger.info(f"Submitted orchestrator task {task.task_id} to worker pool (photo)")
            await worker_pool.submit(execute_code_task, task, update, context)
            response = f"Task #{task.task_id} started.\n\n{user_message}"

        # Queue session writes to worker pool (non-blocking)
        await worker_pool.submit(_async_add_session_message, user_id, "user", message_text)
        await worker_pool.submit(_async_add_session_message, user_id, "assistant", response)

        # Format and send response to user (uses helper that handles document attachment)
        await send_formatted_response(context, user_id, response, workspace_path=session_manager.get_workspace(user_id))

    except Exception as e:
        logger.error(f"Error in async photo processing for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id, text="An error occurred while processing your image. Please try again."
        )
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


async def _handle_photo_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Implementation of photo handling (called from queue)"""
    user_id = update.effective_user.id
    photo = update.message.photo[-1]  # Get highest resolution
    caption = update.message.caption or ""

    logger.info(f"User {user_id} sent photo")

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        # Download photo
        file = await context.bot.get_file(photo.file_id)

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        # Download to temp file
        await file.download_to_drive(tmp_path)
        logger.info(f"Downloaded photo to {tmp_path}")

        # Build message with photo context
        if caption:
            message_text = f"{caption}\n\n[Attached image: photo.jpg]"
        else:
            message_text = "I've uploaded an image. Can you analyze it?"

        logger.info(f"User {user_id} (photo): {message_text}")

        # Launch background task for processing (no await)
        asyncio.create_task(process_photo_async(user_id, message_text, tmp_path, update, context))

        logger.info(f"Queued async processing for photo from user {user_id}")

    except Exception as e:
        logger.error(f"Photo download/prep error: {e}")
        await update.message.reply_text("Error downloading image. Please try again.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue photo uploads for sequential processing"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    await queue_manager.enqueue_message(
        user_id=user_id, update=update, context=context, handler=_handle_photo_impl, handler_name="photo"
    )


async def process_voice_async(
    user_id: int,
    transcription: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    ack_message_id: int | None = None,
):
    """Process voice message asynchronously in background"""
    try:
        # Get conversation history
        session = session_manager.get_session(user_id)
        history = [{"role": msg.role, "content": msg.content} for msg in session.history] if session else []

        # Get workspace and discover repositories
        current_workspace = session_manager.get_workspace(user_id)
        available_repos = discover_repositories(WORKSPACE_PATH)

        # Check for uncommitted changes
        git_tracker = get_git_tracker()
        target_repo = current_workspace or WORKSPACE_PATH
        blocking_msg = git_tracker.get_blocking_message(target_repo)

        if blocking_msg:
            response = blocking_msg
            background_task_info = None
        else:
            # Get active tasks
            all_tasks = task_manager.tasks.values()
            active_tasks_info = [
                {"task_id": t.task_id, "description": t.description, "status": t.status, "workspace": t.workspace}
                for t in all_tasks
                if t.status in ["pending", "running"]
            ]

            # Ask Claude via API with VOICE input (be permissive with errors)
            response, background_task_info, usage_info = await ask_claude(
                user_query=transcription,
                input_method="voice",  # Important: tells Claude to be permissive with voice transcription errors
                conversation_history=history,
                current_workspace=current_workspace,
                bot_repository=BOT_REPOSITORY,
                workspace_path=WORKSPACE_PATH,
                available_repositories=available_repos,
                active_tasks=active_tasks_info,
            )

        # Delete acknowledgment message if it exists
        if ack_message_id:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=ack_message_id)
            except Exception as e:
                logger.debug(f"Could not delete acknowledgment message: {e}")

        if not response:
            logger.warning("Claude API returned empty response (voice), using fallback")
            response = await claude_client.send_message(user_id, transcription)
            background_task_info = None

        # Check if background task should be created
        if background_task_info:
            task_desc = background_task_info["description"]
            user_message = background_task_info["user_message"]
            workspace = current_workspace or WORKSPACE_PATH
            task = task_manager.create_task(
                user_id=user_id, description=task_desc, workspace=workspace, model="sonnet", worker_type="orchestrator"
            )
            logger.info(f"Submitted orchestrator task {task.task_id} to worker pool (voice)")
            await worker_pool.submit(execute_code_task, task, update, context)
            response = f"Task #{task.task_id} started.\n\n{user_message}"

        # Queue session writes to worker pool (non-blocking)
        await worker_pool.submit(_async_add_session_message, user_id, "user", transcription)
        await worker_pool.submit(_async_add_session_message, user_id, "assistant", response)

        # Format and send response to user (uses helper that handles document attachment)
        await send_formatted_response(context, user_id, response, workspace_path=session_manager.get_workspace(user_id))

    except Exception as e:
        logger.error(f"Error in async voice processing for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=user_id, text="An error occurred while processing your voice message. Please try again."
        )


async def _handle_voice_impl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Implementation of voice handling (called from queue)"""
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
            await update.message.reply_text("Transcription failed. Please try again or send text.")
            return

        logger.info(f"User {user_id} (voice): {transcription}")

        # Send acknowledgment message
        ack_message = await update.message.reply_text("Thinking")
        ack_message_id = ack_message.message_id

        # Launch background task for processing (no await)
        asyncio.create_task(process_voice_async(user_id, transcription, update, context, ack_message_id))

        logger.info(f"Queued async processing for voice from user {user_id}")

    except Exception as e:
        logger.error(f"Voice download/transcription error: {e}")
        await update.message.reply_text("Error processing voice message. Please try again.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue voice messages for sequential processing"""
    if not await check_authorization(update):
        return

    user_id = update.effective_user.id
    await queue_manager.enqueue_message(
        user_id=user_id, update=update, context=context, handler=_handle_voice_impl, handler_name="voice"
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

    if update and update.message:
        await update.message.reply_text("An error occurred. Please try again.")


async def cleanup_task(context: ContextTypes.DEFAULT_TYPE):
    """Periodic task to cleanup stale sessions and tasks"""
    # Clean up stale sessions
    session_count = session_manager.cleanup_stale_sessions()
    if session_count > 0:
        logger.info(f"Cleanup task: removed {session_count} stale sessions")

    # Clean up stale pending tasks (older than 1 hour)
    task_count = task_manager.cleanup_stale_pending_tasks(max_age_hours=1)
    if task_count > 0:
        logger.info(f"Cleanup task: marked {task_count} stale pending tasks as failed")


async def log_issue_notification(issue, should_escalate: bool):
    """
    Notification callback for log monitoring
    Called when bot detects issues in logs
    """
    if not ALLOWED_USERS:
        return

    # Only notify the first allowed user (usually the owner)
    user_id = ALLOWED_USERS[0]

    try:
        # Build notification message (plain text - formatter will handle HTML conversion)
        title = issue.title
        severity = issue.level.value.upper()
        description = issue.description

        message = f"🔍 Log Monitor Alert [{severity}]\n\n"
        message += f"{title}\n"
        message += f"{description}\n\n"

        if issue.evidence:
            message += "Evidence:\n"
            for evidence_line in issue.evidence[:2]:
                # Truncate long evidence lines
                if len(evidence_line) > 100:
                    evidence_line = evidence_line[:97] + "..."
                message += f"  {evidence_line}\n"

        message += "\n"

        if should_escalate:
            # Queue escalation to Claude
            log_escalation.add_to_escalation_queue(issue)

            # Perform Claude analysis asynchronously
            analysis_result = await log_escalation.analyze_issues_with_claude([issue], logs_context=None)

            if analysis_result.get("analysis"):
                analysis_msg = f"\nClaude Analysis:\n{analysis_result['analysis'][:500]}"
                if len(analysis_result["analysis"]) > 500:
                    analysis_msg += "\n\n... (truncated)"

                message += analysis_msg

                # Create confirmation request if fixes are suggested
                if analysis_result.get("suggested_fixes"):
                    conf_id = user_confirmations.create_confirmation_request(
                        issue=issue, suggested_action="\n".join(analysis_result["suggested_fixes"][:2]), confidence=0.85
                    )
                    message += f"\n\n✅ /approve {conf_id} to apply\n"
                    message += f"❌ /reject {conf_id} to skip\n"

        # Get bot instance from application (requires global reference)
        from telegram import Bot

        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        # Format response using the formatter (handles HTML entities properly)
        formatted_chunks = format_telegram_response(message, max_length=4000)

        # Send formatted chunks
        for chunk in formatted_chunks:
            await bot.send_message(chat_id=user_id, text=chunk, parse_mode="HTML")

        logger.info(f"Sent log alert to user {user_id}: {issue.title}")

    except Exception as e:
        logger.error(f"Error sending log notification: {e}")


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
        logger.info("Initializing bot (post_init)...")
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Start fresh (clears history)"),
                BotCommand("status", "Active tasks & errors"),
                BotCommand("usage", "Show detailed API usage & costs"),
                BotCommand("retry", "Retry failed tasks"),
                BotCommand("stop", "Stop a running task"),
                BotCommand("stopall", "Stop all active tasks"),
                BotCommand("clear", "Clear conversation"),
                BotCommand("restart", "Restart the bot"),
            ]
        )
        logger.info("Bot commands registered")

    application.post_init = post_init

    # Cleanup and shutdown handler
    async def shutdown(app: Application):
        logger.info("Shutting down...")

        # Mark all in-progress tasks as stopped before shutdown
        logger.info("Marking in-progress tasks as stopped...")
        stopped_count = task_manager.mark_all_running_as_stopped()
        logger.info(f"Marked {stopped_count} tasks as stopped")

        logger.info("Stopping worker pool...")
        await worker_pool.stop()
        logger.info("Worker pool stopped")

        logger.info("Cleaning up message queues...")
        await queue_manager.cleanup_all()

        # Log monitor is disabled, skip stopping
        # logger.info("Stopping log monitor...")
        # await log_monitor_manager.stop()

        logger.info("Shutdown complete")

    application.post_stop = shutdown

    # Start log monitoring after app is initialized
    # DISABLED: Log monitoring alerts are disabled
    # async def start_log_monitor(app: Application):
    #     logger.info("Starting background log monitoring...")
    #     await log_monitor_manager.start(log_issue_notification)

    # Hook to start worker pool and log monitor after post_init
    original_post_init = application.post_init

    async def new_post_init(app: Application):
        if original_post_init:
            await original_post_init(app)

        # Start worker pool FIRST - before any operations that might need it
        logger.info("Starting background worker pool...")
        await worker_pool.start()
        logger.info(f"Worker pool started with {worker_pool.max_workers} workers")

        # Check for restart state and notify user
        import json
        from pathlib import Path

        restart_state_path = Path("data/restart_state.json")
        if restart_state_path.exists():
            try:
                logger.info("Found restart state file, processing...")
                with open(restart_state_path) as f:
                    restart_state = json.load(f)

                user_id = restart_state.get("user_id")
                chat_id = restart_state.get("chat_id")
                message_id = restart_state.get("message_id")
                timestamp = restart_state.get("timestamp")

                # Validate restart state - if invalid, skip restart notification but continue initialization
                if not user_id or not chat_id:
                    logger.warning("Invalid restart state: missing user_id or chat_id, skipping restart notification")
                    restart_state_path.unlink()
                elif timestamp:
                    import time

                    age = time.time() - timestamp
                    if age > 300:  # 5 minutes
                        logger.warning(f"Restart state too old ({age:.0f}s), discarding, skipping restart notification")
                        restart_state_path.unlink()
                    else:
                        # Valid restart state - process it
                        try:
                            # Clear the user's session
                            session_manager.clear_session(user_id)
                            logger.info(f"Cleared session for user {user_id} after restart")

                            # Update or send completion message
                            if message_id:
                                # Try to update the "Restarting..." message
                                try:
                                    await app.bot.edit_message_text(
                                        chat_id=chat_id, message_id=message_id, text="✅ Ready! Fresh start."
                                    )
                                    logger.info(f"Updated restart message for user {user_id}")
                                except Exception as edit_error:
                                    # If edit fails (message too old, etc), send new message
                                    logger.warning(f"Failed to edit restart message: {edit_error}, sending new message")
                                    await app.bot.send_message(chat_id=chat_id, text="✅ Ready! Fresh start.")
                            else:
                                # Send new message if we don't have a message_id
                                await app.bot.send_message(chat_id=chat_id, text="✅ Ready! Fresh start.")
                            logger.info(f"Sent restart completion to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to process restart notification: {e}")

                        # Clean up restart state file
                        restart_state_path.unlink()
                        logger.info("Restart sequence completed successfully")
                else:
                    # No timestamp, process as valid for backwards compatibility
                    try:
                        session_manager.clear_session(user_id)
                        logger.info(f"Cleared session for user {user_id} after restart")

                        if message_id:
                            try:
                                await app.bot.edit_message_text(
                                    chat_id=chat_id, message_id=message_id, text="✅ Ready! Fresh start."
                                )
                            except Exception:
                                await app.bot.send_message(chat_id=chat_id, text="✅ Ready! Fresh start.")
                        else:
                            await app.bot.send_message(chat_id=chat_id, text="✅ Ready! Fresh start.")
                        logger.info(f"Sent restart completion to user {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to process restart notification: {e}")

                    restart_state_path.unlink()
                    logger.info("Restart sequence completed")

            except Exception as e:
                logger.error(f"Error processing restart state: {e}", exc_info=True)
                # Clean up even if there was an error
                try:
                    if restart_state_path.exists():
                        restart_state_path.unlink()
                        logger.info("Cleaned up restart state file after error")
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up restart state file: {cleanup_error}")

        # Clean up old pending tasks (stuck from previous bot issues)
        logger.info("Checking for orphaned pending tasks...")
        from datetime import datetime, timedelta

        now = datetime.now()
        cutoff = now - timedelta(minutes=5)  # Pending > 5 minutes is stuck
        cleaned = 0

        for task in list(task_manager.tasks.values()):
            if task.status == "pending":
                created_time = datetime.fromisoformat(task.created_at)
                if created_time < cutoff:
                    # Task stuck in pending - mark as failed
                    task_manager.update_task(
                        task.task_id,
                        status="failed",
                        error="Task stuck in pending state - never submitted to worker pool",
                    )
                    cleaned += 1
                    logger.warning(f"Cleaned stuck pending task {task.task_id} (created {task.created_at})")

        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} orphaned pending tasks")
        else:
            logger.info("No orphaned pending tasks found")

        # Auto-retry disabled - it creates pending tasks that never get submitted to worker pool
        # Users can manually retry via /retry command
        logger.info("Auto-retry of stopped tasks is disabled")
        stopped_tasks = task_manager.get_stopped_tasks()
        if stopped_tasks:
            logger.info(f"Found {len(stopped_tasks)} stopped tasks - use /retry to retry them manually")
        else:
            logger.info("No stopped tasks found")

        # Start log monitoring - DISABLED
        # await start_log_monitor(app)
        logger.info("Log monitoring alerts are disabled")

    application.post_init = new_post_init

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("usage", usage_command))
    application.add_handler(CommandHandler("retry", retry_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("stopall", stopall_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("restart", restart_command))

    # Handle messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

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
