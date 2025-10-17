#!/usr/bin/env python3
"""Handle Stop event to generate task completion summary per Claude Code hooks documentation"""
import json
import sys
from pathlib import Path


def main():
    # Read event from stdin as per Claude Code hooks spec
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    task_id = event.get("session_id", "unknown")
    log_dir = Path(f"logs/sessions/{task_id}")

    if not log_dir.exists():
        sys.exit(0)

    # Read pre-tool and post-tool logs
    pre_tools = []
    post_tools = []

    try:
        pre_file = log_dir / "pre_tool_use.jsonl"
        if pre_file.exists():
            with open(pre_file) as f:
                pre_tools = [json.loads(line) for line in f if line.strip()]
    except Exception:
        pass

    try:
        post_file = log_dir / "post_tool_use.jsonl"
        if post_file.exists():
            with open(post_file) as f:
                post_tools = [json.loads(line) for line in f if line.strip()]
    except Exception:
        pass

    # Generate summary
    tools_by_type = {}
    for tool in post_tools:
        tool_name = tool.get("tool")
        tools_by_type[tool_name] = tools_by_type.get(tool_name, 0) + 1

    blocked_count = len([t for t in pre_tools if t.get("status") == "blocked"])
    error_count = len([t for t in post_tools if t.get("has_error")])

    summary = {
        "task_id": task_id,
        "total_tools_used": len(post_tools),
        "tools_by_type": tools_by_type,
        "blocked_operations": blocked_count,
        "tools_with_errors": error_count,
    }

    try:
        with open(log_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
    except Exception:
        pass

    # Output summary message (will appear in transcript)
    print(f"Task completed: {summary['total_tools_used']} tools used")

    # Always succeed (exit code 0)
    sys.exit(0)


if __name__ == "__main__":
    main()
