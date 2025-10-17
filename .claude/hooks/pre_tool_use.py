#!/usr/bin/env python3
"""Validate tool usage before execution per Claude Code hooks documentation"""
import json
import re
import sys
from pathlib import Path


def main():
    # Read event from stdin as per Claude Code hooks spec
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Non-blocking failure
        print("Warning: Could not parse hook input", file=sys.stderr)
        sys.exit(0)

    tool_name = event.get("tool_name")
    parameters = event.get("parameters", {})

    # Block dangerous Bash commands
    if tool_name == "Bash":
        command = parameters.get("command", "")

        dangerous_patterns = [
            r"rm\s+-rf\s+/",  # Root deletion
            r"rm\s+-rf\s+\*",  # Wildcard deletion
            r"mkfs\.",  # Format filesystem
            r"dd\s+if=.*of=/dev",  # Direct disk write
            r":(){ :|:& };:",  # Fork bomb
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, command):
                print(f"BLOCKED: Dangerous command pattern detected: {pattern}", file=sys.stderr)
                sys.exit(2)  # Exit code 2 blocks the tool use

    # Prevent editing .env files (credentials)
    if tool_name in ["Edit", "Write"]:
        file_path = parameters.get("file_path", "")
        if ".env" in file_path and not file_path.endswith(".env.example"):
            print("BLOCKED: Cannot modify .env files", file=sys.stderr)
            sys.exit(2)

    # Allow - log to session directory
    task_id = event.get("session_id", "unknown")
    log_dir = Path(f"logs/sessions/{task_id}")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "pre_tool_use.jsonl"

    # Use JSONL format for easier appending and parsing
    log_entry = {
        "tool": tool_name,
        "parameters": parameters,
        "timestamp": event.get("timestamp"),
        "status": "allowed",
    }

    try:
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        # Non-blocking - don't fail if logging fails
        pass

    # Success - allow execution (exit code 0)
    sys.exit(0)


if __name__ == "__main__":
    main()
