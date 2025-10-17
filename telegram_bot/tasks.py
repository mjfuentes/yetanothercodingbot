"""
Task tracking system for background operations
Phase 3-4: Orchestrator & worker task management
"""

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

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
    status: str  # 'pending', 'in_progress', 'completed', 'failed', 'stopped'
    created_at: str
    updated_at: str
    model: str  # 'haiku', 'sonnet'
    workspace: str  # Repository/workspace path
    result: str | None = None
    error: str | None = None
    pid: int | None = None  # Process ID for running tasks

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)


class TaskManager:
    """Manages background tasks"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.tasks_file = self.data_dir / "tasks.json"
        self.tasks: dict[str, Task] = {}

        # Load existing tasks
        self._load_tasks()

        logger.info(f"TaskManager initialized with {len(self.tasks)} tasks")

    def _load_tasks(self):
        """Load tasks from disk"""
        if not self.tasks_file.exists():
            return

        try:
            with open(self.tasks_file) as f:
                data = json.load(f)
                for task_id, task_data in data.items():
                    self.tasks[task_id] = Task.from_dict(task_data)

            logger.info(f"Loaded {len(self.tasks)} tasks from disk")

            # Check in_progress tasks - mark as stopped if process died
            in_progress_tasks = [task for task in self.tasks.values() if task.status == "in_progress"]

            if in_progress_tasks:
                for task in in_progress_tasks:
                    if task.pid and is_process_alive(task.pid):
                        # Task survived restart! Process still running
                        logger.info(f"Task {task.task_id} (PID {task.pid}) still running after restart")
                    else:
                        # Process died (or no PID tracked) - mark as stopped
                        task.status = "stopped"
                        task.error = "Task stopped due to bot restart"
                        task.updated_at = datetime.now().isoformat()
                        logger.warning(f"Marked stopped task {task.task_id}: {task.description}")

                # Save updated state
                self._save_tasks()

        except Exception as e:
            logger.error(f"Error loading tasks: {e}")

    def _save_tasks(self):
        """Save tasks to disk"""
        try:
            data = {task_id: task.to_dict() for task_id, task in self.tasks.items()}

            with open(self.tasks_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving tasks: {e}")

    def create_task(self, user_id: int, description: str, workspace: str, model: str = "sonnet") -> Task:
        """Create a new task"""
        now = datetime.now().isoformat()
        task_id = str(uuid.uuid4())[:6]

        task = Task(
            task_id=task_id,
            user_id=user_id,
            description=description,
            status="pending",
            created_at=now,
            updated_at=now,
            model=model,
            workspace=workspace,
        )

        self.tasks[task_id] = task
        self._save_tasks()

        logger.info(f"Created task {task_id} for user {user_id} in {workspace}: {description}")
        return task

    def update_task(
        self,
        task_id: str,
        status: str | None = None,
        result: str | None = None,
        error: str | None = None,
        pid: int | None = None,
    ):
        """Update task status"""
        if task_id not in self.tasks:
            logger.error(f"Task {task_id} not found")
            return

        task = self.tasks[task_id]

        if status:
            task.status = status
        if result:
            task.result = result
        if error:
            task.error = error
        if pid is not None:
            task.pid = pid

        task.updated_at = datetime.now().isoformat()
        self._save_tasks()

        logger.info(f"Updated task {task_id}: status={status}, pid={pid}")

    def get_task(self, task_id: str) -> Task | None:
        """Get task by ID"""
        return self.tasks.get(task_id)

    def get_user_tasks(self, user_id: int, status: str | None = None, limit: int = 10) -> list[Task]:
        """Get tasks for a user"""
        user_tasks = [task for task in self.tasks.values() if task.user_id == user_id]

        if status:
            user_tasks = [t for t in user_tasks if t.status == status]

        # Sort by created_at descending
        user_tasks.sort(key=lambda t: t.created_at, reverse=True)

        return user_tasks[:limit]

    def get_active_tasks(self, user_id: int) -> list[Task]:
        """Get active (pending/in_progress) tasks for user"""
        return [
            task
            for task in self.tasks.values()
            if task.user_id == user_id and task.status in ["pending", "in_progress"]
        ]

    def retry_task(self, task_id: str) -> Task | None:
        """
        Retry a failed or stopped task by creating a new task with the same parameters.
        Returns the new task if successful, None if task not found or not retryable.
        """
        original_task = self.tasks.get(task_id)

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
        )

        logger.info(f"Created retry task {new_task.task_id} for {original_task.status} task {task_id}")
        return new_task

    def get_failed_tasks(self, user_id: int, limit: int = 10) -> list[Task]:
        """Get failed tasks for a user"""
        failed_tasks = [task for task in self.tasks.values() if task.user_id == user_id and task.status == "failed"]

        # Sort by created_at descending
        failed_tasks.sort(key=lambda t: t.created_at, reverse=True)

        return failed_tasks[:limit]

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
        from datetime import datetime, timedelta

        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        cleared_count = 0

        # Find tasks to remove
        tasks_to_remove = []
        for task_id, task in self.tasks.items():
            if task.user_id == user_id and task.status == "failed":
                try:
                    task_time = datetime.fromisoformat(task.created_at)
                    if task_time < cutoff_time:
                        tasks_to_remove.append(task_id)
                except ValueError:
                    # If we can't parse the timestamp, skip this task
                    logger.warning(f"Could not parse timestamp for task {task_id}: {task.created_at}")
                    continue

        # Remove old failed tasks
        for task_id in tasks_to_remove:
            del self.tasks[task_id]
            cleared_count += 1
            logger.info(f"Cleared old failed task {task_id}")

        if cleared_count > 0:
            self._save_tasks()
            logger.info(f"Cleared {cleared_count} old failed tasks for user {user_id}")

        return cleared_count

    def mark_all_in_progress_as_stopped(self):
        """
        Mark all in-progress tasks as stopped during shutdown.
        This preserves task state so they can be retried on restart.

        Returns:
            Number of tasks marked as stopped
        """
        stopped_count = 0

        for task in self.tasks.values():
            if task.status == "in_progress":
                task.status = "stopped"
                task.error = "Task stopped during bot shutdown"
                task.updated_at = datetime.now().isoformat()
                stopped_count += 1
                logger.info(f"Marked task {task.task_id} as stopped during shutdown")

        if stopped_count > 0:
            self._save_tasks()
            logger.info(f"Marked {stopped_count} tasks as stopped during shutdown")

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
        stopped_tasks = [
            task
            for task in self.tasks.values()
            if task.status == "stopped" and (user_id is None or task.user_id == user_id)
        ]

        # Sort by created_at descending
        stopped_tasks.sort(key=lambda t: t.created_at, reverse=True)

        return stopped_tasks[:limit]

    def stop_task(self, task_id: str) -> tuple[bool, str]:
        """
        Stop a running task by killing its process.

        Args:
            task_id: Task ID to stop

        Returns:
            (success, message) tuple
        """
        task = self.tasks.get(task_id)

        if not task:
            return False, f"Task #{task_id} not found."

        if task.status not in ["pending", "in_progress"]:
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
        task.status = "stopped"
        task.error = "Task stopped by user"
        task.updated_at = datetime.now().isoformat()
        self._save_tasks()

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
            new_task = self.create_task(
                user_id=stopped_task.user_id,
                description=stopped_task.description,
                workspace=stopped_task.workspace,
                model=stopped_task.model,
            )
            new_tasks.append(new_task)
            logger.info(f"Auto-retrying stopped task {stopped_task.task_id} as {new_task.task_id}")

        if new_tasks:
            logger.info(f"Auto-retried {len(new_tasks)} stopped tasks on startup")

        return new_tasks
