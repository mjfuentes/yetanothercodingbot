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
    timeout: int = 300
) -> Optional[str]:
    """
    Invoke orchestrator agent via Claude Code

    Returns:
        User-facing message string, or None on error
    """

    # Discover available repositories
    available_repos = discover_repositories(workspace_path)

    # Build context for orchestrator
    context = {
        "user_query": user_query,
        "input_method": input_method,
        "conversation_history": conversation_history[-5:],  # Last 5 messages
        "current_workspace": current_workspace or workspace_path,
        "available_repositories": available_repos,
        "bot_repository": bot_repository,
        "active_tasks": []  # TODO: populate from TaskManager if needed
    }

    # Format prompt with context
    prompt = f"""CONTEXT:
{json.dumps(context, indent=2)}

Handle this user query. You can respond directly, or spawn a code_worker agent for code modifications.

IMPORTANT CAPABILITIES:
- You have Glob, Grep, and Read tools that work with ABSOLUTE PATHS
- You can access ANY repository in available_repositories by using absolute paths
- Example: To list files in /Users/matifuentes/Workspace/groovetherapy, use: Glob with pattern="*" and path="/Users/matifuentes/Workspace/groovetherapy"
- Don't say you can't access repos - just use the tools with absolute paths!

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
            "--model", "sonnet",
            "--permission-mode", "bypassPermissions"  # Auto-approve write operations
        ]

        logger.debug(f"Command: {' '.join(cmd)}")
        logger.debug(f"Working directory: {bot_repository}")

        # Run from workspace root to access all repos
        # Agent config from bot_repository/.claude/agents won't be available,
        # so we need to pass agent instructions inline via prompt
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_path  # Run from workspace root to access all projects
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
            return output

        except asyncio.TimeoutError:
            logger.error(f"Orchestrator timeout after {timeout}s")
            if process:
                process.kill()
            return None

    except Exception as e:
        logger.error(f"Error invoking orchestrator: {e}")
        return None
