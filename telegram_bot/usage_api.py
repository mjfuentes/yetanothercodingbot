"""
Claude Usage and Cost API integration
Provides programmatic access to historical API usage and cost data
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


class ClaudeUsageAPI:
    """Client for Anthropic Usage and Cost Admin API"""

    def __init__(self, admin_api_key: str | None = None):
        """
        Initialize Usage API client

        Args:
            admin_api_key: Admin API key (prefix: sk-ant-admin...).
                          If not provided, reads from ANTHROPIC_ADMIN_API_KEY env var.
        """
        self.admin_api_key = admin_api_key or os.getenv("ANTHROPIC_ADMIN_API_KEY")
        if not self.admin_api_key:
            raise ValueError("ANTHROPIC_ADMIN_API_KEY not set")

        if not self.admin_api_key.startswith("sk-ant-admin"):
            logger.warning("API key does not appear to be an admin key (should start with sk-ant-admin)")

        self.client = anthropic.Anthropic(api_key=self.admin_api_key)
        self.base_url = "https://api.anthropic.com/v1/organizations"

    def get_usage_report(
        self,
        starting_at: datetime,
        ending_at: datetime,
        bucket_width: str = "1d",
        group_by: list[str] | None = None,
        models: list[str] | None = None,
        service_tiers: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get usage report for specified time range

        Args:
            starting_at: Start timestamp
            ending_at: End timestamp
            bucket_width: Time aggregation interval ('1m', '1h', or '1d')
            group_by: Optional grouping dimensions (model, workspace, service_tier, context_window)
            models: Optional filter by specific models
            service_tiers: Optional filter by service tier (e.g., batch, priority)

        Returns:
            Usage report data including token consumption
        """
        try:
            # Format timestamps as ISO 8601
            start_iso = starting_at.isoformat()
            end_iso = ending_at.isoformat()

            # Build request parameters
            params: dict[str, Any] = {
                "starting_at": start_iso,
                "ending_at": end_iso,
                "bucket_width": bucket_width,
            }

            if group_by:
                params["group_by"] = group_by
            if models:
                params["models"] = models
            if service_tiers:
                params["service_tiers"] = service_tiers

            logger.info(f"Fetching usage report from {start_iso} to {end_iso} (bucket: {bucket_width})")

            # Make API request
            # Note: This uses the beta admin API which may require special client setup
            response = self.client.with_options(
                default_headers={
                    "anthropic-version": "2023-06-01",
                }
            ).get(f"{self.base_url}/usage_report/messages", params=params)

            logger.info("Successfully retrieved usage report")
            return response

        except Exception as e:
            logger.error(f"Error fetching usage report: {e}")
            raise

    def get_cost_report(
        self,
        starting_at: datetime,
        ending_at: datetime,
        group_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get cost report for specified time range

        Args:
            starting_at: Start timestamp
            ending_at: End timestamp
            group_by: Optional grouping by workspace_id or description

        Returns:
            Cost report data in USD (decimal strings, lowest units in cents)
        """
        try:
            # Format timestamps as ISO 8601
            start_iso = starting_at.isoformat()
            end_iso = ending_at.isoformat()

            # Build request parameters
            params: dict[str, Any] = {
                "starting_at": start_iso,
                "ending_at": end_iso,
            }

            if group_by:
                params["group_by"] = group_by

            logger.info(f"Fetching cost report from {start_iso} to {end_iso}")

            # Make API request
            response = self.client.with_options(
                default_headers={
                    "anthropic-version": "2023-06-01",
                }
            ).get(f"{self.base_url}/cost_report", params=params)

            logger.info("Successfully retrieved cost report")
            return response

        except Exception as e:
            logger.error(f"Error fetching cost report: {e}")
            raise

    def get_daily_usage(self, days_back: int = 7) -> dict[str, Any]:
        """
        Convenience method to get daily usage for the last N days

        Args:
            days_back: Number of days to look back (default: 7)

        Returns:
            Daily usage report
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days_back)

        return self.get_usage_report(
            starting_at=start_time,
            ending_at=end_time,
            bucket_width="1d",
            group_by=["model"],
        )

    def get_daily_costs(self, days_back: int = 7) -> dict[str, Any]:
        """
        Convenience method to get daily costs for the last N days

        Args:
            days_back: Number of days to look back (default: 7)

        Returns:
            Daily cost report
        """
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days_back)

        return self.get_cost_report(
            starting_at=start_time,
            ending_at=end_time,
        )

    def get_current_month_usage(self) -> dict[str, Any]:
        """
        Get usage for the current calendar month

        Returns:
            Monthly usage report
        """
        now = datetime.now()
        start_of_month = datetime(now.year, now.month, 1)

        return self.get_usage_report(
            starting_at=start_of_month,
            ending_at=now,
            bucket_width="1d",
            group_by=["model"],
        )

    def get_current_month_costs(self) -> dict[str, Any]:
        """
        Get costs for the current calendar month

        Returns:
            Monthly cost report
        """
        now = datetime.now()
        start_of_month = datetime(now.year, now.month, 1)

        return self.get_cost_report(
            starting_at=start_of_month,
            ending_at=now,
        )


def format_usage_summary(usage_data: dict[str, Any]) -> str:
    """
    Format usage data into a human-readable summary

    Args:
        usage_data: Raw usage data from API

    Returns:
        Formatted summary string
    """
    try:
        summary_lines = ["Usage Summary\n"]

        # Extract buckets (time periods)
        buckets = usage_data.get("buckets", [])
        if not buckets:
            return "No usage data found"

        total_input = 0
        total_output = 0
        total_cached = 0

        for bucket in buckets:
            # Sum up tokens across all models in this bucket
            for group in bucket.get("groups", []):
                metrics = group.get("metrics", {})
                total_input += metrics.get("input_tokens", 0)
                total_output += metrics.get("output_tokens", 0)
                total_cached += metrics.get("cached_input_tokens", 0)

        # Format totals
        summary_lines.append(f"Total Input Tokens: {total_input:,}")
        summary_lines.append(f"Total Output Tokens: {total_output:,}")
        summary_lines.append(f"Total Cached Tokens: {total_cached:,}")
        summary_lines.append(f"Total Tokens: {total_input + total_output + total_cached:,}")

        return "\n".join(summary_lines)

    except Exception as e:
        logger.error(f"Error formatting usage summary: {e}")
        return f"Error formatting usage data: {str(e)}"


def format_cost_summary(cost_data: dict[str, Any]) -> str:
    """
    Format cost data into a human-readable summary

    Args:
        cost_data: Raw cost data from API

    Returns:
        Formatted summary string
    """
    try:
        summary_lines = ["Cost Summary\n"]

        # Extract total cost
        total_cost = cost_data.get("total_cost", "0.00")
        summary_lines.append(f"Total Cost: ${total_cost}")

        # Extract breakdown if available
        breakdown = cost_data.get("breakdown", [])
        if breakdown:
            summary_lines.append("\nBreakdown:")
            for item in breakdown:
                description = item.get("description", "Unknown")
                cost = item.get("cost", "0.00")
                summary_lines.append(f"  {description}: ${cost}")

        return "\n".join(summary_lines)

    except Exception as e:
        logger.error(f"Error formatting cost summary: {e}")
        return f"Error formatting cost data: {str(e)}"
