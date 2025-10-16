"""
Task tracking system for background operations
Phase 3-4: Orchestrator & worker task management
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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
    result: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Task':
        return cls(**data)


class TaskManager:
    """Manages background tasks"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.tasks_file = self.data_dir / "tasks.json"
        self.tasks: Dict[str, Task] = {}

        # Load existing tasks
        self._load_tasks()

        logger.info(f"TaskManager initialized with {len(self.tasks)} tasks")

    def _load_tasks(self):
        """Load tasks from disk"""
        if not self.tasks_file.exists():
            return

        try:
            with open(self.tasks_file, 'r') as f:
                data = json.load(f)
                for task_id, task_data in data.items():
                    self.tasks[task_id] = Task.from_dict(task_data)

            logger.info(f"Loaded {len(self.tasks)} tasks from disk")
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")

    def _save_tasks(self):
        """Save tasks to disk"""
        try:
            data = {
                task_id: task.to_dict()
                for task_id, task in self.tasks.items()
            }

            with open(self.tasks_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving tasks: {e}")

    def create_task(
        self,
        user_id: int,
        description: str,
        workspace: str,
        model: str = "sonnet"
    ) -> Task:
        """Create a new task"""
        now = datetime.now().isoformat()
        task_id = str(uuid.uuid4())[:8]

        task = Task(
            task_id=task_id,
            user_id=user_id,
            description=description,
            status="pending",
            created_at=now,
            updated_at=now,
            model=model,
            workspace=workspace
        )

        self.tasks[task_id] = task
        self._save_tasks()

        logger.info(f"Created task {task_id} for user {user_id} in {workspace}: {description}")
        return task

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None
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

        task.updated_at = datetime.now().isoformat()
        self._save_tasks()

        logger.info(f"Updated task {task_id}: status={status}")

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        return self.tasks.get(task_id)

    def get_user_tasks(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 10
    ) -> List[Task]:
        """Get tasks for a user"""
        user_tasks = [
            task for task in self.tasks.values()
            if task.user_id == user_id
        ]

        if status:
            user_tasks = [t for t in user_tasks if t.status == status]

        # Sort by created_at descending
        user_tasks.sort(key=lambda t: t.created_at, reverse=True)

        return user_tasks[:limit]

    def get_active_tasks(self, user_id: int) -> List[Task]:
        """Get active (pending/in_progress) tasks for user"""
        return [
            task for task in self.tasks.values()
            if task.user_id == user_id and task.status in ['pending', 'in_progress']
        ]
