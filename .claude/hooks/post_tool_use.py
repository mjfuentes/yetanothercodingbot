#!/usr/bin/env python3
"""Log tool usage after execution per Claude Code hooks documentation"""
import json
import sys
from pathlib import Path


def main():
    # Read event from stdin as per Claude Code hooks spec
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Non-blocking failure
        sys.exit(0)

    tool_name = event.get("tool_name")
    # Note: The exact structure of tool_result may vary by tool
    tool_result = event.get("tool_result", {})

    # Log to session directory
    task_id = event.get("session_id", "unknown")
    log_dir = Path(f"logs/sessions/{task_id}")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "post_tool_use.jsonl"

    # Extract relevant info from result
    output = str(tool_result) if tool_result else ""

    log_entry = {
        "tool": tool_name,
        "timestamp": event.get("timestamp"),
        "output_length": len(output),
        "has_error": "error" in output.lower() if output else False,
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        # Non-blocking - don't fail if logging fails
        pass

    # Always succeed (exit code 0) - non-blocking
    sys.exit(0)


if __name__ == "__main__":
    main()
