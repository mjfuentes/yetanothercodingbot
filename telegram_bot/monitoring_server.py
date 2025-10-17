"""
Flask-based monitoring server for bot metrics
Provides web UI and REST API for real-time metrics
"""

import logging
import os

from cost_tracker import CostTracker
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from metrics_aggregator import MetricsAggregator
from tasks import TaskManager
from tool_usage_tracker import ToolUsageTracker

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)  # Enable CORS for API access

# Initialize tracking systems
cost_tracker = CostTracker()
task_manager = TaskManager()
tool_usage_tracker = ToolUsageTracker()

# Initialize metrics aggregator
metrics_aggregator = MetricsAggregator(cost_tracker, task_manager, tool_usage_tracker)


@app.route("/")
def index():
    """Serve the main dashboard"""
    return render_template("dashboard.html")


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


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):  # nosec B104
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
    port = int(os.getenv("MONITORING_PORT", "5000"))
    debug = os.getenv("MONITORING_DEBUG", "false").lower() == "true"

    run_server(host=host, port=port, debug=debug)
