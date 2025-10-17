"""
Flask-based monitoring server for bot metrics
Provides web UI and REST API for real-time metrics
"""

import logging
import os
from pathlib import Path

from cost_tracker import CostTracker
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from metrics_aggregator import MetricsAggregator
from tasks import TaskManager
from tool_usage_tracker import ToolUsageTracker

# Load environment variables from parent directory's .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)  # Enable CORS for API access

# Initialize tracking systems (use parent directory for data)
cost_tracker = CostTracker(data_dir="../data")
task_manager = TaskManager(data_dir="../data")
tool_usage_tracker = ToolUsageTracker(data_dir="../data")

# Initialize metrics aggregator
metrics_aggregator = MetricsAggregator(cost_tracker, task_manager, tool_usage_tracker)


@app.route("/")
def index():
    """Serve the main dashboard"""
    return render_template("dashboard.html")


@app.route("/telegram")
def telegram():
    """Serve the Telegram Web embed page"""
    return render_template("telegram.html")


@app.route("/api/metrics/overview")
def metrics_overview():
    """Get overview of all metrics"""
    try:
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
        metrics = metrics_aggregator.get_task_statistics()
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting task metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/tools")
def tool_metrics():
    """Get tool usage metrics"""
    try:
        hours = int(request.args.get("hours", 24))
        metrics = metrics_aggregator.get_tool_usage_metrics(hours=hours)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting tool metrics: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/metrics/hooks")
def hook_metrics():
    """Get hook usage metrics"""
    try:
        metrics = metrics_aggregator.get_hook_usage_summary()
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting hook metrics: {e}")
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


@app.route("/api/metrics/usage-api")
def usage_api_metrics():
    """Get real-time usage from Anthropic Usage API"""
    try:
        import os
        from datetime import datetime

        from usage_api import ClaudeUsageAPI

        # Check if admin API key is configured
        admin_key = os.getenv("ANTHROPIC_ADMIN_API_KEY")
        if not admin_key:
            return jsonify({"error": "ANTHROPIC_ADMIN_API_KEY not configured", "configured": False})

        # Initialize Usage API client
        usage_api = ClaudeUsageAPI(admin_api_key=admin_key)

        # Get current month data
        now = datetime.now()
        start_of_month = datetime(now.year, now.month, 1)

        # Get usage and cost reports
        usage_data = usage_api.get_usage_report(
            starting_at=start_of_month, ending_at=now, bucket_width="1d", group_by=["model"]
        )

        cost_data = usage_api.get_cost_report(starting_at=start_of_month, ending_at=now)

        # Calculate totals
        total_input = 0
        total_output = 0
        total_cached = 0
        model_breakdown = {}

        for bucket in usage_data.get("buckets", []):
            for group in bucket.get("groups", []):
                model = group.get("model", "unknown")
                metrics = group.get("metrics", {})

                input_tokens = metrics.get("input_tokens", 0)
                output_tokens = metrics.get("output_tokens", 0)
                cached_tokens = metrics.get("cached_input_tokens", 0)

                total_input += input_tokens
                total_output += output_tokens
                total_cached += cached_tokens

                if model not in model_breakdown:
                    model_breakdown[model] = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}

                model_breakdown[model]["input_tokens"] += input_tokens
                model_breakdown[model]["output_tokens"] += output_tokens
                model_breakdown[model]["cached_tokens"] += cached_tokens

        return jsonify(
            {
                "configured": True,
                "total_cost": float(cost_data.get("total_cost", "0.00")),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_cached_tokens": total_cached,
                "total_tokens": total_input + total_output + total_cached,
                "model_breakdown": model_breakdown,
                "period": {"start": start_of_month.isoformat(), "end": now.isoformat()},
            }
        )

    except Exception as e:
        logger.error(f"Error getting Usage API metrics: {e}")
        return jsonify({"error": str(e), "configured": False}), 500


@app.route("/api/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "service": "bot-monitoring",
            "version": "1.0.0",
        }
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
