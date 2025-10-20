"""
Task tracking system for background operations
Phase 3-4: Orchestrator & worker task management
Now using SQLite for better performance and querying
"""

import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from database import Database

logger = logging.getLogger(__name__)


def is_process_alive(pid: int) -> bool:
    """Check if process with given PID is still running"""
    if pid is None:
        return False

    try:
        # Send signal 0 - checks if process exists without killing it
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@dataclass
class Task:
    """Background task"""

    task_id: str
    user_id: int
    description: str
    status: str  # 'pending', 'running', 'completed', 'failed', 'stopped'
    created_at: str
    updated_at: str
    model: str  # 'haiku', 'sonnet'
    workspace: str  # Repository/workspace path
    agent_type: str = "code_agent"  # 'code_agent', 'frontend_agent', 'research_agent', etc.
    result: str | None = None
    error: str | None = None
    pid: int | None = None  # Process ID for running tasks
    activity_log: list[dict] | None = None  # Activity/progress log with timestamps

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        # Ensure activity_log exists (for backwards compatibility)
        if "activity_log" not in data:
            data["activity_log"] = []
        # Ensure agent_type exists (for backwards compatibility with old tasks)
        if "agent_type" not in data:
            data["agent_type"] = "code_agent"
        return cls(**data)

    def add_activity(self, message: str, output_lines: int | None = None):
        """Add activity entry to log"""
        if self.activity_log is None:
            self.activity_log = []

        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
        }
        if output_lines is not None:
            entry["output_lines"] = output_lines

        self.activity_log.append(entry)

    def get_latest_activity(self, limit: int = 5) -> list[dict]:
        """Get latest activity entries"""
        if not self.activity_log:
            return []
        return self.activity_log[-limit:]


class TaskManager:
    """Manages background tasks using SQLite"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        # Initialize SQLite database
        db_path = self.data_dir / "agentlab.db"
        self.db = Database(str(db_path))

        # Check running tasks - mark as stopped if process died
        self._check_running_tasks()

        # Get task count for logging
        stats = self.db.get_database_stats()
        logger.info(f"TaskManager initialized with {stats['tasks']} tasks")

    def _check_running_tasks(self):
        """Check running tasks on startup - mark as stopped if process died"""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT task_id, pid FROM tasks WHERE status = 'running'")
        running_tasks = cursor.fetchall()

        if running_tasks:
            for row in running_tasks:
                task_id, pid = row
                if pid and is_process_alive(pid):
                    # Task survived restart! Process still running
                    logger.info(f"Task {task_id} (PID {pid}) still running after restart")
                else:
                    # Process died (or no PID tracked) - mark as stopped
                    self.db.update_task(task_id, status="stopped", error="Task stopped due to bot restart")
                    logger.warning(f"Marked stopped task {task_id}")

    def reload_tasks(self):
        """
        Reload tasks - no-op for SQLite backend since queries are always fresh.
        Kept for API compatibility.
        """
        logger.debug("reload_tasks() called - no-op for SQLite backend")

    def create_task(
        self, user_id: int, description: str, workspace: str, model: str = "sonnet", agent_type: str = "code_agent"
    ) -> Task:
        """Create a new task"""
        task_id = str(uuid.uuid4())[:6]

        # Create in database
        task_dict = self.db.create_task(
            task_id=task_id,
            user_id=user_id,
            description=description,
            workspace=workspace,
            model=model,
            agent_type=agent_type,
        )

        logger.info(f"Created {agent_type} task {task_id} for user {user_id} in {workspace}: {description}")
        return Task.from_dict(task_dict)

    def update_task(
        self,
        task_id: str,
        status: str | None = None,
        result: str | None = None,
        error: str | None = None,
        pid: int | None = None,
    ):
        """Update task status"""
        success = self.db.update_task(
            task_id=task_id,
            status=status,
            result=result,
            error=error,
            pid=pid,
        )

        if not success:
            logger.error(f"Task {task_id} not found")
            return

        logger.info(f"Updated task {task_id}: status={status}, pid={pid}")

    def log_activity(self, task_id: str, message: str, output_lines: int | None = None, save: bool = True):
        """Log activity for a task"""
        success = self.db.add_activity(task_id, message, output_lines)

        if not success:
            logger.error(f"Task {task_id} not found")
            return

        logger.debug(f"Task {task_id} activity: {message}")

    def get_task(self, task_id: str) -> Task | None:
        """Get task by ID"""
        task_dict = self.db.get_task(task_id)
        return Task.from_dict(task_dict) if task_dict else None

    def get_user_tasks(self, user_id: int, status: str | None = None, limit: int = 10) -> list[Task]:
        """Get tasks for a user"""
        task_dicts = self.db.get_user_tasks(user_id, status, limit)
        return [Task.from_dict(t) for t in task_dicts]

    def get_active_tasks(self, user_id: int) -> list[Task]:
        """Get active (pending/running) tasks for user"""
        task_dicts = self.db.get_active_tasks(user_id)
        return [Task.from_dict(t) for t in task_dicts]

    def retry_task(self, task_id: str) -> Task | None:
        """
        Retry a failed or stopped task by creating a new task with the same parameters.
        Returns the new task if successful, None if task not found or not retryable.
        """
        original_task = self.get_task(task_id)

        if not original_task:
            logger.error(f"Task {task_id} not found")
            return None

        if original_task.status not in ["failed", "stopped"]:
            logger.warning(f"Task {task_id} is not retryable (status: {original_task.status})")
            return None

        # Create new task with same parameters
        new_task = self.create_task(
            user_id=original_task.user_id,
            description=original_task.description,
            workspace=original_task.workspace,
            model=original_task.model,
            agent_type=original_task.agent_type,
        )

        logger.info(f"Created retry task {new_task.task_id} for {original_task.status} task {task_id}")
        return new_task

    def get_failed_tasks(self, user_id: int, limit: int = 10) -> list[Task]:
        """Get failed tasks for a user"""
        task_dicts = self.db.get_failed_tasks(user_id, limit)
        return [Task.from_dict(t) for t in task_dicts]

    def clear_old_failed_tasks(self, user_id: int, older_than_hours: int = 24):
        """
        Clear old failed tasks for a user to prevent clutter in status display.
        Only removes tasks older than the specified hours.

        Args:
            user_id: User ID to clear tasks for
            older_than_hours: Only clear tasks older than this many hours (default: 24)

        Returns:
            Number of tasks cleared
        """
        cleared_count = self.db.clear_old_failed_tasks(user_id, older_than_hours)
        return cleared_count

    def mark_all_running_as_stopped(self):
        """
        Mark all running tasks as stopped during shutdown.
        This preserves task state so they can be retried on restart.

        Returns:
            Number of tasks marked as stopped
        """
        stopped_count = self.db.mark_all_running_as_stopped()
        return stopped_count

    def get_stopped_tasks(self, user_id: int | None = None, limit: int = 100) -> list[Task]:
        """
        Get stopped tasks, optionally filtered by user.

        Args:
            user_id: Optional user ID to filter by
            limit: Maximum number of tasks to return

        Returns:
            List of stopped tasks
        """
        task_dicts = self.db.get_stopped_tasks(user_id, limit)
        return [Task.from_dict(t) for t in task_dicts]

    def cleanup_stale_pending_tasks(self, max_age_hours: int = 1) -> int:
        """
        Clean up stale pending tasks that have been waiting too long.
        Marks them as failed to prevent cluttering the active tasks list.

        Args:
            max_age_hours: Maximum age in hours before a pending task is considered stale

        Returns:
            Number of tasks cleaned up
        """
        cleaned_count = self.db.cleanup_stale_pending_tasks(max_age_hours)
        return cleaned_count

    def stop_task(self, task_id: str) -> tuple[bool, str]:
        """
        Stop a running task by killing its process.

        Args:
            task_id: Task ID to stop

        Returns:
            (success, message) tuple
        """
        task = self.get_task(task_id)

        if not task:
            return False, f"Task #{task_id} not found."

        if task.status not in ["pending", "running"]:
            return False, f"Task #{task_id} is not running (status: {task.status})."

        # Try to kill the process if we have a PID
        if task.pid and is_process_alive(task.pid):
            try:
                os.kill(task.pid, 9)  # SIGKILL - forcefully terminate
                logger.info(f"Killed process {task.pid} for task {task_id}")
            except OSError as e:
                logger.error(f"Failed to kill process {task.pid}: {e}")
                return False, f"Failed to stop task #{task_id}: {e}"

        # Update task status
        self.db.update_task(task_id, status="stopped", error="Task stopped by user")

        logger.info(f"Stopped task {task_id} (was {task.status})")
        return True, f"Task #{task_id} stopped successfully."

    def retry_all_stopped_tasks(self) -> list[Task]:
        """
        Retry all stopped tasks on startup.
        Creates new tasks for all stopped tasks across all users.

        Returns:
            List of new tasks created
        """
        stopped_tasks = self.get_stopped_tasks()
        new_tasks = []

        for stopped_task in stopped_tasks:
            # Skip repetitive/test tasks that shouldn't be auto-retried
            if any(skip_pattern in stopped_task.description for skip_pattern in ["Find todos", "test", "Test"]):
                logger.info(f"Skipping auto-retry of task {stopped_task.task_id}: {stopped_task.description[:50]}")
                continue

            new_task = self.create_task(
                user_id=stopped_task.user_id,
                description=stopped_task.description,
                workspace=stopped_task.workspace,
                model=stopped_task.model,
                agent_type=stopped_task.agent_type,
            )
            new_tasks.append(new_task)
            logger.info(f"Auto-retrying stopped task {stopped_task.task_id} as {new_task.task_id}")

        if new_tasks:
            logger.info(f"Auto-retried {len(new_tasks)} stopped tasks on startup")

        return new_tasks

    def stop_all_tasks(self, user_id: int) -> tuple[int, int, list[str]]:
        """
        Stop all active tasks for a user.

        Args:
            user_id: User ID whose tasks to stop

        Returns:
            (stopped_count, failed_count, failed_task_ids) tuple
        """
        active_tasks = self.get_active_tasks(user_id)

        if not active_tasks:
            return 0, 0, []

        stopped_count = 0
        failed_count = 0
        failed_task_ids = []

        for task in active_tasks:
            success, message = self.stop_task(task.task_id)
            if success:
                stopped_count += 1
            else:
                failed_count += 1
                failed_task_ids.append(task.task_id)

        logger.info(f"Stopped {stopped_count}/{len(active_tasks)} tasks for user {user_id}")

        return stopped_count, failed_count, failed_task_ids
