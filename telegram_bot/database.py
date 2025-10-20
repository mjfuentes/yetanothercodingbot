"""
SQLite database backend for AgentLab
Replaces JSON file storage with SQLite for better performance and querying
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Database schema version for migrations
SCHEMA_VERSION = 1


class Database:
    """SQLite database wrapper for AgentLab storage"""

    def __init__(self, db_path: str = "data/agentlab.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name

        # Enable foreign keys
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Initialize schema
        self._init_schema()

        logger.info(f"Database initialized at {self.db_path}")

    def _init_schema(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()

        # Create schema version table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """
        )

        # Check current version
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        current_version = row[0] if row else 0

        if current_version < SCHEMA_VERSION:
            self._migrate_schema(current_version, SCHEMA_VERSION)
            cursor.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now().isoformat()),
            )
            self.conn.commit()

        logger.info(f"Database schema version: {SCHEMA_VERSION}")

    def _migrate_schema(self, from_version: int, to_version: int):
        """Apply schema migrations"""
        cursor = self.conn.cursor()

        if from_version == 0 and to_version >= 1:
            # Initial schema
            logger.info("Creating initial schema...")

            # Tasks table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    agent_type TEXT NOT NULL DEFAULT 'code_agent',
                    result TEXT,
                    error TEXT,
                    pid INTEGER,
                    activity_log TEXT  -- JSON array
                )
            """
            )

            # Tool usage table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    duration_ms REAL,
                    success BOOLEAN,
                    error TEXT,
                    parameters TEXT  -- JSON blob
                )
            """
            )

            # Agent status table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    metadata TEXT  -- JSON blob
                )
            """
            )

            # Create indices for common queries
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_user_status
                ON tasks(user_id, status, created_at DESC)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_created
                ON tasks(created_at DESC)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_timestamp
                ON tool_usage(timestamp DESC)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_task
                ON tool_usage(task_id)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tool_name
                ON tool_usage(tool_name)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status_timestamp
                ON agent_status(timestamp DESC)
            """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status_task
                ON agent_status(task_id)
            """
            )

            logger.info("Initial schema created successfully")

    # ========== TASK OPERATIONS ==========

    def create_task(
        self,
        task_id: str,
        user_id: int,
        description: str,
        workspace: str,
        model: str = "sonnet",
        agent_type: str = "code_agent",
    ) -> dict:
        """Create a new task"""
        now = datetime.now().isoformat()

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (
                task_id, user_id, description, status, created_at, updated_at,
                model, workspace, agent_type, activity_log
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (task_id, user_id, description, "pending", now, now, model, workspace, agent_type, "[]"),
        )
        self.conn.commit()

        logger.info(f"Created task {task_id} for user {user_id}")
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict | None:
        """Get task by ID"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_task_dict(row)

    def update_task(
        self,
        task_id: str,
        status: str | None = None,
        result: str | None = None,
        error: str | None = None,
        pid: int | None = None,
    ) -> bool:
        """Update task fields"""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if result is not None:
            updates.append("result = ?")
            params.append(result)
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if pid is not None:
            updates.append("pid = ?")
            params.append(pid)

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(task_id)

        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?", params)  # nosec B608
        self.conn.commit()

        logger.info(f"Updated task {task_id}: {', '.join(updates)}")
        return cursor.rowcount > 0

    def add_activity(self, task_id: str, message: str, output_lines: int | None = None) -> bool:
        """Add activity entry to task log"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT activity_log FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()

        if not row:
            logger.error(f"Task {task_id} not found")
            return False

        # Parse existing log
        activity_log = json.loads(row[0]) if row[0] else []

        # Add new entry
        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
        }
        if output_lines is not None:
            entry["output_lines"] = output_lines

        activity_log.append(entry)

        # Update task
        cursor.execute(
            "UPDATE tasks SET activity_log = ?, updated_at = ? WHERE task_id = ?",
            (json.dumps(activity_log), datetime.now().isoformat(), task_id),
        )
        self.conn.commit()

        logger.debug(f"Added activity to task {task_id}: {message}")
        return True

    def get_user_tasks(self, user_id: int, status: str | None = None, limit: int = 10) -> list[dict]:
        """Get tasks for a user"""
        cursor = self.conn.cursor()

        if status:
            cursor.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (user_id, status, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (user_id, limit),
            )

        return [self._row_to_task_dict(row) for row in cursor.fetchall()]

    def get_active_tasks(self, user_id: int) -> list[dict]:
        """Get active (pending/running) tasks for user"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM tasks
            WHERE user_id = ? AND status IN ('pending', 'running')
            ORDER BY created_at DESC
        """,
            (user_id,),
        )

        return [self._row_to_task_dict(row) for row in cursor.fetchall()]

    def get_failed_tasks(self, user_id: int, limit: int = 10) -> list[dict]:
        """Get failed tasks for a user"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM tasks
            WHERE user_id = ? AND status = 'failed'
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (user_id, limit),
        )

        return [self._row_to_task_dict(row) for row in cursor.fetchall()]

    def get_stopped_tasks(self, user_id: int | None = None, limit: int = 100) -> list[dict]:
        """Get stopped tasks, optionally filtered by user"""
        cursor = self.conn.cursor()

        if user_id is not None:
            cursor.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ? AND status = 'stopped'
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (user_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'stopped'
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

        return [self._row_to_task_dict(row) for row in cursor.fetchall()]

    def delete_task(self, task_id: str) -> bool:
        """Delete a task"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        self.conn.commit()

        return cursor.rowcount > 0

    def clear_old_failed_tasks(self, user_id: int, older_than_hours: int = 24) -> int:
        """Clear old failed tasks for a user"""
        cutoff_time = (datetime.now() - timedelta(hours=older_than_hours)).isoformat()

        cursor = self.conn.cursor()
        cursor.execute(
            """
            DELETE FROM tasks
            WHERE user_id = ? AND status = 'failed' AND created_at < ?
        """,
            (user_id, cutoff_time),
        )
        self.conn.commit()

        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logger.info(f"Cleared {deleted_count} old failed tasks for user {user_id}")

        return deleted_count

    def cleanup_stale_pending_tasks(self, max_age_hours: int = 1) -> int:
        """Mark stale pending tasks as failed"""
        cutoff_time = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        now = datetime.now().isoformat()

        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE tasks
            SET status = 'failed',
                error = ?,
                updated_at = ?
            WHERE status = 'pending' AND created_at < ?
        """,
            (f"Task was pending for more than {max_age_hours}h without being picked up by worker", now, cutoff_time),
        )
        self.conn.commit()

        updated_count = cursor.rowcount
        if updated_count > 0:
            logger.info(f"Cleaned up {updated_count} stale pending tasks")

        return updated_count

    def mark_all_running_as_stopped(self) -> int:
        """Mark all running tasks as stopped during shutdown"""
        now = datetime.now().isoformat()

        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE tasks
            SET status = 'stopped',
                error = 'Task stopped during bot shutdown',
                updated_at = ?
            WHERE status = 'running'
        """,
            (now,),
        )
        self.conn.commit()

        stopped_count = cursor.rowcount
        if stopped_count > 0:
            logger.info(f"Marked {stopped_count} tasks as stopped during shutdown")

        return stopped_count

    def get_task_statistics(self) -> dict:
        """Get task statistics"""
        cursor = self.conn.cursor()

        # Count by status
        cursor.execute(
            """
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        """
        )
        by_status = {row[0]: row[1] for row in cursor.fetchall()}

        # Total tasks
        cursor.execute("SELECT COUNT(*) FROM tasks")
        total = cursor.fetchone()[0]

        # Tasks in last 24 hours
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE created_at >= ?", (cutoff,))
        recent_24h = cursor.fetchone()[0]

        # Calculate success rate
        completed = by_status.get("completed", 0)
        failed = by_status.get("failed", 0)
        success_rate = (completed / (completed + failed) * 100) if (completed + failed) > 0 else 0

        return {
            "total": total,
            "by_status": by_status,
            "recent_24h": recent_24h,
            "success_rate": success_rate,
        }

    # ========== TOOL USAGE OPERATIONS ==========

    def record_tool_usage(
        self,
        task_id: str,
        tool_name: str,
        duration_ms: float | None = None,
        success: bool | None = None,
        error: str | None = None,
        parameters: dict | None = None,
    ):
        """Record tool usage"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO tool_usage (timestamp, task_id, tool_name, duration_ms, success, error, parameters)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                datetime.now().isoformat(),
                task_id,
                tool_name,
                duration_ms,
                success,
                error,
                json.dumps(parameters) if parameters else None,
            ),
        )
        self.conn.commit()

        logger.debug(f"Recorded tool usage: {task_id} - {tool_name}")

    def get_tool_statistics(self, task_id: str | None = None, hours: int = 24) -> dict[str, Any]:
        """Get tool usage statistics"""
        cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()

        cursor = self.conn.cursor()

        # Filter by time and optionally task_id
        if task_id:
            cursor.execute(
                """
                SELECT tool_name, duration_ms, success
                FROM tool_usage
                WHERE task_id = ? AND timestamp >= ?
            """,
                (task_id, cutoff_time),
            )
        else:
            cursor.execute(
                """
                SELECT tool_name, duration_ms, success
                FROM tool_usage
                WHERE timestamp >= ?
            """,
                (cutoff_time,),
            )

        rows = cursor.fetchall()

        if not rows:
            return {
                "total_calls": 0,
                "time_window_hours": hours,
                "tools": {},
            }

        # Aggregate by tool
        tool_stats = {}
        for row in rows:
            tool_name, duration_ms, success = row

            if tool_name not in tool_stats:
                tool_stats[tool_name] = {
                    "count": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_duration_ms": 0.0,
                    "min_duration_ms": float("inf"),
                    "max_duration_ms": 0.0,
                }

            stats = tool_stats[tool_name]
            stats["count"] += 1

            if success is True:
                stats["successes"] += 1
            elif success is False:
                stats["failures"] += 1

            if duration_ms is not None:
                stats["total_duration_ms"] += duration_ms
                stats["min_duration_ms"] = min(stats["min_duration_ms"], duration_ms)
                stats["max_duration_ms"] = max(stats["max_duration_ms"], duration_ms)

        # Calculate averages and success rates
        for _tool, stats in tool_stats.items():
            if stats["count"] > 0:
                if stats["total_duration_ms"] > 0:
                    stats["avg_duration_ms"] = stats["total_duration_ms"] / stats["count"]
                else:
                    stats["avg_duration_ms"] = 0.0
                stats["success_rate"] = stats["successes"] / stats["count"] if stats["count"] > 0 else 0.0

        return {
            "total_calls": len(rows),
            "time_window_hours": hours,
            "tools": tool_stats,
        }

    def get_task_timeline(self, task_id: str) -> list[dict]:
        """Get complete timeline of events for a task"""
        cursor = self.conn.cursor()

        events = []

        # Get tool usage events
        cursor.execute(
            """
            SELECT timestamp, tool_name, duration_ms, success, error
            FROM tool_usage
            WHERE task_id = ?
        """,
            (task_id,),
        )

        for row in cursor.fetchall():
            events.append(
                {
                    "timestamp": row[0],
                    "type": "tool_usage",
                    "tool_name": row[1],
                    "duration_ms": row[2],
                    "success": row[3],
                    "error": row[4],
                }
            )

        # Get status change events
        cursor.execute(
            """
            SELECT timestamp, status, message
            FROM agent_status
            WHERE task_id = ?
        """,
            (task_id,),
        )

        for row in cursor.fetchall():
            events.append(
                {
                    "timestamp": row[0],
                    "type": "status_change",
                    "status": row[1],
                    "message": row[2],
                }
            )

        # Sort by timestamp
        events.sort(key=lambda e: e["timestamp"])

        return events

    def cleanup_old_tool_usage(self, days: int = 30) -> int:
        """Delete tool usage records older than specified days"""
        cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()

        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM tool_usage WHERE timestamp < ?", (cutoff_time,))
        self.conn.commit()

        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old tool usage records")

        return deleted_count

    # ========== AGENT STATUS OPERATIONS ==========

    def record_agent_status(
        self,
        task_id: str,
        status: str,
        message: str | None = None,
        metadata: dict | None = None,
    ):
        """Record agent status change"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO agent_status (timestamp, task_id, status, message, metadata)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                datetime.now().isoformat(),
                task_id,
                status,
                message,
                json.dumps(metadata) if metadata else None,
            ),
        )
        self.conn.commit()

        logger.debug(f"Recorded status change: {task_id} - {status}")

    def get_agent_status_summary(self, task_id: str | None = None) -> dict[str, Any]:
        """Get summary of agent status changes"""
        cursor = self.conn.cursor()

        if task_id:
            cursor.execute(
                """
                SELECT status, timestamp, task_id, message
                FROM agent_status
                WHERE task_id = ?
                ORDER BY timestamp DESC
            """,
                (task_id,),
            )
        else:
            cursor.execute(
                """
                SELECT status, timestamp, task_id, message
                FROM agent_status
                ORDER BY timestamp DESC
            """
            )

        rows = cursor.fetchall()

        if not rows:
            return {
                "total_status_changes": 0,
                "by_status": {},
                "recent_changes": [],
            }

        # Aggregate by status
        status_counts = {}
        for row in rows:
            status = row[0]
            status_counts[status] = status_counts.get(status, 0) + 1

        # Get recent changes (last 10)
        recent_changes = [
            {
                "timestamp": row[1],
                "task_id": row[2],
                "status": row[0],
                "message": row[3],
            }
            for row in rows[:10]
        ]

        return {
            "total_status_changes": len(rows),
            "by_status": status_counts,
            "recent_changes": recent_changes,
        }

    def cleanup_old_agent_status(self, days: int = 30) -> int:
        """Delete agent status records older than specified days"""
        cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()

        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM agent_status WHERE timestamp < ?", (cutoff_time,))
        self.conn.commit()

        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old agent status records")

        return deleted_count

    # ========== UTILITY METHODS ==========

    def _row_to_task_dict(self, row: sqlite3.Row) -> dict:
        """Convert SQLite row to task dictionary"""
        return {
            "task_id": row["task_id"],
            "user_id": row["user_id"],
            "description": row["description"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "model": row["model"],
            "workspace": row["workspace"],
            "agent_type": row["agent_type"],
            "result": row["result"],
            "error": row["error"],
            "pid": row["pid"],
            "activity_log": json.loads(row["activity_log"]) if row["activity_log"] else [],
        }

    def get_database_stats(self) -> dict:
        """Get database statistics"""
        cursor = self.conn.cursor()

        # Count tasks
        cursor.execute("SELECT COUNT(*) FROM tasks")
        task_count = cursor.fetchone()[0]

        # Count tool usage
        cursor.execute("SELECT COUNT(*) FROM tool_usage")
        tool_usage_count = cursor.fetchone()[0]

        # Count agent status
        cursor.execute("SELECT COUNT(*) FROM agent_status")
        agent_status_count = cursor.fetchone()[0]

        # Database file size
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        return {
            "tasks": task_count,
            "tool_usage_records": tool_usage_count,
            "agent_status_records": agent_status_count,
            "database_size_bytes": db_size,
            "database_size_kb": db_size / 1024,
        }

    def vacuum(self):
        """Vacuum database to reclaim space"""
        logger.info("Vacuuming database...")
        self.conn.execute("VACUUM")
        logger.info("Database vacuumed successfully")

    def close(self):
        """Close database connection"""
        self.conn.close()
        logger.info("Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
