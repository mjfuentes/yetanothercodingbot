"""
Flask-based monitoring server for bot metrics
Provides web UI and REST API for real-time metrics with SSE support
"""

import json
import logging
import os
import time
from collections.abc import Generator
from pathlib import Path

from cost_tracker import CostTracker
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS
from hooks_reader import HooksReader
from metrics_aggregator import MetricsAggregator
from tasks import TaskManager
from tool_usage_tracker import ToolUsageTracker

# Load environment variables from parent directory's .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
CORS(app)  # Enable CORS for API access

# Initialize tracking systems (determine data paths based on where we're running from)

if Path.cwd().name == "telegram_bot":
    # Running from telegram_bot/ directory
    data_dir = "../data"
    sessions_dir = "../logs/sessions"
else:
    # Running from project root
    data_dir = "data"
    sessions_dir = "logs/sessions"

cost_tracker = CostTracker(data_dir=data_dir)
task_manager = TaskManager(data_dir=data_dir)
tool_usage_tracker = ToolUsageTracker(data_dir=data_dir)
hooks_reader = HooksReader(sessions_dir=sessions_dir)

# Initialize metrics aggregator
metrics_aggregator = MetricsAggregator(cost_tracker, task_manager, tool_usage_tracker, hooks_reader)

# Store last sent data for change detection
last_metrics_snapshot = None


@app.route("/")
def index():
    """Serve the main dashboard"""
    import base64
    import os

    # Load logo image and convert to base64
    logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
    logo_base64 = ""

    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode("utf-8")

    return render_template("dashboard.html", logo_base64=logo_base64)


@app.route("/api/metrics/overview")
def metrics_overview():
    """Get overview of all metrics"""
    try:
        # Reload tasks to get latest state
        task_manager.reload_tasks()

        hours = int(request.args.get("hours", 24))
        snapshot = metrics_aggregator.get_complete_snapshot(hours=hours)
        return jsonify(snapshot.to_dict())
    except Exception as e:
        logger.error(f"Error getting metrics overview: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/claude-api")
def claude_api_metrics():
    """Get Claude API usage metrics"""
    try:
        hours = int(request.args.get("hours", 24))
        metrics = metrics_aggregator.get_claude_api_metrics(hours=hours)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting Claude API metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/tasks")
def task_metrics():
    """Get task execution metrics"""
    try:
        # Reload tasks to get latest state
        task_manager.reload_tasks()
        metrics = metrics_aggregator.get_task_statistics()
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting task metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<task_id>/tool-usage")
def task_tool_usage(task_id):
    """Get tool usage for a specific task from session logs"""
    try:
        import json
        import uuid
        from collections import defaultdict

        # Convert task_id to UUID (same deterministic conversion as in claude_interactive.py)
        task_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"agentlab.task.{task_id}"))

        # Session logs are stored in logs/sessions/{task_uuid}/
        session_dir = Path(sessions_dir) / task_uuid
        summary_file = session_dir / "summary.json"
        pre_tool_file = session_dir / "pre_tool_use.jsonl"
        post_tool_file = session_dir / "post_tool_use.jsonl"

        # Check if session directory exists
        if not session_dir.exists():
            return jsonify({"error": "No session logs found for this task"}), 404

        # Read summary if it exists, otherwise generate on-the-fly for running tasks
        if summary_file.exists():
            with open(summary_file) as f:
                summary = json.load(f)
        else:
            # Generate summary from JSONL files for running tasks
            summary = {
                "task_id": task_id,
                "total_tools_used": 0,
                "tools_by_type": {},
                "blocked_operations": 0,
                "tools_with_errors": 0,
            }

            # Count from post_tool_use.jsonl
            if post_tool_file.exists():
                tools_by_type = defaultdict(int)
                tools_with_errors = 0
                with open(post_tool_file) as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            tool = entry.get("tool", "unknown")
                            tools_by_type[tool] += 1
                            if entry.get("has_error", False):
                                tools_with_errors += 1

                summary["total_tools_used"] = sum(tools_by_type.values())
                summary["tools_by_type"] = dict(tools_by_type)
                summary["tools_with_errors"] = tools_with_errors

            # Count blocked operations from pre_tool_use.jsonl
            if pre_tool_file.exists():
                blocked_count = 0
                with open(pre_tool_file) as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            if entry.get("status") == "blocked":
                                blocked_count += 1
                summary["blocked_operations"] = blocked_count

        # Read post_tool_use for detailed tool calls
        tool_calls = []
        worker_chain = []

        if post_tool_file.exists():
            with open(post_tool_file) as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        tool_calls.append(entry)

                        # Track worker spawning (Task tool calls)
                        if entry.get("tool") == "Task":
                            # Note: parameters not available in post_tool_use hook
                            worker_chain.append(
                                {
                                    "worker": "unknown",
                                    "description": "Task agent spawned",
                                    "timestamp": entry.get("timestamp"),
                                }
                            )

        return jsonify(
            {
                "task_id": task_id,
                "summary": summary,
                "tool_calls": tool_calls,
                "worker_chain": worker_chain,
                "has_logs": True,
            }
        )
    except Exception as e:
        logger.error(f"Error getting tool usage for task {task_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/activity")
def task_activity():
    """Get recent task activity for live feed"""
    try:
        limit = int(request.args.get("limit", 50))
        user_id = request.args.get("user_id")  # Optional filter by user

        # End any stale read transaction to see latest writes
        task_manager.db.conn.rollback()

        # Get tasks from database
        cursor = task_manager.db.conn.cursor()
        if user_id:
            cursor.execute(
                """
                SELECT task_id, description, status, activity_log, updated_at
                FROM tasks
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            """,
                (int(user_id), limit),
            )
        else:
            cursor.execute(
                """
                SELECT task_id, description, status, activity_log, updated_at
                FROM tasks
                ORDER BY updated_at DESC
                LIMIT ?
            """,
                (limit,),
            )

        # Build activity feed from task activity logs
        activity_feed = []
        for row in cursor.fetchall():
            task_id, description, status, activity_log_json, updated_at = row
            activity_log = json.loads(activity_log_json) if activity_log_json else []

            # Add each activity entry
            if activity_log:
                for activity in reversed(activity_log[-10:]):  # Last 10 per task
                    activity_feed.append(
                        {
                            "task_id": task_id,
                            "description": description[:50],
                            "status": status,
                            "timestamp": activity["timestamp"],
                            "message": activity["message"],
                            "output_lines": activity.get("output_lines"),
                        }
                    )

        # Sort all activity by timestamp (most recent first)
        activity_feed.sort(key=lambda x: x["timestamp"], reverse=True)

        return jsonify({"activity": activity_feed[:limit], "total": len(activity_feed)})

    except Exception as e:
        logger.error(f"Error getting task activity: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/tools")
def tool_metrics():
    """Get tool usage metrics from Claude Code hooks"""
    try:
        hours = int(request.args.get("hours", 24))
        # Use hooks data instead of ToolUsageTracker (which isn't populated)
        hooks_stats = hooks_reader.get_aggregate_statistics(hours=hours)

        # Convert to expected format
        tools_breakdown = hooks_stats["tools_by_type"]
        most_used = sorted(
            [
                {"tool": k, "count": v, "success_rate": 100.0, "avg_duration_ms": 0.0}
                for k, v in tools_breakdown.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        # Get agent status from ToolUsageTracker (still useful)
        status_summary = tool_usage_tracker.get_agent_status_summary()

        return jsonify(
            {
                "time_window_hours": hours,
                "total_tool_calls": hooks_stats["total_tool_calls"],
                "tools_breakdown": tools_breakdown,
                "most_used_tools": most_used,
                "agent_status": status_summary,
            }
        )
    except Exception as e:
        logger.error(f"Error getting tool metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/hooks")
def hook_metrics():
    """Get hook usage metrics from Claude Code hook logs"""
    try:
        hours = int(request.args.get("hours", 24))
        stats = hooks_reader.get_aggregate_statistics(hours=hours)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting hook metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hooks/sessions")
def hook_sessions():
    """Get list of all hook sessions"""
    try:
        sessions = hooks_reader.get_all_sessions()
        return jsonify({"sessions": sessions, "total": len(sessions)})
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/hooks/session/<session_id>")
def hook_session_detail(session_id: str):
    """Get detailed timeline for a specific session"""
    try:
        summary = hooks_reader.read_session_summary(session_id)
        timeline = hooks_reader.get_session_timeline(session_id)

        if not summary:
            return jsonify({"error": "Session not found"}), 404

        return jsonify(
            {
                "session_id": session_id,
                "summary": {
                    "total_tools": summary.total_tools,
                    "tools_by_type": summary.tools_by_type,
                    "blocked_operations": summary.blocked_operations,
                    "tools_with_errors": summary.tools_with_errors,
                },
                "timeline": timeline,
            }
        )
    except Exception as e:
        logger.error(f"Error getting session detail: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/system")
def system_health():
    """Get system health metrics"""
    try:
        metrics = metrics_aggregator.get_system_health()
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/timeseries")
def timeseries_data():
    """Get time-series data for charts"""
    try:
        hours = int(request.args.get("hours", 24))
        interval = int(request.args.get("interval", 60))
        data = metrics_aggregator.get_time_series_data(hours=hours, interval_minutes=interval)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error getting timeseries data: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/claude-sessions")
def claude_sessions_metrics():
    """Get Claude Code session metrics"""
    try:
        hours = int(request.args.get("hours", 24))

        # Get sessions from hooks reader
        sessions_stats = hooks_reader.get_aggregate_statistics(hours=hours)

        return jsonify(
            {
                "total_sessions": sessions_stats["total_sessions"],
                "total_tool_calls": sessions_stats["total_tool_calls"],
                "tools_by_type": sessions_stats["tools_by_type"],
                "blocked_operations": sessions_stats["total_blocked_operations"],
                "errors": sessions_stats["total_errors"],
                "time_window_hours": hours,
                "recent_sessions": sessions_stats["recent_sessions"],
            }
        )

    except Exception as e:
        logger.error(f"Error getting Claude sessions metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/running")
def running_tasks():
    """Get list of currently running tasks"""
    try:
        # Get pagination parameters
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))

        # End any stale read transaction to see latest writes
        task_manager.db.conn.rollback()

        # Get tasks with status 'running' or 'pending' from database
        cursor = task_manager.db.conn.cursor()
        cursor.execute(
            """
            SELECT task_id, description, status, agent_type, model, created_at, updated_at, activity_log
            FROM tasks
            WHERE status IN ('running', 'pending')
            ORDER BY created_at DESC
        """
        )

        running = []
        for row in cursor.fetchall():
            task_id, description, status, agent_type, model, created_at, updated_at, activity_log_json = row
            activity_log = json.loads(activity_log_json) if activity_log_json else []

            # Get latest activity message
            latest_activity = None
            if activity_log and len(activity_log) > 0:
                latest_activity = activity_log[-1]["message"]

            running.append(
                {
                    "task_id": task_id,
                    "description": description,
                    "status": status,
                    "worker_type": agent_type,  # Keep old name for compatibility
                    "model": model,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "latest_activity": latest_activity,
                }
            )

        # Apply pagination
        total = len(running)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = running[start:end]

        return jsonify({"tasks": paginated, "total": total, "page": page, "page_size": page_size})

    except Exception as e:
        logger.error(f"Error getting running tasks: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/completed")
def completed_tasks():
    """Get list of completed tasks"""
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))

        # End any stale read transaction to see latest writes
        task_manager.db.conn.rollback()

        # Get completed tasks from database
        cursor = task_manager.db.conn.cursor()
        cursor.execute(
            """
            SELECT task_id, description, status, agent_type, model, created_at, updated_at, activity_log
            FROM tasks
            WHERE status = 'completed'
            ORDER BY updated_at DESC
        """
        )

        completed = []
        for row in cursor.fetchall():
            task_id, description, status, agent_type, model, created_at, updated_at, activity_log_json = row
            activity_log = json.loads(activity_log_json) if activity_log_json else []

            latest_activity = None
            if activity_log and len(activity_log) > 0:
                latest_activity = activity_log[-1]["message"]

            completed.append(
                {
                    "task_id": task_id,
                    "description": description,
                    "status": status,
                    "worker_type": agent_type,
                    "model": model,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "latest_activity": latest_activity,
                }
            )

        # Apply pagination
        total = len(completed)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = completed[start:end]

        return jsonify({"tasks": paginated, "total": total, "page": page, "page_size": page_size})

    except Exception as e:
        logger.error(f"Error getting completed tasks: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/failed")
def failed_tasks():
    """Get list of failed/stopped tasks"""
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))

        # End any stale read transaction to see latest writes
        task_manager.db.conn.rollback()

        # Get failed/stopped tasks from database
        cursor = task_manager.db.conn.cursor()
        cursor.execute(
            """
            SELECT task_id, description, status, agent_type, model, created_at, updated_at, activity_log
            FROM tasks
            WHERE status IN ('failed', 'stopped')
            ORDER BY updated_at DESC
        """
        )

        failed = []
        for row in cursor.fetchall():
            task_id, description, status, agent_type, model, created_at, updated_at, activity_log_json = row
            activity_log = json.loads(activity_log_json) if activity_log_json else []

            latest_activity = None
            if activity_log and len(activity_log) > 0:
                latest_activity = activity_log[-1]["message"]

            failed.append(
                {
                    "task_id": task_id,
                    "description": description,
                    "status": status,
                    "worker_type": agent_type,
                    "model": model,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "latest_activity": latest_activity,
                }
            )

        # Apply pagination
        total = len(failed)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = failed[start:end]

        return jsonify({"tasks": paginated, "total": total, "page": page, "page_size": page_size})

    except Exception as e:
        logger.error(f"Error getting failed tasks: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/all")
def all_tasks():
    """Get list of all tasks"""
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))

        # End any stale read transaction to see latest writes
        task_manager.db.conn.rollback()

        # Get all tasks from database
        cursor = task_manager.db.conn.cursor()
        cursor.execute(
            """
            SELECT task_id, description, status, agent_type, model, created_at, updated_at, activity_log
            FROM tasks
            ORDER BY updated_at DESC
        """
        )

        all_tasks_list = []
        for row in cursor.fetchall():
            task_id, description, status, agent_type, model, created_at, updated_at, activity_log_json = row
            activity_log = json.loads(activity_log_json) if activity_log_json else []

            latest_activity = None
            if activity_log and len(activity_log) > 0:
                latest_activity = activity_log[-1]["message"]

            all_tasks_list.append(
                {
                    "task_id": task_id,
                    "description": description,
                    "status": status,
                    "worker_type": agent_type,
                    "model": model,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "latest_activity": latest_activity,
                }
            )

        # Apply pagination
        total = len(all_tasks_list)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = all_tasks_list[start:end]

        return jsonify({"tasks": paginated, "total": total, "page": page, "page_size": page_size})

    except Exception as e:
        logger.error(f"Error getting all tasks: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<task_id>")
def task_detail(task_id: str):
    """Get detailed information about a specific task"""
    try:
        # Get task from database
        task_dict = task_manager.db.get_task(task_id)

        if not task_dict:
            return jsonify({"error": "Task not found"}), 404

        return jsonify(task_dict)

    except Exception as e:
        logger.error(f"Error getting task detail: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/docs/list")
def list_docs():
    """Get list of all documentation files"""
    try:
        # Determine docs directory based on where we're running from
        if Path.cwd().name == "telegram_bot":
            docs_dir = Path("../docs")
        else:
            docs_dir = Path("docs")

        if not docs_dir.exists():
            return jsonify({"error": "Documentation directory not found"}), 404

        # Recursively find all markdown and text files
        doc_files = []
        for ext in ["*.md", "*.txt"]:
            doc_files.extend(docs_dir.rglob(ext))

        # Build file tree structure
        files = []
        for file_path in sorted(doc_files):
            relative_path = file_path.relative_to(docs_dir)
            stat = file_path.stat()

            files.append(
                {
                    "path": str(relative_path),
                    "name": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "is_archive": "archive" in str(relative_path),
                }
            )

        return jsonify({"files": files, "total": len(files)})

    except Exception as e:
        logger.error(f"Error listing documentation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/docs/content")
def get_doc_content():
    """Get content of a specific documentation file"""
    try:
        doc_path = request.args.get("path")
        if not doc_path:
            return jsonify({"error": "Missing path parameter"}), 400

        # Determine docs directory based on where we're running from
        if Path.cwd().name == "telegram_bot":
            docs_dir = Path("../docs")
        else:
            docs_dir = Path("docs")

        # Security: Prevent directory traversal
        file_path = (docs_dir / doc_path).resolve()
        if not file_path.is_relative_to(docs_dir.resolve()):
            return jsonify({"error": "Invalid path"}), 403

        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404

        # Read file content
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        return jsonify(
            {
                "path": str(doc_path),
                "name": file_path.name,
                "content": content,
                "size": file_path.stat().st_size,
            }
        )

    except Exception as e:
        logger.error(f"Error reading documentation: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "service": "YetAnotherCodingBot-monitoring",
            "version": "1.0.0",
        }
    )


def generate_sse_updates(hours: int = 24) -> Generator[str, None, None]:
    """
    Generator function that yields SSE-formatted metric updates.
    Polls metrics every 2 seconds and sends updates only when data changes.
    """
    global last_metrics_snapshot

    while True:
        try:
            # Reload tasks to get latest state
            task_manager.reload_tasks()

            # Gather all metrics
            overview = metrics_aggregator.get_complete_snapshot(hours=hours)
            sessions_stats = hooks_reader.get_aggregate_statistics(hours=hours)
            sessions_metrics = {
                "total_sessions": sessions_stats["total_sessions"],
                "total_tool_calls": sessions_stats["total_tool_calls"],
                "tools_by_type": sessions_stats["tools_by_type"],
                "blocked_operations": sessions_stats["total_blocked_operations"],
                "errors": sessions_stats["total_errors"],
                "time_window_hours": hours,
                "recent_sessions": sessions_stats["recent_sessions"],
            }
            activity = []

            # Get recent task activity from database
            limit = 20

            # End any stale read transaction to see latest writes
            task_manager.db.conn.rollback()

            cursor = task_manager.db.conn.cursor()
            cursor.execute(
                """
                SELECT task_id, description, status, activity_log
                FROM tasks
                ORDER BY updated_at DESC
                LIMIT ?
            """,
                (limit,),
            )

            for row in cursor.fetchall():
                task_id, description, status, activity_log_json = row
                activity_log = json.loads(activity_log_json) if activity_log_json else []

                if activity_log:
                    for activity_entry in reversed(activity_log[-10:]):
                        activity.append(
                            {
                                "task_id": task_id,
                                "description": description[:50],
                                "status": status,
                                "timestamp": activity_entry["timestamp"],
                                "message": activity_entry["message"],
                                "output_lines": activity_entry.get("output_lines"),
                            }
                        )

            activity.sort(key=lambda x: x["timestamp"], reverse=True)
            activity = activity[:limit]

            # Create current snapshot
            current_snapshot = {
                "overview": overview.to_dict(),
                "sessions": sessions_metrics,
                "activity": activity,
                "timestamp": time.time(),
            }

            # Convert to JSON for comparison
            current_json = json.dumps(current_snapshot, sort_keys=True)
            last_json = json.dumps(last_metrics_snapshot, sort_keys=True) if last_metrics_snapshot else None

            # Only send if data has changed or this is the first update
            if current_json != last_json:
                last_metrics_snapshot = current_snapshot

                # Format as SSE event
                data = json.dumps(current_snapshot)
                yield f"data: {data}\n\n"

                logger.debug("Sent SSE update - metrics changed")
            else:
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"
                logger.debug("Sent SSE heartbeat - no changes")

        except Exception as e:
            logger.error(f"Error generating SSE update: {e}")
            error_data = json.dumps({"error": str(e)})
            yield f"event: error\ndata: {error_data}\n\n"

        # Poll every 2 seconds for much faster updates than 30s
        time.sleep(2)


@app.route("/api/stream/metrics")
def stream_metrics():
    """
    Server-Sent Events endpoint for real-time metrics updates.
    Clients connect via EventSource and receive updates whenever metrics change.
    """
    hours = int(request.args.get("hours", 24))

    return Response(
        generate_sse_updates(hours=hours),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )


def run_server(host: str = "0.0.0.0", port: int = 3000, debug: bool = False):  # nosec B104
    """Run the monitoring server"""
    logger.info(f"Starting monitoring server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    # Get configuration from environment
    host = os.getenv("MONITORING_HOST", "0.0.0.0")  # nosec B104
    port = int(os.getenv("MONITORING_PORT", "3000"))
    debug = os.getenv("MONITORING_DEBUG", "false").lower() == "true"

    run_server(host=host, port=port, debug=debug)
