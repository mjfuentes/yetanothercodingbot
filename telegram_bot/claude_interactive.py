"""
Interactive Claude Code session handler
Phase 3-4: Full tool access for code operations
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ClaudeInteractiveSession:
    """
    Interactive Claude Code session with full tool access
    Unlike non-interactive mode, this can use Read, Write, Edit, Bash, etc.
    """

    def __init__(self, workspace: Path, model: str = "sonnet"):
        self.workspace = workspace
        self.model = model
        self.process: Optional[subprocess.Popen] = None
        self.task_id: Optional[str] = None

    async def start(self, task_id: str):
        """Start interactive Claude session"""
        self.task_id = task_id

        try:
            # Start Claude in interactive mode
            cmd = [
                "claude",
                "chat",
                "--model", self.model,
                "--no-stream"  # Get complete responses
            ]

            logger.info(f"Starting Claude interactive session for task {task_id}")
            logger.info(f"Command: {' '.join(cmd)}")
            logger.info(f"Workspace: {self.workspace}")

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace)
            )

            logger.info(f"Interactive session started (PID: {self.process.pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to start interactive session: {e}")
            return False

    async def send_message(self, message: str, timeout: int = 300) -> Optional[str]:
        """Send message to Claude and get response"""
        if not self.process or not self.process.stdin:
            logger.error("No active session")
            return None

        try:
            # Send message
            self.process.stdin.write(f"{message}\n".encode())
            await self.process.stdin.drain()

            # Read response with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    self.process.communicate(),
                    timeout=timeout
                )

                response = stdout.decode().strip()

                if stderr:
                    error_msg = stderr.decode().strip()
                    if error_msg:
                        logger.warning(f"Claude stderr: {error_msg}")

                return response

            except asyncio.TimeoutError:
                logger.error(f"Response timeout after {timeout}s")
                await self.terminate()
                return None

        except Exception as e:
            logger.error(f"Error sending message: {e}")
            await self.terminate()
            return None

    async def terminate(self):
        """Terminate the session"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
                logger.info(f"Session terminated for task {self.task_id}")
            except asyncio.TimeoutError:
                self.process.kill()
                logger.warning(f"Session killed (timeout) for task {self.task_id}")
            except Exception as e:
                logger.error(f"Error terminating session: {e}")

            self.process = None

    async def execute_task(self, task_description: str, bot_repo_path: Optional[str] = None) -> tuple[bool, str]:
        """
        Execute a coding task
        Returns: (success, result_message)
        """
        try:
            # Start session
            if not await self.start(self.task_id or "unknown"):
                return False, "Failed to start Claude session"

            # Build context about bot's location
            bot_context = ""
            if bot_repo_path:
                bot_context = f"""
CONTEXT: You are a Telegram bot powered by Claude Code. When users say "you", "your code", or "the bot", they're referring to your own codebase.

Your code lives at: {bot_repo_path}
Structure:
- telegram_bot/main.py - Bot entry point, message handlers, routing logic
- telegram_bot/session.py - Session & conversation history management
- telegram_bot/tasks.py - Background task tracking system
- telegram_bot/claude_interactive.py - Interactive Claude sessions (YOU are being invoked from here!)
- data/ - Persistent storage (sessions.json, tasks.json)
- logs/ - Application logs

Use your natural language understanding to determine if the user wants you to modify your own code or work on a different project."""

            # Send task with clear instructions
            prompt = f"""{bot_context}

User request: {task_description}

Working directory: {self.workspace}
You have full access to tools (Read, Write, Edit, Glob, Grep, Bash, etc.).

Complete the task and provide a concise summary of what you did."""

            # Execute
            response = await self.send_message(prompt)

            # Cleanup
            await self.terminate()

            if response:
                return True, response
            else:
                return False, "No response from Claude"

        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await self.terminate()
            return False, f"Error: {str(e)}"


class ClaudeSessionPool:
    """Pool of Claude sessions for concurrent task execution"""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.active_sessions: dict[str, ClaudeInteractiveSession] = {}

    async def execute_task(
        self,
        task_id: str,
        description: str,
        workspace: Path,
        bot_repo_path: Optional[str] = None,
        model: str = "sonnet"
    ) -> tuple[bool, str]:
        """Execute a task using session pool"""

        # Wait if at capacity
        while len(self.active_sessions) >= self.max_concurrent:
            await asyncio.sleep(1)

        # Create session with specified workspace
        session = ClaudeInteractiveSession(workspace, model)
        session.task_id = task_id
        self.active_sessions[task_id] = session

        try:
            # Execute with bot context
            success, result = await session.execute_task(description, bot_repo_path)
            return success, result

        finally:
            # Cleanup
            if task_id in self.active_sessions:
                del self.active_sessions[task_id]

    async def terminate_all(self):
        """Terminate all active sessions"""
        for session in self.active_sessions.values():
            await session.terminate()
        self.active_sessions.clear()
