"""
Metrics aggregation system for bot monitoring
Collects and aggregates data from all tracking systems
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cost_tracker import CostTracker
from hooks_reader import HooksReader
from tasks import TaskManager
from tool_usage_tracker import ToolUsageTracker

logger = logging.getLogger(__name__)


@dataclass
class MetricsSnapshot:
    """Snapshot of bot metrics at a point in time"""

    timestamp: str
    claude_api_usage: dict[str, Any]
    task_statistics: dict[str, Any]
    tool_usage: dict[str, Any]
    system_health: dict[str, Any]

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsAggregator:
    """Aggregates metrics from all tracking systems"""

    def __init__(
        self,
        cost_tracker: CostTracker,
        task_manager: TaskManager,
        tool_usage_tracker: ToolUsageTracker,
        hooks_reader: HooksReader | None = None,
    ):
        self.cost_tracker = cost_tracker
        self.task_manager = task_manager
        self.tool_usage_tracker = tool_usage_tracker
        self.hooks_reader = hooks_reader

        logger.info("MetricsAggregator initialized")

    def get_claude_api_metrics(self, hours: int = 24) -> dict[str, Any]:
        """Get Claude API usage metrics"""
        # Aggregate across all users
        all_users = {}
        total_cost = 0.0
        total_requests = 0
        model_breakdown = {}

        for user_id, usage in self.cost_tracker.users.items():
            all_users[user_id] = self.cost_tracker.get_usage_stats(user_id)
            total_cost += usage.total_cost
            total_requests += usage.total_requests

            # Aggregate model breakdown
            for record in usage.records:
                model = record.model
                if model not in model_breakdown:
                    model_breakdown[model] = {
                        "requests": 0,
                        "cost": 0.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }
                model_breakdown[model]["requests"] += 1
                model_breakdown[model]["cost"] += record.cost
                model_breakdown[model]["input_tokens"] += record.input_tokens
                model_breakdown[model]["output_tokens"] += record.output_tokens

        # Recent activity (last N hours)
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_requests = 0
        recent_cost = 0.0

        for usage in self.cost_tracker.users.values():
            for record in usage.records:
                record_time = datetime.fromisoformat(record.timestamp)
                if record_time >= cutoff_time:
                    recent_requests += 1
                    recent_cost += record.cost

        return {
            "total_cost": total_cost,
            "total_requests": total_requests,
            "recent_hours": hours,
            "recent_requests": recent_requests,
            "recent_cost": recent_cost,
            "model_breakdown": model_breakdown,
            "by_user": all_users,
        }

    def get_task_statistics(self) -> dict[str, Any]:
        """Get task execution statistics"""
        all_tasks = list(self.task_manager.tasks.values())

        # Count by status
        status_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "stopped": 0}

        for task in all_tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        # Recent tasks (last 24 hours)
        cutoff_time = datetime.now() - timedelta(hours=24)
        recent_tasks = []
        recent_completed = 0
        recent_failed = 0

        for task in all_tasks:
            task_time = datetime.fromisoformat(task.created_at)
            if task_time >= cutoff_time:
                recent_tasks.append(
                    {
                        "task_id": task.task_id,
                        "user_id": task.user_id,
                        "description": task.description[:100],
                        "status": task.status,
                        "created_at": task.created_at,
                        "model": task.model,
                    }
                )
                if task.status == "completed":
                    recent_completed += 1
                elif task.status == "failed":
                    recent_failed += 1

        # Calculate success rate
        total_finished = status_counts["completed"] + status_counts["failed"]
        success_rate = (status_counts["completed"] / total_finished * 100) if total_finished > 0 else 0.0

        return {
            "total_tasks": len(all_tasks),
            "by_status": status_counts,
            "success_rate": success_rate,
            "recent_24h": {
                "total": len(recent_tasks),
                "completed": recent_completed,
                "failed": recent_failed,
                "tasks": recent_tasks[:20],  # Last 20 tasks
            },
        }

    def get_tool_usage_metrics(self, hours: int = 24) -> dict[str, Any]:
        """Get tool usage statistics from Claude Code hooks"""
        # Use hooks data if available
        if self.hooks_reader:
            hooks_stats = self.hooks_reader.get_aggregate_statistics(hours=hours)

            # Convert to expected format
            tools_breakdown = hooks_stats["tools_by_type"]
            most_used = sorted(
                [
                    {
                        "tool": k,
                        "count": v,
                        "success_rate": 1.0,  # Hooks don't track success rate per tool
                        "avg_duration_ms": 0.0,
                    }
                    for k, v in tools_breakdown.items()
                ],
                key=lambda x: x["count"],
                reverse=True,
            )[:10]

            status_summary = self.tool_usage_tracker.get_agent_status_summary()

            return {
                "time_window_hours": hours,
                "total_tool_calls": hooks_stats["total_tool_calls"],
                "tools_breakdown": tools_breakdown,
                "most_used_tools": most_used,
                "agent_status": status_summary,
            }

        # Fallback to old tracker (mostly empty)
        tool_stats = self.tool_usage_tracker.get_tool_statistics(hours=hours)
        status_summary = self.tool_usage_tracker.get_agent_status_summary()

        tools_by_usage = sorted(
            tool_stats.get("tools", {}).items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )

        most_used_tools = [
            {
                "tool": tool,
                "count": stats["count"],
                "success_rate": stats.get("success_rate", 0.0),
                "avg_duration_ms": stats.get("avg_duration_ms", 0.0),
            }
            for tool, stats in tools_by_usage[:10]
        ]

        return {
            "time_window_hours": hours,
            "total_tool_calls": tool_stats.get("total_calls", 0),
            "tools_breakdown": tool_stats.get("tools", {}),
            "most_used_tools": most_used_tools,
            "agent_status": status_summary,
        }

    def get_system_health(self) -> dict[str, Any]:
        """Get system health metrics"""
        # Check data file sizes
        data_dir = Path("data")
        file_sizes = {}

        if data_dir.exists():
            for file in data_dir.glob("*.json"):
                size_mb = file.stat().st_size / (1024 * 1024)
                file_sizes[file.name] = round(size_mb, 2)

        # Active sessions info
        active_tasks = [task for task in self.task_manager.tasks.values() if task.status in ["pending", "running"]]

        # Recent errors
        recent_errors = []
        cutoff_time = datetime.now() - timedelta(hours=24)

        for task in self.task_manager.tasks.values():
            if task.status == "failed" and task.error:
                task_time = datetime.fromisoformat(task.created_at)
                if task_time >= cutoff_time:
                    recent_errors.append(
                        {
                            "task_id": task.task_id,
                            "timestamp": task.created_at,
                            "error": task.error[:200],  # Truncate long errors
                        }
                    )

        # Sort by timestamp (most recent first)
        recent_errors.sort(key=lambda x: x["timestamp"], reverse=True)

        return {
            "data_file_sizes_mb": file_sizes,
            "active_tasks_count": len(active_tasks),
            "recent_errors_24h": len(recent_errors),
            "recent_errors": recent_errors[:10],  # Last 10 errors
            "timestamp": datetime.now().isoformat(),
        }

    def get_complete_snapshot(self, hours: int = 24) -> MetricsSnapshot:
        """Get complete metrics snapshot"""
        return MetricsSnapshot(
            timestamp=datetime.now().isoformat(),
            claude_api_usage=self.get_claude_api_metrics(hours=hours),
            task_statistics=self.get_task_statistics(),
            tool_usage=self.get_tool_usage_metrics(hours=hours),
            system_health=self.get_system_health(),
        )

    def get_hook_usage_summary(self) -> dict[str, Any]:
        """Get summary of registered hooks and their activity"""
        return {
            "tool_start_hooks": len(self.tool_usage_tracker.tool_start_hooks),
            "tool_complete_hooks": len(self.tool_usage_tracker.tool_complete_hooks),
            "status_change_hooks": len(self.tool_usage_tracker.status_change_hooks),
            "hooks_registered": (
                len(self.tool_usage_tracker.tool_start_hooks)
                + len(self.tool_usage_tracker.tool_complete_hooks)
                + len(self.tool_usage_tracker.status_change_hooks)
            ),
        }

    def get_time_series_data(self, hours: int = 24, interval_minutes: int = 60) -> dict[str, Any]:
        """
        Get time-series data for charting

        Args:
            hours: Time window in hours
            interval_minutes: Data point interval in minutes
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        interval_delta = timedelta(minutes=interval_minutes)

        # Initialize time buckets
        buckets = []
        current_time = cutoff_time
        while current_time <= datetime.now():
            buckets.append(
                {
                    "timestamp": current_time.isoformat(),
                    "requests": 0,
                    "cost": 0.0,
                    "tasks_completed": 0,
                    "tasks_failed": 0,
                    "tool_calls": 0,
                }
            )
            current_time += interval_delta

        # Aggregate data into buckets
        for usage in self.cost_tracker.users.values():
            for record in usage.records:
                record_time = datetime.fromisoformat(record.timestamp)
                if record_time >= cutoff_time:
                    # Find appropriate bucket
                    bucket_index = int((record_time - cutoff_time).total_seconds() / (interval_minutes * 60))
                    if 0 <= bucket_index < len(buckets):
                        buckets[bucket_index]["requests"] += 1
                        buckets[bucket_index]["cost"] += record.cost

        # Add task data
        for task in self.task_manager.tasks.values():
            task_time = datetime.fromisoformat(task.created_at)
            if task_time >= cutoff_time:
                bucket_index = int((task_time - cutoff_time).total_seconds() / (interval_minutes * 60))
                if 0 <= bucket_index < len(buckets):
                    if task.status == "completed":
                        buckets[bucket_index]["tasks_completed"] += 1
                    elif task.status == "failed":
                        buckets[bucket_index]["tasks_failed"] += 1

        # Add tool usage data (count all tool records, not just those with duration)
        for record in self.tool_usage_tracker.tool_records:
            record_time = datetime.fromisoformat(record.timestamp)
            if record_time >= cutoff_time:
                bucket_index = int((record_time - cutoff_time).total_seconds() / (interval_minutes * 60))
                if 0 <= bucket_index < len(buckets):
                    buckets[bucket_index]["tool_calls"] += 1

        return {
            "time_window_hours": hours,
            "interval_minutes": interval_minutes,
            "data_points": buckets,
        }
