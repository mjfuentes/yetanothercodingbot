"""
Tool usage tracking system with hooks for monitoring Claude agent activity
Tracks tool calls, execution times, success rates, and agent status
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolUsageRecord:
    """Record of a single tool usage event"""

    timestamp: str
    task_id: str
    tool_name: str
    duration_ms: float | None = None  # Execution time in milliseconds
    success: bool | None = None
    error: str | None = None
    parameters: dict | None = None  # Sanitized parameters (no sensitive data)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ToolUsageRecord":
        return cls(**data)


@dataclass
class AgentStatusRecord:
    """Record of agent status changes"""

    timestamp: str
    task_id: str
    status: str  # 'started', 'tool_call', 'completed', 'failed'
    message: str | None = None
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentStatusRecord":
        return cls(**data)


class ToolUsageTracker:
    """Track tool usage and agent activity with hooks"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.usage_file = self.data_dir / "tool_usage.json"
        self.status_file = self.data_dir / "agent_status.json"

        # Storage
        self.tool_records: list[ToolUsageRecord] = []
        self.status_records: list[AgentStatusRecord] = []

        # Hooks - callbacks that get called on events
        self.tool_start_hooks: list[Callable[[str, str, dict], None]] = []
        self.tool_complete_hooks: list[Callable[[str, str, float, bool, str | None], None]] = []
        self.status_change_hooks: list[Callable[[str, str, str | None], None]] = []

        # Load existing data
        self._load_data()

        logger.info(
            f"ToolUsageTracker initialized with {len(self.tool_records)} tool records "
            f"and {len(self.status_records)} status records"
        )

    def _load_data(self):
        """Load tracking data from disk"""
        # Load tool usage records
        if self.usage_file.exists():
            try:
                with open(self.usage_file) as f:
                    data = json.load(f)
                    self.tool_records = [ToolUsageRecord.from_dict(r) for r in data]
                logger.info(f"Loaded {len(self.tool_records)} tool usage records")
            except Exception as e:
                logger.error(f"Error loading tool usage records: {e}")

        # Load agent status records
        if self.status_file.exists():
            try:
                with open(self.status_file) as f:
                    data = json.load(f)
                    self.status_records = [AgentStatusRecord.from_dict(r) for r in data]
                logger.info(f"Loaded {len(self.status_records)} agent status records")
            except Exception as e:
                logger.error(f"Error loading agent status records: {e}")

    def _save_tool_usage(self):
        """Save tool usage records to disk"""
        try:
            # Keep only last 10000 records
            if len(self.tool_records) > 10000:
                self.tool_records = self.tool_records[-10000:]

            data = [r.to_dict() for r in self.tool_records]
            with open(self.usage_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tool usage records: {e}")

    def _save_agent_status(self):
        """Save agent status records to disk"""
        try:
            # Keep only last 5000 records
            if len(self.status_records) > 5000:
                self.status_records = self.status_records[-5000:]

            data = [r.to_dict() for r in self.status_records]
            with open(self.status_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving agent status records: {e}")

    # Hook management
    def register_tool_start_hook(self, callback: Callable[[str, str, dict], None]):
        """
        Register a hook that gets called when a tool usage starts

        Args:
            callback: Function with signature (task_id, tool_name, parameters) -> None
        """
        self.tool_start_hooks.append(callback)
        logger.info(f"Registered tool start hook: {callback.__name__}")

    def register_tool_complete_hook(self, callback: Callable[[str, str, float, bool, str | None], None]):
        """
        Register a hook that gets called when a tool usage completes

        Args:
            callback: Function with signature (task_id, tool_name, duration_ms, success, error) -> None
        """
        self.tool_complete_hooks.append(callback)
        logger.info(f"Registered tool complete hook: {callback.__name__}")

    def register_status_change_hook(self, callback: Callable[[str, str, str | None], None]):
        """
        Register a hook that gets called when agent status changes

        Args:
            callback: Function with signature (task_id, status, message) -> None
        """
        self.status_change_hooks.append(callback)
        logger.info(f"Registered status change hook: {callback.__name__}")

    # Tool usage tracking
    def record_tool_start(self, task_id: str, tool_name: str, parameters: dict | None = None) -> str:
        """
        Record the start of a tool usage

        Args:
            task_id: Task ID
            tool_name: Name of the tool being used
            parameters: Tool parameters (will be sanitized)

        Returns:
            Record ID for tracking this usage
        """
        # Sanitize parameters - remove sensitive data
        sanitized_params = self._sanitize_parameters(parameters) if parameters else None

        # Create record with pending state
        record = ToolUsageRecord(
            timestamp=datetime.now().isoformat(),
            task_id=task_id,
            tool_name=tool_name,
            parameters=sanitized_params,
            success=None,  # Pending
        )

        self.tool_records.append(record)

        # Call hooks
        for hook in self.tool_start_hooks:
            try:
                hook(task_id, tool_name, sanitized_params or {})
            except Exception as e:
                logger.error(f"Error in tool start hook {hook.__name__}: {e}")

        logger.debug(f"Recorded tool start: {task_id} - {tool_name}")

        # Return index as record ID
        return str(len(self.tool_records) - 1)

    def record_tool_complete(
        self, task_id: str, tool_name: str, duration_ms: float, success: bool = True, error: str | None = None
    ):
        """
        Record the completion of a tool usage

        Args:
            task_id: Task ID
            tool_name: Name of the tool used
            duration_ms: Execution time in milliseconds
            success: Whether the tool completed successfully
            error: Error message if tool failed
        """
        # Create completion record
        record = ToolUsageRecord(
            timestamp=datetime.now().isoformat(),
            task_id=task_id,
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=success,
            error=error,
        )

        self.tool_records.append(record)
        self._save_tool_usage()

        # Call hooks
        for hook in self.tool_complete_hooks:
            try:
                hook(task_id, tool_name, duration_ms, success, error)
            except Exception as e:
                logger.error(f"Error in tool complete hook {hook.__name__}: {e}")

        status = "success" if success else "failed"
        logger.info(f"Recorded tool completion: {task_id} - {tool_name} ({duration_ms:.2f}ms, {status})")

    # Agent status tracking
    def record_status_change(self, task_id: str, status: str, message: str | None = None, metadata: dict | None = None):
        """
        Record a change in agent status

        Args:
            task_id: Task ID
            status: New status ('started', 'tool_call', 'completed', 'failed')
            message: Optional message describing the status change
            metadata: Optional metadata dictionary
        """
        record = AgentStatusRecord(
            timestamp=datetime.now().isoformat(), task_id=task_id, status=status, message=message, metadata=metadata
        )

        self.status_records.append(record)
        self._save_agent_status()

        # Call hooks
        for hook in self.status_change_hooks:
            try:
                hook(task_id, status, message)
            except Exception as e:
                logger.error(f"Error in status change hook {hook.__name__}: {e}")

        logger.info(f"Recorded status change: {task_id} - {status} {f'({message})' if message else ''}")

    # Statistics and reporting
    def get_tool_statistics(self, task_id: str | None = None, hours: int = 24) -> dict[str, Any]:
        """
        Get tool usage statistics

        Args:
            task_id: Optional task ID to filter by
            hours: Time window in hours (default: 24)

        Returns:
            Dictionary with statistics
        """

        cutoff_time = datetime.now(UTC) - timedelta(hours=hours)

        # Filter records
        records = [
            r
            for r in self.tool_records
            if (task_id is None or r.task_id == task_id) and datetime.fromisoformat(r.timestamp) >= cutoff_time
        ]

        if not records:
            return {
                "total_calls": 0,
                "time_window_hours": hours,
                "tools": {},
            }

        # Aggregate by tool
        tool_stats = {}
        for record in records:
            tool = record.tool_name
            if tool not in tool_stats:
                tool_stats[tool] = {
                    "count": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_duration_ms": 0.0,
                    "min_duration_ms": float("inf"),
                    "max_duration_ms": 0.0,
                }

            stats = tool_stats[tool]
            stats["count"] += 1
            if record.success is True:
                stats["successes"] += 1
            elif record.success is False:
                stats["failures"] += 1

            if record.duration_ms is not None:
                stats["total_duration_ms"] += record.duration_ms
                stats["min_duration_ms"] = min(stats["min_duration_ms"], record.duration_ms)
                stats["max_duration_ms"] = max(stats["max_duration_ms"], record.duration_ms)

        # Calculate averages and success rates
        for _tool, stats in tool_stats.items():
            if stats["count"] > 0:
                # Only calculate avg duration if we have duration data
                if stats["total_duration_ms"] > 0:
                    stats["avg_duration_ms"] = stats["total_duration_ms"] / stats["count"]
                else:
                    stats["avg_duration_ms"] = 0.0
                stats["success_rate"] = stats["successes"] / stats["count"] if stats["count"] > 0 else 0.0

        return {
            "total_calls": len(records),
            "time_window_hours": hours,
            "tools": tool_stats,
        }

    def get_agent_status_summary(self, task_id: str | None = None) -> dict[str, Any]:
        """
        Get summary of agent status changes

        Args:
            task_id: Optional task ID to filter by

        Returns:
            Dictionary with status summary
        """
        # Filter records
        records = [r for r in self.status_records if task_id is None or r.task_id == task_id]

        if not records:
            return {
                "total_status_changes": 0,
                "by_status": {},
                "recent_changes": [],
            }

        # Aggregate by status
        status_counts = {}
        for record in records:
            status = record.status
            status_counts[status] = status_counts.get(status, 0) + 1

        # Get recent changes (last 10)
        recent = sorted(records, key=lambda r: r.timestamp, reverse=True)[:10]
        recent_changes = [
            {"timestamp": r.timestamp, "task_id": r.task_id, "status": r.status, "message": r.message} for r in recent
        ]

        return {
            "total_status_changes": len(records),
            "by_status": status_counts,
            "recent_changes": recent_changes,
        }

    def get_task_timeline(self, task_id: str) -> list[dict]:
        """
        Get complete timeline of events for a task

        Args:
            task_id: Task ID

        Returns:
            List of events sorted by timestamp
        """
        events = []

        # Add tool usage events
        for record in self.tool_records:
            if record.task_id == task_id:
                events.append(
                    {
                        "timestamp": record.timestamp,
                        "type": "tool_usage",
                        "tool_name": record.tool_name,
                        "duration_ms": record.duration_ms,
                        "success": record.success,
                        "error": record.error,
                    }
                )

        # Add status change events
        for record in self.status_records:
            if record.task_id == task_id:
                events.append(
                    {
                        "timestamp": record.timestamp,
                        "type": "status_change",
                        "status": record.status,
                        "message": record.message,
                    }
                )

        # Sort by timestamp
        events.sort(key=lambda e: e["timestamp"])

        return events

    def _sanitize_parameters(self, parameters: dict) -> dict:
        """
        Sanitize parameters to remove sensitive data

        Args:
            parameters: Raw parameters

        Returns:
            Sanitized parameters
        """
        sanitized = {}

        # List of keys to exclude
        sensitive_keys = {"token", "password", "secret", "api_key", "auth", "credential"}

        for key, value in parameters.items():
            # Skip sensitive keys
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "<redacted>"
            # Truncate long strings
            elif isinstance(value, str) and len(value) > 200:
                sanitized[key] = value[:200] + "..."
            else:
                sanitized[key] = value

        return sanitized


class ToolUsageContext:
    """Context manager for tracking tool usage with automatic timing"""

    def __init__(self, tracker: ToolUsageTracker, task_id: str, tool_name: str, parameters: dict | None = None):
        self.tracker = tracker
        self.task_id = task_id
        self.tool_name = tool_name
        self.parameters = parameters
        self.start_time: float | None = None
        self.record_id: str | None = None

    def __enter__(self):
        """Start tracking tool usage"""
        self.start_time = time.time()
        self.record_id = self.tracker.record_tool_start(self.task_id, self.tool_name, self.parameters)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete tracking tool usage"""
        if self.start_time:
            duration_ms = (time.time() - self.start_time) * 1000
            success = exc_type is None
            error = str(exc_val) if exc_val else None

            self.tracker.record_tool_complete(self.task_id, self.tool_name, duration_ms, success, error)

        return False  # Don't suppress exceptions
