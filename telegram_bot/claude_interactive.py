"""
Interactive Claude Code session handler
Phase 3-4: Full tool access for code operations
Enhanced with workflow enforcement for testing and commits
Enhanced with tool usage tracking via hooks
Enhanced with security: prompt injection prevention and input sanitization
"""

import asyncio
import html
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from tool_usage_tracker import ToolUsageTracker
from workflow_enforcer import WorkflowEnforcer

logger = logging.getLogger(__name__)


def sanitize_prompt_content(text: str) -> str:
    """
    Sanitize text for safe inclusion in prompts sent to Claude Code CLI.
    Prevents prompt injection via special characters and control sequences.

    Args:
        text: Raw user input or untrusted content

    Returns:
        Escaped text safe for prompt inclusion
    """
    if not text:
        return ""

    # HTML escape XML special characters
    escaped = html.escape(text, quote=True)

    # Remove control characters that could break prompt structure
    escaped = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", escaped)

    # Check for and remove potential injection patterns
    dangerous_patterns = [
        r"</\w+>",  # Closing XML tags
        r"<\w+[^>]*>",  # Opening XML tags
        r"<bot_context>",  # Structural tags
        r"<request>",
        r"<environment>",
        r"<instructions>",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, escaped, re.IGNORECASE):
            escaped = re.sub(pattern, "", escaped, flags=re.IGNORECASE)
            logger.warning(f"Removed dangerous pattern from prompt: {pattern}")

    return escaped


def validate_task_description(description: str) -> tuple[bool, str | None]:
    """
    Validate task description for security issues.

    Args:
        description: Task description to validate

    Returns:
        (is_valid, error_message) - False if invalid with error message
    """
    if not description or not description.strip():
        return False, "Empty task description"

    # Check length
    if len(description) > 5000:
        return False, "Task description too long (max 5000 characters)"

    # Check for injection patterns
    injection_patterns = [
        (r"ignore (all |previous )?instructions?", "Instruction override attempt"),
        (r"system:?\s*", "System prompt manipulation"),
        (r"<\|im_start\|>", "Prompt format injection"),
    ]

    desc_lower = description.lower()
    for pattern, reason in injection_patterns:
        if re.search(pattern, desc_lower):
            logger.warning(f"Task validation failed: {reason} in: {description[:100]}")
            return False, f"Invalid task description: {reason}"

    return True, None


class PromptBuilder:
    """
    Reusable prompt engineering components for Claude interactions
    Optimized with XML structure for clarity and token efficiency
    """

    @staticmethod
    def build_bot_context(bot_repo_path: str) -> str:
        """Build context about the bot's codebase with XML structure"""
        # Security: Sanitize bot repo path
        safe_path = sanitize_prompt_content(bot_repo_path)

        return f"""<bot_context>
You are a Telegram bot powered by Claude Code. When users say "you", "your code", or "the bot", they mean YOUR codebase.

<structure>
Location: {safe_path}
telegram_bot/main.py - Entry point, handlers, routing
telegram_bot/session.py - Session & history mgmt
telegram_bot/tasks.py - Background task tracking
telegram_bot/claude_interactive.py - YOU are invoked from here
data/ - Persistent storage (sessions, tasks)
logs/ - Application logs
</structure>

Use NLU to determine: user's own code vs. modifying bot code.
</bot_context>"""

    @staticmethod
    def build_task_prompt(
        task_description: str,
        workspace: str | Path,
        bot_context: str = "",
        workflow_context: str = "",
    ) -> str:
        """
        Build complete task execution prompt with XML structure
        Optimized for token efficiency and clarity
        Security: Sanitizes all user inputs before inclusion
        """
        # Security: Validate and sanitize task description
        is_valid, error_msg = validate_task_description(task_description)
        if not is_valid:
            logger.error(f"Invalid task description: {error_msg}")
            # Return safe error message - don't expose validation details
            task_description = "Invalid task description provided"

        safe_task = sanitize_prompt_content(task_description)
        safe_workspace = sanitize_prompt_content(str(workspace))

        parts = []

        # Add bot context (already XML-formatted and sanitized)
        if bot_context:
            parts.append(bot_context)
            parts.append("")

        # User request (XML tag) - sanitized
        parts.append(f"<request>{safe_task}</request>")
        parts.append("")

        # Environment info (XML structure) - sanitized
        parts.append("<environment>")
        parts.append(f"working_directory: {safe_workspace}")
        parts.append("tools_available: Read, Write, Edit, Glob, Grep, Bash")
        parts.append("</environment>")
        parts.append("")

        # Workflow context if provided (trusted internal content)
        if workflow_context:
            parts.append(workflow_context)
            parts.append("")

        # Completion instructions (XML tag for clarity)
        parts.append("<instructions>")
        parts.append("Complete the task and provide a concise summary.")
        parts.append("</instructions>")

        return "\n".join(parts)


class ClaudeInteractiveSession:
    """
    Interactive Claude Code session with full tool access
    Unlike non-interactive mode, this can use Read, Write, Edit, Bash, etc.
    """

    def __init__(
        self,
        workspace: Path,
        model: str = "sonnet",
        enforce_workflow: bool = True,
        usage_tracker: ToolUsageTracker | None = None,
        agent: str | None = None,
    ):
        self.workspace = workspace
        self.model = model
        self.agent = agent
        self.process: subprocess.Popen | None = None
        self.task_id: str | None = None
        self.enforce_workflow = enforce_workflow
        self.workflow_enforcer = WorkflowEnforcer(workspace) if enforce_workflow else None
        self.usage_tracker = usage_tracker

    async def start(self, task_id: str):
        """Start interactive Claude session"""
        self.task_id = task_id

        try:
            # Record agent status change
            if self.usage_tracker:
                self.usage_tracker.record_status_change(task_id, "started", "Starting Claude interactive session")

            # Start Claude in interactive mode with auto-approval for background tasks
            # Generate deterministic UUID from task_id for session tracking
            import uuid

            # Create UUID5 from task_id (deterministic, valid UUID format)
            task_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"agentlab.task.{task_id}"))

            cmd = [
                "claude",
                "chat",
                "--model",
                self.model,
                "--permission-mode",
                "bypassPermissions",  # Auto-approve file operations
                "--session-id",
                task_uuid,  # Use deterministic UUID based on task_id
            ]

            # Add agent flag if specified
            if self.agent:
                cmd.extend(["--agents", self.agent])

                # Enforce tool restrictions based on agent type
                # orchestrator.md specifies "tools: Task" - enforce this restriction
                if self.agent == "orchestrator":
                    cmd.extend(["--allowed-tools", "Task", "TodoWrite"])
                # research_agent.md specifies read-only tools
                elif self.agent == "research_agent":
                    cmd.extend(["--allowed-tools", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"])

            logger.info(f"Starting Claude interactive session for task {task_id}")
            logger.info(f"Command: {' '.join(cmd)}")
            logger.info(f"Workspace: {self.workspace}")
            if self.agent:
                logger.info(f"Agent: {self.agent}")

            # Set SESSION_ID environment variable to match task_id for hook logging
            # (Claude Code hooks can access this to organize logs by task)
            env = os.environ.copy()
            env["SESSION_ID"] = task_id

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env=env,
            )

            logger.info(f"Interactive session started (PID: {self.process.pid})")

            # Record successful start with PID
            if self.usage_tracker:
                self.usage_tracker.record_status_change(
                    task_id,
                    "started",
                    f"Session started with PID {self.process.pid}",
                    metadata={"pid": self.process.pid},
                )

            return True

        except Exception as e:
            logger.error(f"Failed to start interactive session: {e}")

            # Record failure
            if self.usage_tracker:
                self.usage_tracker.record_status_change(task_id, "failed", f"Failed to start session: {str(e)}")

            return False

    async def send_message_with_streaming(
        self,
        message: str,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> str | None:
        """Send message to Claude and get response with streaming updates

        Args:
            message: The message to send to Claude
            progress_callback: Optional callback for progress updates. Called with (status_message, elapsed_seconds)

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

            # Stream output
            start_time = time.time()
            stdout_chunks = []
            stderr_chunks = []

            async def read_stream(stream, chunks, stream_name):
                """Read from stream line by line"""
                while True:
                    try:
                        line = await stream.readline()
                        if not line:
                            break
                        decoded = line.decode()
                        chunks.append(decoded)
                        logger.debug(f"Claude {stream_name} (task {self.task_id}): {decoded.rstrip()}")
                    except Exception as e:
                        logger.error(f"Error reading {stream_name}: {e}")
                        break

            # Start reading both streams
            stdout_task = asyncio.create_task(read_stream(self.process.stdout, stdout_chunks, "stdout"))
            stderr_task = asyncio.create_task(read_stream(self.process.stderr, stderr_chunks, "stderr"))

            # Wait for both streams to finish
            await asyncio.gather(stdout_task, stderr_task)

            # Wait for process to exit
            await self.process.wait()

            # Combine output
            response = "".join(stdout_chunks).strip()
            stderr_output = "".join(stderr_chunks).strip()

            elapsed = int(time.time() - start_time)

            if stderr_output:
                logger.debug(f"Claude stderr (task {self.task_id}): {stderr_output}")

            if response:
                logger.info(f"Received response from Claude (task {self.task_id}): {len(response)} chars in {elapsed}s")
                if progress_callback:
                    progress_callback(f"Completed in {elapsed}s", elapsed)
                return response
            else:
                logger.warning(f"Empty response from Claude (task {self.task_id}) after {elapsed}s")
                if progress_callback:
                    progress_callback(f"Warning: Empty response after {elapsed}s", elapsed)
                return None

        except Exception as e:
            logger.error(f"Error sending message (task {self.task_id}): {e}")
            await self.terminate()
            return None

    async def send_message(self, message: str) -> str | None:
        """Send message to Claude and get response (backward compatible version without streaming)"""
        return await self.send_message_with_streaming(message, progress_callback=None)

    async def terminate(self):
        """Terminate the session"""
        if self.process:
            try:
                # Check if process is still running
                if self.process.returncode is None:
                    self.process.terminate()
                    await self.process.wait()
                    logger.info(f"Session terminated for task {self.task_id}")
                else:
                    logger.info(
                        f"Session already exited for task {self.task_id} (returncode: {self.process.returncode})"
                    )
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

            # Build bot context if needed
            bot_context = PromptBuilder.build_bot_context(bot_repo_path) if bot_repo_path else ""

            # Get workflow enforcement context if enabled
            workflow_context = ""
            if self.enforce_workflow and self.workflow_enforcer:
                workflow_context = self.workflow_enforcer.get_workflow_prompt_context()

            # Build and send prompt
            prompt = PromptBuilder.build_task_prompt(
                task_description=task_description,
                workspace=self.workspace,
                bot_context=bot_context,
                workflow_context=workflow_context,
            )

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

    def __init__(
        self, max_concurrent: int = 3, enforce_workflow: bool = True, usage_tracker: ToolUsageTracker | None = None
    ):
        self.max_concurrent = max_concurrent
        self.enforce_workflow = enforce_workflow
        self.usage_tracker = usage_tracker
        self.active_sessions: dict[str, ClaudeInteractiveSession] = {}

    async def execute_task(
        self,
        task_id: str,
        description: str,
        workspace: Path,
        bot_repo_path: str | None = None,
        model: str = "sonnet",
        agent: str | None = None,
        pid_callback: Callable[[int], None] | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> tuple[bool, str, int | None]:
        """Execute a task using session pool

        Args:
            agent: Optional agent name to use (e.g., 'frontend_agent', 'code_agent')
            pid_callback: Optional callback function called with PID when process starts
                         Format: pid_callback(pid: int)
            progress_callback: Optional callback for progress updates
                              Format: progress_callback(status_message: str, elapsed_seconds: int)

        Returns:
            (success, result, pid) - pid is the Claude process ID if available
        """

        # Wait if at capacity
        while len(self.active_sessions) >= self.max_concurrent:
            await asyncio.sleep(1)

        # Disable workflow enforcement for agents that only delegate (don't execute directly)
        # orchestrator: Only uses Task tool to spawn other agents, doesn't make code changes
        # research_agent: Read-only analysis, doesn't make code changes
        enforce_workflow_for_session = self.enforce_workflow and agent not in ["orchestrator", "research_agent"]

        # Create session with specified workspace, workflow enforcement, and usage tracker
        session = ClaudeInteractiveSession(
            workspace,
            model,
            enforce_workflow=enforce_workflow_for_session,
            usage_tracker=self.usage_tracker,
            agent=agent,
        )
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
            bot_context = PromptBuilder.build_bot_context(bot_repo_path) if bot_repo_path else ""

            # Get workflow enforcement context if enabled
            workflow_context = ""
            if self.enforce_workflow and session.workflow_enforcer:
                workflow_context = session.workflow_enforcer.get_workflow_prompt_context()

            # Build prompt using PromptBuilder
            prompt = PromptBuilder.build_task_prompt(
                task_description=description,
                workspace=workspace,
                bot_context=bot_context,
                workflow_context=workflow_context,
            )

            # Execute task with streaming and progress updates
            response = await session.send_message_with_streaming(prompt, progress_callback=progress_callback)

            # Cleanup
            await session.terminate()

            # Check for empty or invalid response
            if not response:
                error_msg = "Claude produced no output. The task may have failed silently or timed out."
                logger.error(f"Task {task_id}: {error_msg}")
                if self.usage_tracker:
                    self.usage_tracker.record_status_change(task_id, "failed", error_msg)
                return False, error_msg, pid

            # Check if response is essentially empty (just whitespace or minimal content)
            if len(response.strip()) < 10:
                error_msg = f"Claude produced minimal output ({len(response)} chars): {response[:100]}"
                logger.warning(f"Task {task_id}: {error_msg}")
                if self.usage_tracker:
                    self.usage_tracker.record_status_change(task_id, "failed", "Minimal/empty output")
                return False, error_msg, pid

            # Enforce workflow if enabled
            workflow_result = ""
            if self.enforce_workflow and session.workflow_enforcer:
                logger.info(f"Enforcing workflow for task {task_id}")
                success, workflow_msg = session.workflow_enforcer.enforce_workflow(description)

                workflow_result = f"\n\n{'='*60}\nWORKFLOW ENFORCEMENT\n{'='*60}\n{workflow_msg}\n"

                if not success:
                    logger.warning(f"Workflow enforcement failed for task {task_id}")

                    # Record workflow failure
                    if self.usage_tracker:
                        self.usage_tracker.record_status_change(task_id, "failed", "Workflow enforcement failed")

                    return False, response + workflow_result, pid
                else:
                    logger.info(f"Workflow enforcement passed for task {task_id}")

                    # Record workflow success
                    if self.usage_tracker:
                        self.usage_tracker.record_status_change(
                            task_id, "completed", "Task completed with workflow enforcement"
                        )

            # Record completion
            if self.usage_tracker:
                self.usage_tracker.record_status_change(task_id, "completed", "Task completed successfully")

            return True, response + workflow_result, pid

        except Exception as e:
            logger.error(f"Task execution error: {e}")

            # Record failure
            if self.usage_tracker:
                self.usage_tracker.record_status_change(task_id, "failed", f"Task execution error: {str(e)}")

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
