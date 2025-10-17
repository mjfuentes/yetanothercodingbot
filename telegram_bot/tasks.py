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
    status: str  # 'pending', 'in_progress', 'completed', 'failed'
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

            # FIX #1 & #3: Check in_progress tasks - mark as failed if process died
            in_progress_tasks = [task for task in self.tasks.values() if task.status == "in_progress"]

            if in_progress_tasks:
                for task in in_progress_tasks:
                    if task.pid and is_process_alive(task.pid):
                        # Task survived restart! Process still running
                        logger.info(f"Task {task.task_id} (PID {task.pid}) still running after restart")
                    else:
                        # Process died (or no PID tracked)
                        task.status = "failed"
                        task.error = "Task cancelled due to bot restart"
                        task.updated_at = datetime.now().isoformat()
                        logger.warning(f"Cleared stale task {task.task_id}: {task.description}")

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
        Retry a failed task by creating a new task with the same parameters.
        Returns the new task if successful, None if task not found or not failed.
        """
        original_task = self.tasks.get(task_id)

        if not original_task:
            logger.error(f"Task {task_id} not found")
            return None

        if original_task.status != "failed":
            logger.warning(f"Task {task_id} is not failed (status: {original_task.status})")
            return None

        # Create new task with same parameters
        new_task = self.create_task(
            user_id=original_task.user_id,
            description=original_task.description,
            workspace=original_task.workspace,
            model=original_task.model,
        )

        logger.info(f"Created retry task {new_task.task_id} for failed task {task_id}")
        return new_task

    def get_failed_tasks(self, user_id: int, limit: int = 10) -> list[Task]:
        """Get failed tasks for a user"""
        failed_tasks = [task for task in self.tasks.values() if task.user_id == user_id and task.status == "failed"]

        # Sort by created_at descending
        failed_tasks.sort(key=lambda t: t.created_at, reverse=True)

        return failed_tasks[:limit]
