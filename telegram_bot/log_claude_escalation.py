"""
Claude-assisted escalation for log issues
For complex issues that need intelligent analysis, escalates to Claude API
Uses smart caching to minimize API calls
"""

import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

from log_analyzer import LogIssue, IssueLevel, IssueType
from orchestrator import invoke_orchestrator

logger = logging.getLogger(__name__)


class LogClaudeEscalation:
    """Handle Claude API escalation for complex log issues"""

    def __init__(self, bot_repo_path: str):
        self.bot_repo_path = bot_repo_path
        self.escalation_cache = {}  # Cache Claude responses
        self.cache_expiry = 3600  # Cache for 1 hour
        self.last_escalation_time = None

    async def analyze_issues_with_claude(
        self,
        issues: List[LogIssue],
        logs_context: Optional[str] = None
    ) -> Dict:
        """
        Send complex issues to Claude for intelligent analysis
        Returns recommendations and fixes
        """
        if not issues:
            return {"analysis": None, "recommendations": []}

        try:
            # Build prompt for Claude
            prompt = self._build_escalation_prompt(issues, logs_context)

            # Call orchestrator with Claude
            response = await invoke_orchestrator(
                user_query=prompt,
                input_method="text",
                conversation_history=[],
                current_workspace=self.bot_repo_path,
                bot_repository=self.bot_repo_path,
                workspace_path=self.bot_repo_path,
                task_manager=None  # Log analysis doesn't need task manager
            )

            if not response or response.strip() == "":
                logger.warning("Claude returned empty response for log escalation")
                return {"analysis": None, "recommendations": []}

            # Parse Claude's response
            analysis = self._parse_claude_response(response, issues)

            self.last_escalation_time = datetime.now()

            return {
                "analysis": response,
                "recommendations": analysis.get("recommendations", []),
                "severity_assessment": analysis.get("severity", "medium"),
                "suggested_fixes": analysis.get("fixes", [])
            }

        except Exception as e:
            logger.error(f"Error escalating to Claude: {e}")
            return {"analysis": None, "recommendations": []}

    def _build_escalation_prompt(self, issues: List[LogIssue], logs_context: Optional[str]) -> str:
        """Build a prompt for Claude to analyze the issues"""
        issues_text = "\n".join([
            f"• [{issue.level.value.upper()}] {issue.title}\n"
            f"  Description: {issue.description}\n"
            f"  Evidence: {'; '.join(issue.evidence[:2])}"
            for issue in issues
        ])

        prompt = f"""You are a bot debugging expert. Analyze these detected log issues and provide insights:

DETECTED ISSUES:
{issues_text}

Please provide:
1. Root cause analysis for each issue
2. Priority ranking (critical/high/medium/low)
3. Specific code fixes or configuration changes needed
4. Estimated impact on bot performance
5. Whether these issues might cascade into other problems

Format your response as JSON with keys:
- "analysis": detailed explanation
- "recommendations": [list of actionable recommendations]
- "severity": overall severity assessment
- "fixes": [specific code changes needed]
- "impact": estimated impact on bot performance
- "cascade_risk": risk of issues causing other problems

Be concise and technical."""

        if logs_context:
            prompt += f"\n\nLOG CONTEXT:\n{logs_context}"

        return prompt

    def _parse_claude_response(self, response: str, issues: List[LogIssue]) -> Dict:
        """Parse Claude's response for structured recommendations"""
        result = {
            "recommendations": [],
            "severity": "medium",
            "fixes": []
        }

        try:
            # Try to extract JSON from response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)
                result.update(data)
        except json.JSONDecodeError:
            # If JSON parsing fails, extract recommendations from text
            lines = response.split("\n")
            for line in lines:
                if line.startswith("- ") or line.startswith("• "):
                    result["recommendations"].append(line[2:].strip())

        return result

    async def should_escalate_now(self) -> bool:
        """
        Determine if we should escalate now (rate limiting for API calls)
        Only escalate once per 30 minutes per issue category
        """
        if not self.last_escalation_time:
            return True

        time_since_last = datetime.now() - self.last_escalation_time
        # Only escalate every 30 minutes to avoid excessive API usage
        return time_since_last > timedelta(minutes=30)

    def get_escalation_cache(self) -> Dict:
        """Get cached escalation responses"""
        return self.escalation_cache

    def clear_old_cache(self):
        """Remove expired cache entries"""
        now = datetime.now()
        self.escalation_cache = {
            k: v for k, v in self.escalation_cache.items()
            if (now - v.get("timestamp", now)).total_seconds() < self.cache_expiry
        }


class UserConfirmationManager:
    """Manage user confirmations for suggested fixes"""

    def __init__(self):
        self.pending_confirmations: Dict[str, Dict] = {}
        self.confirmed_actions: List[Dict] = []
        self.rejected_actions: List[Dict] = []

    def create_confirmation_request(
        self,
        issue: LogIssue,
        suggested_action: str,
        confidence: float = 0.8
    ) -> str:
        """
        Create a confirmation request for a suggested fix
        Returns confirmation ID
        """
        confirmation_id = f"{issue.issue_type.value}_{int(datetime.now().timestamp())}"

        self.pending_confirmations[confirmation_id] = {
            "id": confirmation_id,
            "issue": issue.to_dict(),
            "suggested_action": suggested_action,
            "confidence": confidence,
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }

        return confirmation_id

    def confirm_action(self, confirmation_id: str, user_notes: Optional[str] = None) -> bool:
        """User confirms to apply the suggested fix"""
        if confirmation_id not in self.pending_confirmations:
            return False

        confirmation = self.pending_confirmations[confirmation_id]
        confirmation["status"] = "confirmed"
        confirmation["user_notes"] = user_notes
        confirmation["confirmed_at"] = datetime.now().isoformat()

        self.confirmed_actions.append(confirmation)
        del self.pending_confirmations[confirmation_id]

        logger.info(f"User confirmed action: {confirmation_id}")
        return True

    def reject_action(self, confirmation_id: str, reason: Optional[str] = None) -> bool:
        """User rejects the suggested fix"""
        if confirmation_id not in self.pending_confirmations:
            return False

        confirmation = self.pending_confirmations[confirmation_id]
        confirmation["status"] = "rejected"
        confirmation["rejection_reason"] = reason
        confirmation["rejected_at"] = datetime.now().isoformat()

        self.rejected_actions.append(confirmation)
        del self.pending_confirmations[confirmation_id]

        logger.info(f"User rejected action: {confirmation_id}")
        return True

    def get_pending_confirmations(self) -> List[Dict]:
        """Get all pending confirmation requests"""
        return list(self.pending_confirmations.values())

    def get_confirmation_status(self, confirmation_id: str) -> Optional[Dict]:
        """Get status of a specific confirmation"""
        if confirmation_id in self.pending_confirmations:
            return self.pending_confirmations[confirmation_id]
        return None

    def get_action_history(self) -> Dict:
        """Get history of user actions"""
        return {
            "confirmed": self.confirmed_actions,
            "rejected": self.rejected_actions,
            "pending": list(self.pending_confirmations.values())
        }
