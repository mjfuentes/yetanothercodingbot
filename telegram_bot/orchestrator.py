"""
Orchestrator agent integration for Telegram bot

Proper separation of concerns:
- Orchestrator: Handles routing, user responses, simple queries via Task tool
- code_worker: Spawned by orchestrator for all file operations and code changes
"""

import asyncio
import json
import logging
import os
import subprocess
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
    task_manager=None,  # TaskManager instance for background task creation
    image_path: Optional[str] = None  # Path to uploaded image
) -> Optional[str]:
    """
    Invoke orchestrator agent via Claude Code (fire-and-forget pattern).

    IMPORTANT: This function returns IMMEDIATELY (<100ms) without waiting for
    Claude Code execution. The orchestrator subprocess runs detached from the
    parent process, allowing the bot to remain responsive.

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

    # Add image path if provided
    if image_path:
        context["image_path"] = image_path

    # Format prompt - orchestrator now handles routing and spawns code_worker for coding tasks
    prompt = f"""CONTEXT:
{json.dumps(context, indent=2)}

USER CONTEXT:
- Name: Matias Fuentes
- You are their personal engineering assistant
- Available projects: cloudmate, Latinamerica2026, permanent_residence, groovetherapy, mjfuentes.github.io, agentlab
- Use this project knowledge in conversations - reference their work and interests

YOUR ROLE:
You are the routing orchestrator. For user queries:
1. Answer directly if it's a question, chat, or knowledge request
2. Spawn code_worker if it's a coding task (file ops, code changes, git commands)
3. Use BACKGROUND_TASK format for complex tasks that should run async

ROUTING DECISION:
- QUESTIONS/CHAT: "what does X do?", "explain Y", "show me..." → Answer directly
- CODING TASKS: "fix bug in X", "add feature", "edit file", "commit changes" → Use Task tool to spawn code_worker
- COMPLEX WORK: Multi-file changes, refactoring, building projects → Use BACKGROUND_TASK format

SPAWNING CODE_WORKER:
For coding tasks, use the Task tool with:
```
subagent_type: "code_worker"
description: "Brief task description"
prompt: "Full context including workspace, task details, and any special instructions"
```

The code_worker will have access to: Read, Write, Edit, Glob, Grep, Bash

IMPORTANT:
- You can READ/ANALYZE files with your tools (Glob, Grep, Read)
- But DON'T attempt Write/Edit/Bash - spawn code_worker instead!
- code_worker handles all file modifications and git commands

BACKGROUND TASK SUPPORT:
For very complex tasks that should run async and notify user when done:
- Start response with: "BACKGROUND_TASK: <brief description>"
- Next line: User-facing message
- Bot will create background task and notify when complete

Examples of BACKGROUND tasks:
- "refactor the entire authentication system"
- "implement a new feature with tests"
- "build a Tetris game from scratch"
- "migrate database schema and update all models"

RESPONSE REQUIREMENTS:
- ALWAYS return a response. If uncertain, respond with best interpretation
- For questions/chat: Direct, conversational answer (2-3 sentences)
- For code tasks: Describe what you're spawning code_worker to do
- Keep it brief: Mobile users, max 3 sentences
- Use active voice: "Fixed X" not "X has been fixed"
- Use Task tool output to compose your response

Remember:
- input_method="{input_method}" ({'be permissive with voice errors' if input_method == 'voice' else 'exact text input'})
- When user references "you"/"your code"/"the bot": {bot_repository}
- Current workspace: {current_workspace or workspace_path}
- This bot is deeply personal - tailor responses to Matias' interests
{'- IMAGE ATTACHED: View at: ' + image_path if image_path else ''}

User query: {user_query}"""

    try:
        logger.info(f"Invoking orchestrator agent for: {user_query[:60]}...")

        # Invoke Claude Code in interactive mode
        # The orchestrator agent will automatically be available from .claude/agents/
        cmd = [
            "claude", "chat",
            "--model", "haiku",  # Fast responses for chat/routing (background tasks use Sonnet)
            "--permission-mode", "bypass-permissions"  # Auto-approve write operations
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
            cwd=bot_repository,  # Run from bot repo to load .claude/agents/orchestrator.md
            start_new_session=True  # Detach from parent process (fire-and-forget)
        )

        try:
            # Send prompt (non-blocking with timeout for stdin operations)
            if process.stdin:
                process.stdin.write(f"{prompt}\n".encode())
                await asyncio.wait_for(process.stdin.drain(), timeout=5)
                process.stdin.close()

            logger.info("Orchestrator subprocess started (detached, fire-and-forget)")

            # IMPORTANT: Do NOT call process.communicate() here!
            # That would block waiting for subprocess completion.
            # Instead, spawn a background task to collect the response asynchronously.
            # This allows invoke_orchestrator() to return immediately (<100ms).

            # Spawn background task to handle response collection
            asyncio.create_task(_collect_orchestrator_response(process, user_query))

            # Return immediately - no waiting for Claude Code to finish
            # The real response will be collected asynchronously in background
            logger.debug("Returning immediately from orchestrator (response collected in background)")
            return "Processing your request..."

        except Exception as e:
            logger.error(f"Error starting orchestrator process: {e}")
            if process:
                process.kill()
            return None

    except Exception as e:
        logger.error(f"Error invoking orchestrator: {e}")
        return None


async def _collect_orchestrator_response(process, user_query: str) -> None:
    """
    Background task to collect orchestrator response asynchronously.

    This runs detached from the main request handling, allowing the HTTP
    response to return immediately while we collect the orchestrator output.

    Args:
        process: The subprocess running Claude Code
        user_query: Original user query for logging
    """
    try:
        # Now we can wait for the full response without blocking the bot
        stdout, stderr = await process.communicate()

        output = stdout.decode().strip()

        if stderr:
            error_msg = stderr.decode().strip()
            if error_msg and not error_msg.startswith("Loading"):
                logger.warning(f"Orchestrator stderr: {error_msg}")

        if not output:
            logger.error("Empty output from orchestrator")
            return

        logger.info(f"Orchestrator response collected: {output[:100]}...")

        # Process background tasks if needed
        if output.startswith("BACKGROUND_TASK:"):
            logger.info("Background task detected in orchestrator response")
            # This would be handled by the background task system in main.py

    except Exception as e:
        logger.error(f"Error collecting orchestrator response: {e}", exc_info=True)
    finally:
        # Ensure process is cleaned up
        try:
            if process.returncode is None:
                process.kill()
        except:
            pass
