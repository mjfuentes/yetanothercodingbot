"""
Monitoring, health checks, and error tracking
Phase 7: Production hardening
"""

import json
import logging
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


@dataclass
class ErrorRecord:
    """Error tracking record"""

    timestamp: str
    error_type: str
    error_message: str
    user_id: int | None
    context: str
    stack_trace: str | None = None


@dataclass
class PerformanceMetric:
    """Performance metric record"""

    timestamp: str
    metric_name: str
    value: float
    unit: str


class HealthMonitor:
    """Monitor system health and track errors/performance"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.errors_file = self.data_dir / "errors.json"
        self.metrics_file = self.data_dir / "metrics.json"

        self.errors: list[ErrorRecord] = []
        self.metrics: list[PerformanceMetric] = []
        self.start_time = datetime.now()
        self.request_count = 0
        self.error_count = 0

        # Load existing data
        self._load_data()

        logger.info("HealthMonitor initialized")

    def _load_data(self):
        """Load monitoring data from disk"""
        # Load errors
        if self.errors_file.exists():
            try:
                with open(self.errors_file) as f:
                    data = json.load(f)
                    self.errors = [ErrorRecord(**e) for e in data]
                logger.info(f"Loaded {len(self.errors)} error records")
            except Exception as e:
                logger.error(f"Error loading error records: {e}")

        # Load metrics
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file) as f:
                    data = json.load(f)
                    self.metrics = [PerformanceMetric(**m) for m in data]
                logger.info(f"Loaded {len(self.metrics)} performance metrics")
            except Exception as e:
                logger.error(f"Error loading metrics: {e}")

    def _save_errors(self):
        """Save error records to disk"""
        try:
            # Keep only last 1000 errors
            if len(self.errors) > 1000:
                self.errors = self.errors[-1000:]

            data = [asdict(e) for e in self.errors]
            with open(self.errors_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving error records: {e}")

    def _save_metrics(self):
        """Save performance metrics to disk"""
        try:
            # Keep only last 1000 metrics
            if len(self.metrics) > 1000:
                self.metrics = self.metrics[-1000:]

            data = [asdict(m) for m in self.metrics]
            with open(self.metrics_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")

    def record_error(self, error: Exception, user_id: int | None = None, context: str = "unknown"):
        """Record an error"""
        import traceback

        self.error_count += 1

        error_record = ErrorRecord(
            timestamp=datetime.now().isoformat(),
            error_type=type(error).__name__,
            error_message=str(error),
            user_id=user_id,
            context=context,
            stack_trace=traceback.format_exc(),
        )

        self.errors.append(error_record)
        self._save_errors()

        logger.error(f"Recorded error in {context}: {error}")

    def record_metric(self, name: str, value: float, unit: str = ""):
        """Record a performance metric"""
        metric = PerformanceMetric(timestamp=datetime.now().isoformat(), metric_name=name, value=value, unit=unit)

        self.metrics.append(metric)
        self._save_metrics()

        logger.debug(f"Recorded metric: {name}={value}{unit}")

    def record_request(self):
        """Record that a request was processed"""
        self.request_count += 1

    def get_health_status(self) -> dict:
        """Get current health status"""
        try:
            # System info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Process info
            process = psutil.Process()
            process_memory = process.memory_info()

            # Uptime
            uptime = datetime.now() - self.start_time
            uptime_seconds = int(uptime.total_seconds())

            # Error rate (last hour)
            one_hour_ago = datetime.now() - timedelta(hours=1)
            recent_errors = [e for e in self.errors if datetime.fromisoformat(e.timestamp) > one_hour_ago]

            # Request rate
            requests_per_minute = self.request_count / max(uptime_seconds / 60, 1)

            return {
                "status": "healthy" if cpu_percent < 90 and memory.percent < 90 else "degraded",
                "uptime_seconds": uptime_seconds,
                "uptime_human": str(uptime).split(".")[0],  # Remove microseconds
                "requests_total": self.request_count,
                "requests_per_minute": round(requests_per_minute, 2),
                "errors_total": self.error_count,
                "errors_last_hour": len(recent_errors),
                "system": {
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_used_mb": memory.used // (1024 * 1024),
                    "memory_total_mb": memory.total // (1024 * 1024),
                    "disk_percent": disk.percent,
                    "disk_free_gb": disk.free // (1024 * 1024 * 1024),
                },
                "process": {
                    "memory_mb": process_memory.rss // (1024 * 1024),
                    "threads": process.num_threads(),
                    "pid": process.pid,
                },
                "platform": {
                    "system": platform.system(),
                    "python_version": sys.version.split()[0],
                    "hostname": platform.node(),
                },
            }
        except Exception as e:
            logger.error(f"Error getting health status: {e}")
            return {"status": "error", "error": str(e)}

    def get_recent_errors(self, limit: int = 10) -> list[ErrorRecord]:
        """Get recent errors"""
        return self.errors[-limit:]

    def get_error_summary(self) -> dict:
        """Get error summary statistics"""
        # Last 24 hours
        one_day_ago = datetime.now() - timedelta(days=1)
        recent_errors = [e for e in self.errors if datetime.fromisoformat(e.timestamp) > one_day_ago]

        # Count by type
        error_types = {}
        for error in recent_errors:
            error_types[error.error_type] = error_types.get(error.error_type, 0) + 1

        # Count by context
        error_contexts = {}
        for error in recent_errors:
            error_contexts[error.context] = error_contexts.get(error.context, 0) + 1

        return {
            "total_errors_24h": len(recent_errors),
            "total_errors_all_time": len(self.errors),
            "error_types": error_types,
            "error_contexts": error_contexts,
        }

    def get_performance_metrics(self) -> dict:
        """Get performance metrics summary"""
        # Last hour metrics
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_metrics = [m for m in self.metrics if datetime.fromisoformat(m.timestamp) > one_hour_ago]

        # Group by metric name
        metrics_by_name = {}
        for metric in recent_metrics:
            if metric.metric_name not in metrics_by_name:
                metrics_by_name[metric.metric_name] = []
            metrics_by_name[metric.metric_name].append(metric.value)

        # Calculate averages
        averages = {}
        for name, values in metrics_by_name.items():
            if values:
                averages[name] = {
                    "avg": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }

        return {"metrics_last_hour": len(recent_metrics), "averages": averages}

    def check_alerts(self) -> list[str]:
        """Check for alert conditions"""
        alerts = []

        try:
            # CPU alert
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                alerts.append(f"High CPU usage: {cpu_percent}%")

            # Memory alert
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                alerts.append(f"High memory usage: {memory.percent}%")

            # Disk alert
            disk = psutil.disk_usage("/")
            if disk.percent > 90:
                alerts.append(f"Low disk space: {disk.percent}% used")

            # Error rate alert
            one_hour_ago = datetime.now() - timedelta(hours=1)
            recent_errors = [e for e in self.errors if datetime.fromisoformat(e.timestamp) > one_hour_ago]
            if len(recent_errors) > 50:
                alerts.append(f"High error rate: {len(recent_errors)} errors in last hour")

        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
            alerts.append(f"Error checking system health: {str(e)}")

        return alerts
