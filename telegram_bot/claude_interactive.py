"""
Interactive Claude Code session handler
Phase 3-4: Full tool access for code operations
Enhanced with workflow enforcement for testing and commits
"""

import asyncio
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from workflow_enforcer import WorkflowEnforcer

logger = logging.getLogger(__name__)


class ClaudeInteractiveSession:
    """
    Interactive Claude Code session with full tool access
    Unlike non-interactive mode, this can use Read, Write, Edit, Bash, etc.
    """

    def __init__(self, workspace: Path, model: str = "sonnet", enforce_workflow: bool = True):
        self.workspace = workspace
        self.model = model
        self.process: subprocess.Popen | None = None
        self.task_id: str | None = None
        self.enforce_workflow = enforce_workflow
        self.workflow_enforcer = WorkflowEnforcer(workspace) if enforce_workflow else None

    async def start(self, task_id: str):
        """Start interactive Claude session"""
        self.task_id = task_id

        try:
            # Start Claude in interactive mode with auto-approval for background tasks
            cmd = [
                "claude",
                "chat",
                "--model",
                self.model,
                "--permission-mode",
                "bypassPermissions",  # Auto-approve file operations
            ]

            logger.info(f"Starting Claude interactive session for task {task_id}")
            logger.info(f"Command: {' '.join(cmd)}")
            logger.info(f"Workspace: {self.workspace}")

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            logger.info(f"Interactive session started (PID: {self.process.pid})")
            return True

        except Exception as e:
            logger.error(f"Failed to start interactive session: {e}")
            return False

    async def send_message(self, message: str, timeout: int = 300) -> str | None:
        """Send message to Claude and get response

        Note: This closes stdin after sending the message, which causes the claude chat
        process to execute and exit. This is intentional for background task execution.
        """
        if not self.process or not self.process.stdin:
            logger.error("No active session")
            return None

        try:
            # Send message and close stdin to trigger execution
            self.process.stdin.write(f"{message}\n".encode())
            await self.process.stdin.drain()
            self.process.stdin.close()  # Close stdin to signal we're done (synchronous, no await)
            await self.process.stdin.wait_closed()  # Wait for stdin to actually close
            logger.debug(f"Sent message to Claude and closed stdin (task {self.task_id})")

            # Wait for process to complete with timeout
            try:
                stdout, stderr = await asyncio.wait_for(self.process.communicate(), timeout=timeout)

                response = stdout.decode().strip()

                if stderr:
                    error_msg = stderr.decode().strip()
                    if error_msg:
                        logger.debug(f"Claude stderr (task {self.task_id}): {error_msg}")

                if response:
                    logger.debug(f"Received response from Claude (task {self.task_id}): {len(response)} chars")
                    return response
                else:
                    logger.warning(f"Empty response from Claude (task {self.task_id})")
                    return None

            except TimeoutError:
                logger.error(f"Response timeout after {timeout}s (task {self.task_id})")
                await self.terminate()
                return None

        except Exception as e:
            logger.error(f"Error sending message (task {self.task_id}): {e}")
            await self.terminate()
            return None

    async def terminate(self):
        """Terminate the session"""
        if self.process:
            try:
                # Check if process is still running
                if self.process.returncode is None:
                    self.process.terminate()
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                    logger.info(f"Session terminated for task {self.task_id}")
                else:
                    logger.info(
                        f"Session already exited for task {self.task_id} (returncode: {self.process.returncode})"
                    )
            except TimeoutError:
                self.process.kill()
                logger.warning(f"Session killed (timeout) for task {self.task_id}")
            except ProcessLookupError:
                # Process already terminated
                logger.debug(f"Session process already terminated for task {self.task_id}")
            except Exception as e:
                error_msg = str(e) if str(e) else type(e).__name__
                logger.error(f"Error terminating session: {error_msg}")

            self.process = None

    async def execute_task(self, task_description: str, bot_repo_path: str | None = None) -> tuple[bool, str]:
        """
        Execute a coding task with workflow enforcement
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

            # Add workflow enforcement context
            workflow_context = ""
            if self.enforce_workflow and self.workflow_enforcer:
                workflow_context = self.workflow_enforcer.get_workflow_prompt_context()

            # Send task with clear instructions
            prompt = f"""{bot_context}

User request: {task_description}

Working directory: {self.workspace}
You have full access to tools (Read, Write, Edit, Glob, Grep, Bash, etc.).

{workflow_context}

Complete the task and provide a concise summary of what you did."""

            # Execute
            response = await self.send_message(prompt)

            # Cleanup
            await self.terminate()

            if not response:
                return False, "No response from Claude"

            # Enforce workflow if enabled
            workflow_result = ""
            if self.enforce_workflow and self.workflow_enforcer:
                logger.info(f"Enforcing workflow for task {self.task_id}")
                success, workflow_msg = self.workflow_enforcer.enforce_workflow(task_description)

                workflow_result = f"\n\n{'='*60}\nWORKFLOW ENFORCEMENT\n{'='*60}\n{workflow_msg}\n"

                if not success:
                    logger.warning(f"Workflow enforcement failed for task {self.task_id}")
                    return False, response + workflow_result
                else:
                    logger.info(f"Workflow enforcement passed for task {self.task_id}")

            return True, response + workflow_result

        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await self.terminate()
            return False, f"Error: {str(e)}"


class ClaudeSessionPool:
    """Pool of Claude sessions for concurrent task execution"""

    def __init__(self, max_concurrent: int = 3, enforce_workflow: bool = True):
        self.max_concurrent = max_concurrent
        self.enforce_workflow = enforce_workflow
        self.active_sessions: dict[str, ClaudeInteractiveSession] = {}

    async def execute_task(
        self,
        task_id: str,
        description: str,
        workspace: Path,
        bot_repo_path: str | None = None,
        model: str = "sonnet",
        pid_callback: Callable[[int], None] | None = None,
    ) -> tuple[bool, str, int | None]:
        """Execute a task using session pool

        Args:
            pid_callback: Optional callback function called with PID when process starts
                         Format: pid_callback(pid: int)

        Returns:
            (success, result, pid) - pid is the Claude process ID if available
        """

        # Wait if at capacity
        while len(self.active_sessions) >= self.max_concurrent:
            await asyncio.sleep(1)

        # Create session with specified workspace and workflow enforcement
        session = ClaudeInteractiveSession(workspace, model, enforce_workflow=self.enforce_workflow)
        session.task_id = task_id
        self.active_sessions[task_id] = session

        try:
            # Start session first to get PID
            if not await session.start(task_id):
                return False, "Failed to start Claude session", None

            # Call callback with PID immediately after process starts
            pid = session.process.pid if session.process else None
            if pid and pid_callback:
                try:
                    pid_callback(pid)
                except Exception as e:
                    logger.error(f"Error in PID callback: {e}")

            # Build context and execute task
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

            # Add workflow enforcement context
            workflow_context = ""
            if self.enforce_workflow and session.workflow_enforcer:
                workflow_context = session.workflow_enforcer.get_workflow_prompt_context()

            prompt = f"""{bot_context}

User request: {description}

Working directory: {workspace}
You have full access to tools (Read, Write, Edit, Glob, Grep, Bash, etc.).

{workflow_context}

Complete the task and provide a concise summary of what you did."""

            # Execute task
            response = await session.send_message(prompt)

            # Cleanup
            await session.terminate()

            if not response:
                return False, "No response from Claude", pid

            # Enforce workflow if enabled
            workflow_result = ""
            if self.enforce_workflow and session.workflow_enforcer:
                logger.info(f"Enforcing workflow for task {task_id}")
                success, workflow_msg = session.workflow_enforcer.enforce_workflow(description)

                workflow_result = f"\n\n{'='*60}\nWORKFLOW ENFORCEMENT\n{'='*60}\n{workflow_msg}\n"

                if not success:
                    logger.warning(f"Workflow enforcement failed for task {task_id}")
                    return False, response + workflow_result, pid
                else:
                    logger.info(f"Workflow enforcement passed for task {task_id}")

            return True, response + workflow_result, pid

        except Exception as e:
            logger.error(f"Task execution error: {e}")
            await session.terminate()
            return False, f"Error: {str(e)}", None

        finally:
            # Cleanup
            if task_id in self.active_sessions:
                del self.active_sessions[task_id]

    async def terminate_all(self):
        """Terminate all active sessions"""
        for session in self.active_sessions.values():
            await session.terminate()
        self.active_sessions.clear()
