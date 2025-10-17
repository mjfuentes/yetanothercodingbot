"""
Cost tracking and limits for API usage
Phase 7: Production hardening
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Model pricing (per 1M tokens)
PRICING = {
    "haiku": {
        "input": 0.80,   # $0.80 per 1M input tokens
        "output": 4.00,  # $4.00 per 1M output tokens
    },
    "sonnet": {
        "input": 3.00,   # $3 per 1M input tokens
        "output": 15.00, # $15 per 1M output tokens
    },
}

# Default limits (can be overridden per user)
DEFAULT_LIMITS = {
    "daily": 100.0,    # $100/day
    "monthly": 1000.0, # $1000/month
}

# Warning threshold
WARNING_THRESHOLD = 0.8  # Warn at 80% of limit


@dataclass
class UsageRecord:
    """Single usage record"""
    timestamp: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float
    request_type: str  # 'chat', 'code_task', 'orchestration'


@dataclass
class UserUsage:
    """User usage statistics"""
    user_id: int
    total_requests: int
    total_cost: float
    daily_cost: float
    monthly_cost: float
    records: list[UsageRecord]
    limits: dict  # Custom limits per user
    last_reset: str
    last_warning: Optional[str] = None  # Timestamp of last warning

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'UserUsage':
        records = [UsageRecord(**r) for r in data.get('records', [])]
        return cls(
            user_id=data['user_id'],
            total_requests=data['total_requests'],
            total_cost=data['total_cost'],
            daily_cost=data['daily_cost'],
            monthly_cost=data['monthly_cost'],
            records=records,
            limits=data.get('limits', DEFAULT_LIMITS.copy()),
            last_reset=data['last_reset'],
            last_warning=data.get('last_warning')
        )


class CostTracker:
    """Track API usage costs and enforce limits"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.usage_file = self.data_dir / "usage.json"
        self.users: Dict[int, UserUsage] = {}

        # Load existing usage data
        self._load_usage()

        logger.info(f"CostTracker initialized with {len(self.users)} users")

    def _load_usage(self):
        """Load usage data from disk"""
        if not self.usage_file.exists():
            return

        try:
            with open(self.usage_file, 'r') as f:
                data = json.load(f)
                for user_id_str, usage_data in data.items():
                    user_id = int(user_id_str)
                    self.users[user_id] = UserUsage.from_dict(usage_data)

            logger.info(f"Loaded usage data for {len(self.users)} users")
        except Exception as e:
            logger.error(f"Error loading usage data: {e}")

    def _save_usage(self):
        """Save usage data to disk"""
        try:
            data = {
                str(user_id): usage.to_dict()
                for user_id, usage in self.users.items()
            }

            with open(self.usage_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving usage data: {e}")

    def _get_or_create_usage(self, user_id: int) -> UserUsage:
        """Get or create usage record for user"""
        if user_id not in self.users:
            self.users[user_id] = UserUsage(
                user_id=user_id,
                total_requests=0,
                total_cost=0.0,
                daily_cost=0.0,
                monthly_cost=0.0,
                records=[],
                limits=DEFAULT_LIMITS.copy(),
                last_reset=datetime.now().isoformat()
            )
            self._save_usage()

        return self.users[user_id]

    def _reset_daily_costs(self, usage: UserUsage):
        """Reset daily costs if needed"""
        last_reset = datetime.fromisoformat(usage.last_reset)
        now = datetime.now()

        # Reset if last reset was yesterday or earlier
        if last_reset.date() < now.date():
            usage.daily_cost = 0.0
            usage.last_reset = now.isoformat()
            logger.info(f"Reset daily costs for user {usage.user_id}")

    def _reset_monthly_costs(self, usage: UserUsage):
        """Reset monthly costs if needed"""
        last_reset = datetime.fromisoformat(usage.last_reset)
        now = datetime.now()

        # Reset if we're in a new month
        if (last_reset.year, last_reset.month) < (now.year, now.month):
            usage.monthly_cost = 0.0
            usage.last_reset = now.isoformat()
            logger.info(f"Reset monthly costs for user {usage.user_id}")

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text (rough approximation)"""
        # Rough estimate: ~4 characters per token for English text
        return max(1, len(text) // 4)

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for API call"""
        if model not in PRICING:
            logger.warning(f"Unknown model: {model}, defaulting to sonnet pricing")
            model = "sonnet"

        pricing = PRICING[model]
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def record_usage(
        self,
        user_id: int,
        model: str,
        input_tokens: int,
        output_tokens: int,
        request_type: str = "chat"
    ) -> float:
        """Record API usage and return cost"""
        usage = self._get_or_create_usage(user_id)

        # Reset periods if needed
        self._reset_daily_costs(usage)
        self._reset_monthly_costs(usage)

        # Calculate cost
        cost = self.calculate_cost(model, input_tokens, output_tokens)

        # Create record
        record = UsageRecord(
            timestamp=datetime.now().isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            request_type=request_type
        )

        # Update usage
        usage.records.append(record)
        usage.total_requests += 1
        usage.total_cost += cost
        usage.daily_cost += cost
        usage.monthly_cost += cost

        # Keep only last 1000 records
        if len(usage.records) > 1000:
            usage.records = usage.records[-1000:]

        self._save_usage()

        logger.info(f"Recorded usage for user {user_id}: {model} ${cost:.4f} (daily: ${usage.daily_cost:.2f})")

        return cost

    def check_limits(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        Check if user is within limits
        Returns: (allowed, warning_message)
        """
        usage = self._get_or_create_usage(user_id)

        # Reset periods if needed
        self._reset_daily_costs(usage)
        self._reset_monthly_costs(usage)

        # Check daily limit
        if usage.daily_cost >= usage.limits["daily"]:
            return False, f"Daily limit exceeded (${usage.limits['daily']:.2f}). Resets at midnight."

        # Check monthly limit
        if usage.monthly_cost >= usage.limits["monthly"]:
            return False, f"Monthly limit exceeded (${usage.limits['monthly']:.2f}). Resets next month."

        # Check if approaching limits (warn at 80%)
        warning_msg = None
        daily_percentage = usage.daily_cost / usage.limits["daily"]
        monthly_percentage = usage.monthly_cost / usage.limits["monthly"]

        if daily_percentage >= WARNING_THRESHOLD:
            warning_msg = f"⚠️ Approaching daily limit: ${usage.daily_cost:.2f} / ${usage.limits['daily']:.2f} ({daily_percentage*100:.0f}%)"
        elif monthly_percentage >= WARNING_THRESHOLD:
            warning_msg = f"⚠️ Approaching monthly limit: ${usage.monthly_cost:.2f} / ${usage.limits['monthly']:.2f} ({monthly_percentage*100:.0f}%)"

        # Only warn once per hour
        if warning_msg:
            now = datetime.now()
            if usage.last_warning:
                last_warning_time = datetime.fromisoformat(usage.last_warning)
                if now - last_warning_time < timedelta(hours=1):
                    warning_msg = None  # Already warned recently
                else:
                    usage.last_warning = now.isoformat()
                    self._save_usage()
            else:
                usage.last_warning = now.isoformat()
                self._save_usage()

        return True, warning_msg

    def get_usage_stats(self, user_id: int) -> dict:
        """Get usage statistics for user"""
        usage = self._get_or_create_usage(user_id)

        # Reset periods if needed
        self._reset_daily_costs(usage)
        self._reset_monthly_costs(usage)

        # Calculate model breakdown
        model_stats = {}
        for record in usage.records:
            if record.model not in model_stats:
                model_stats[record.model] = {
                    "requests": 0,
                    "cost": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0
                }
            model_stats[record.model]["requests"] += 1
            model_stats[record.model]["cost"] += record.cost
            model_stats[record.model]["input_tokens"] += record.input_tokens
            model_stats[record.model]["output_tokens"] += record.output_tokens

        # Recent activity (last 24 hours)
        now = datetime.now()
        recent_records = [
            r for r in usage.records
            if (now - datetime.fromisoformat(r.timestamp)) < timedelta(hours=24)
        ]

        return {
            "user_id": user_id,
            "total_requests": usage.total_requests,
            "total_cost": usage.total_cost,
            "daily_cost": usage.daily_cost,
            "monthly_cost": usage.monthly_cost,
            "daily_limit": usage.limits["daily"],
            "monthly_limit": usage.limits["monthly"],
            "daily_percentage": (usage.daily_cost / usage.limits["daily"]) * 100,
            "monthly_percentage": (usage.monthly_cost / usage.limits["monthly"]) * 100,
            "model_breakdown": model_stats,
            "recent_24h": len(recent_records),
            "last_reset": usage.last_reset
        }

    def set_user_limits(self, user_id: int, daily: Optional[float] = None, monthly: Optional[float] = None):
        """Set custom limits for a user"""
        usage = self._get_or_create_usage(user_id)

        if daily is not None:
            usage.limits["daily"] = daily
        if monthly is not None:
            usage.limits["monthly"] = monthly

        self._save_usage()
        logger.info(f"Updated limits for user {user_id}: daily=${usage.limits['daily']}, monthly=${usage.limits['monthly']}")
