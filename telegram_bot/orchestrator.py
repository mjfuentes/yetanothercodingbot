"""
Orchestrator agent integration for Telegram bot
Simplified: Just invoke Claude Code with context, orchestrator handles everything
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from git_tracker import get_git_tracker

logger = logging.getLogger(__name__)


def discover_repositories(base_path: str) -> list[str]:
    """Discover git repositories in workspace"""
    repos = []
    base = Path(base_path)

    try:
        # Look for .git directories up to 2 levels deep
        for item in base.iterdir():
            if item.is_dir():
                if (item / ".git").exists():
                    repos.append(str(item))
                # Check one level deeper
                try:
                    for subitem in item.iterdir():
                        if subitem.is_dir() and (subitem / ".git").exists():
                            repos.append(str(subitem))
                except (PermissionError, OSError):
                    pass  # Skip directories we can't read
    except Exception as e:
        logger.warning(f"Error discovering repositories: {e}")

    return repos


async def invoke_orchestrator(
    user_query: str,
    input_method: str,  # "voice" or "text"
    conversation_history: list[dict],
    current_workspace: Optional[str],
    bot_repository: str,
    workspace_path: str,
    timeout: int = 300,
    task_manager=None  # TaskManager instance for background task creation
) -> Optional[str]:
    """
    Invoke orchestrator agent via Claude Code

    Returns:
        User-facing message string, or None on error
    """

    # Discover available repositories
    available_repos = discover_repositories(workspace_path)

    # Check for uncommitted changes blocking work
    git_tracker = get_git_tracker()

    # Determine target repo from query or current workspace
    target_repo = current_workspace or workspace_path

    # Check if blocked by dirty repos
    blocking_msg = git_tracker.get_blocking_message(target_repo)
    if blocking_msg:
        logger.info(f"Blocking work due to dirty repos")
        return blocking_msg

    # Get active tasks info if task_manager provided
    active_tasks_info = []
    if task_manager:
        # Get user's active tasks (pending or in_progress)
        user_id = None  # We need to pass user_id to this function
        # For now, get all active tasks - orchestrator will filter by context
        all_tasks = task_manager.tasks.values()
        active_tasks_info = [
            {
                "task_id": t.task_id,
                "description": t.description,
                "status": t.status,
                "workspace": t.workspace
            }
            for t in all_tasks
            if t.status in ["pending", "in_progress"]
        ]

    # Build context for orchestrator
    context = {
        "user_query": user_query,
        "input_method": input_method,
        "conversation_history": conversation_history[-3:],  # Last 3 messages (reduced context)
        "current_workspace": current_workspace or workspace_path,
        "available_repositories": available_repos,
        "bot_repository": bot_repository,
        "active_tasks": active_tasks_info
    }

    # Format prompt with context - ENHANCED with background task instructions
    prompt = f"""CONTEXT:
{json.dumps(context, indent=2)}

Handle this user query. You can respond directly, or spawn a code_worker agent for code modifications.

IMPORTANT CAPABILITIES:
- You have Glob, Grep, and Read tools that work with ABSOLUTE PATHS
- You can access ANY repository in available_repositories by using absolute paths
- Example: To list files in /Users/matifuentes/Workspace/groovetherapy, use: Glob with pattern="*" and path="/Users/matifuentes/Workspace/groovetherapy"
- Don't say you can't access repos - just use the tools with absolute paths!

BACKGROUND TASK SUPPORT:
- For COMPLEX tasks that involve multiple file changes, refactoring, or take >2 minutes, indicate this is a BACKGROUND_TASK
- To trigger background task, start your response with: "BACKGROUND_TASK: <brief description>"
- Then provide: The task will be executed in the background with full tool access
- Background tasks get full Claude Code access (Read, Write, Edit, Bash, Grep, Glob, etc.)
- User will be notified when the task completes

Examples of tasks that should be BACKGROUND:
- "refactor the entire authentication system"
- "implement a new feature with tests"
- "migrate database schema and update all models"
- "fix all type errors in the codebase"
- "build a new API endpoint with documentation"

Examples of tasks that should be IMMEDIATE:
- "what does this function do?"
- "explain the architecture"
- "show me the status of tasks"
- "read and summarize this file"

Remember:
- input_method="{input_method}" ({'be permissive with voice errors' if input_method == 'voice' else 'exact text input'})
- When user references "you"/"your code"/"the bot": {bot_repository}
- Current workspace: {current_workspace or workspace_path}
- USE CONVERSATION CONTEXT: If user just asked about a specific repo, assume subsequent actions apply to that repo
- Compose user-facing response (concise, mobile-friendly)

User query: {user_query}"""

    try:
        logger.info(f"Invoking orchestrator agent for: {user_query[:60]}...")

        # Invoke Claude Code in interactive mode
        # The orchestrator agent will automatically be available from .claude/agents/
        cmd = [
            "claude", "chat",
            "--model", "sonnet",  # Better understanding than Haiku
            "--permission-mode", "bypassPermissions"  # Auto-approve write operations
        ]

        logger.debug(f"Command: {' '.join(cmd)}")
        logger.debug(f"Working directory: {bot_repository}")

        # Run from bot_repository to load orchestrator agent config from .claude/agents/
        # Orchestrator can still access other repos using absolute paths via Glob/Grep/Read tools
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=bot_repository  # Run from bot repo to load .claude/agents/orchestrator.md
        )

        try:
            # Send prompt
            if process.stdin:
                process.stdin.write(f"{prompt}\n".encode())
                await process.stdin.drain()
                process.stdin.close()

            # Wait for response
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            output = stdout.decode().strip()

            if stderr:
                error_msg = stderr.decode().strip()
                if error_msg and not error_msg.startswith("Loading"):
                    logger.warning(f"Orchestrator stderr: {error_msg}")

            if not output:
                logger.error("Empty output from orchestrator")
                return None

            logger.info(f"Orchestrator response: {output[:100]}...")

            # Check if this is a background task request
            if output.startswith("BACKGROUND_TASK:"):
                lines = output.split('\n', 1)
                task_desc = lines[0].replace("BACKGROUND_TASK:", "").strip()
                user_message = lines[1].strip() if len(lines) > 1 else "Task queued for background execution."

                # We'll return a special format that main.py can parse
                # Format: "BACKGROUND_TASK|description|user_message"
                return f"BACKGROUND_TASK|{task_desc}|{user_message}"

            return output

        except asyncio.TimeoutError:
            logger.error(f"Orchestrator timeout after {timeout}s")
            if process:
                process.kill()
            return None

    except Exception as e:
        logger.error(f"Error invoking orchestrator: {e}")
        return None
