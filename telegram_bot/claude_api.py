"""
Claude API integration for question answering and routing
Replaces orchestrator agent with direct Anthropic API calls
"""

import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)


async def ask_claude(
    user_query: str,
    input_method: str,  # "voice" or "text"
    conversation_history: list[dict],
    current_workspace: str | None,
    bot_repository: str,
    workspace_path: str,
    available_repositories: list[str],
    active_tasks: list[dict],
    image_path: str | None = None,
) -> tuple[str, dict | None, dict | None]:
    """
    Ask Claude a question using Anthropic API (not Claude Code CLI)

    Returns:
        (response_text, background_task_info, usage_info)
        - response_text: Direct answer for user
        - background_task_info: Dict with 'description' and 'user_message' if background task needed, else None
        - usage_info: Dict with 'input_tokens', 'output_tokens' from API response
    """

    # Build context - minimize tokens
    context = {
        "user_query": user_query,
        "input_method": input_method,
        "conversation_history": conversation_history[-2:],  # Last 2 messages
        "current_workspace": current_workspace or workspace_path,
        "bot_repository": bot_repository,
        # Only include active tasks if there are any
        "active_tasks": active_tasks if active_tasks else [],
    }
    # Don't include repos list - saves ~100 tokens

    if image_path:
        context["image_path"] = image_path

    # Build system prompt with XML structure for clarity and token efficiency
    system_prompt = f"""<role>Personal assistant for Matias Fuentes via Telegram. Model: Claude Haiku 4.5 (fast routing & Q&A).</role>

<context>
{json.dumps(context, indent=2)}
</context>

<capabilities>
Handle routing and answer questions:
• DIRECT: General knowledge (no file access needed)
• ROUTE: File operations → BACKGROUND_TASK format
</capabilities>

<routing_rules>
DIRECT ANSWER when:
• General knowledge: "what is X?", "how does Y work?", "explain Z"
• Greetings/chat: "hey", "thanks", "what's up"
• Capabilities: "what can you do?"
• Log checking: "check logs"/"show logs"/"?" (logs in context)

BACKGROUND_TASK when:
• Code analysis: "check code", "analyze", "review", "scan for issues"
• File operations: "show me X file", "what's in Y", "read Z"
• Actions: fix, add, edit, refactor, create, modify, update, change, implement
• Git ops: commit, push, show diff, status
• Testing: "run tests", "check if X works"

CRITICAL: "fix X" → BACKGROUND_TASK (explaining ≠ fixing)
Rule: File access needed → BACKGROUND_TASK. General knowledge → answer directly.
</routing_rules>

<log_protocol>
For "check logs"/"show logs"/"?":
• Scan for ERROR, WARNING, CRITICAL, Exception, Traceback
• Summarize (3-4 sentences max)
• Focus on actionable issues or "Logs clean"
</log_protocol>

<background_task_format>
Return pipe-delimited, single line, NO markdown blocks, NO extra text:

Default: BACKGROUND_TASK|<task_description>|<user_message>
With worker: BACKGROUND_TASK|<worker_type>|<task_description>|<user_message>

Workers:
• code_worker (default): Backend, scripts, APIs, general coding
• frontend_worker: Web UI/UX, HTML/CSS/JS, design, websites

Frontend triggers: website, web page, landing page, portfolio, UI, UX, design, styling, layout, responsive, HTML, CSS, JavaScript, gallery, navigation, header, footer, button, form

Rules:
• No markdown wrapping (no ```)
• No explanation before/after
• Only the BACKGROUND_TASK line
• user_message = action-oriented (shown immediately)
</background_task_format>

<examples>
GOOD:
• "fix bug in main.py" → BACKGROUND_TASK|Fix bug in main.py|Fixing the bug.
• "build landing page" → BACKGROUND_TASK|frontend_worker|Build landing page|Creating a responsive landing page.
• "update gallery" → BACKGROUND_TASK|frontend_worker|Update website gallery|Updating gallery.
• "check code" → BACKGROUND_TASK|Analyze codebase for improvements|Scanning the code.
• "what is asyncio?" → [Direct answer about asyncio]
• "check logs" → [Direct log summary from context]

BAD:
• Wrapping in ```BACKGROUND_TASK|...|...```
• Adding "Here's what I'll do: BACKGROUND_TASK|..."
• Attempting to read files yourself
• Making up answers about unseen code
• Verbose mobile responses (>3 sentences)
</examples>

<anti_examples>
❌ NEVER: Read/modify files (you're API, not CLI - no file access)
❌ NEVER: Invent code details without seeing it → route to BACKGROUND_TASK
❌ NEVER: Multi-paragraph responses for simple queries
❌ NEVER: Ask clarifying questions when context is clear
❌ NEVER: Use phrases like "I've completed", "I'll get started" - be direct
</anti_examples>

<personality>
• Direct: "Done." not "I've completed that"
• Casual: Use contractions, skip formality
• Action-first: Lead with results, not process
• Minimal emojis: Max 1/message
• Smart assumptions: Use context vs. asking
</personality>

<user_profile>
Name: Matias Fuentes
Projects: cloudmate, Latinamerica2026, permanent_residence, groovetherapy, mjfuentes.github.io, agentlab
Tailor responses to his technical interests
</user_profile>

<runtime_config>
input_method: {input_method} ({'voice - be permissive with errors' if input_method == 'voice' else 'text - exact input'})
bot_repository: {bot_repository}
current_workspace: {current_workspace or workspace_path}
{'image_attached: ' + image_path if image_path else ''}
</runtime_config>

<query>{user_query}</query>"""

    try:
        # Get API key from environment
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set")
            return "Configuration error. Check API key.", None

        # Create client
        client = anthropic.Anthropic(api_key=api_key)

        # Prepare messages
        messages = []

        # Add image if provided
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as f:
                    image_data = f.read()
                    import base64

                    image_base64 = base64.b64encode(image_data).decode()

                    # Determine media type
                    ext = Path(image_path).suffix.lower()
                    media_type = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }.get(ext, "image/jpeg")

                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": image_base64,
                                    },
                                },
                                {"type": "text", "text": user_query},
                            ],
                        }
                    )
            except Exception as e:
                logger.error(f"Error loading image: {e}")
                messages.append({"role": "user", "content": user_query})
        else:
            # If checking logs, include log content
            if any(keyword in user_query.lower() for keyword in ["check log", "show log", "?"]):
                log_path = Path(bot_repository) / "logs" / "bot.log"
                if log_path.exists():
                    try:
                        # Read last 50 lines only (not 200) to reduce tokens
                        with open(log_path) as f:
                            lines = f.readlines()
                            recent_logs = "".join(lines[-50:])

                        messages.append(
                            {"role": "user", "content": f"{user_query}\n\nRecent log content:\n```\n{recent_logs}\n```"}
                        )
                    except Exception as e:
                        logger.error(f"Error reading logs: {e}")
                        messages.append({"role": "user", "content": user_query})
                else:
                    messages.append({"role": "user", "content": user_query})
            else:
                messages.append({"role": "user", "content": user_query})

        logger.info(f"Calling Claude API (Haiku 4.5) for: {user_query[:60]}...")

        # Call API with Haiku 4.5 (fast and cheap - launched Oct 15, 2025)
        response = client.messages.create(
            model="claude-haiku-4-5", max_tokens=2048, system=system_prompt, messages=messages
        )

        # Extract response text
        response_text = response.content[0].text.strip()

        # Extract usage info
        usage_info = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

        logger.info(
            f"Claude API response: {response_text[:100]}... (tokens: {usage_info['input_tokens']} in, {usage_info['output_tokens']} out)"
        )

        # Check if response contains BACKGROUND_TASK anywhere (not just at start)
        if "BACKGROUND_TASK|" in response_text:
            # Find the line with BACKGROUND_TASK
            lines = response_text.split("\n")
            task_line = None

            for line in lines:
                cleaned_line = line.strip()
                # Strip markdown code blocks if present
                if cleaned_line.startswith("```"):
                    cleaned_line = cleaned_line[3:].strip()
                if cleaned_line.endswith("```"):
                    cleaned_line = cleaned_line[:-3].strip()

                if cleaned_line.startswith("BACKGROUND_TASK|"):
                    task_line = cleaned_line
                    break

            if task_line:
                # Parse the BACKGROUND_TASK line
                # Supports two formats:
                # 1. BACKGROUND_TASK|task_description|user_message (default: code_worker)
                # 2. BACKGROUND_TASK|worker_type|task_description|user_message (specify worker)
                parts = task_line.split("|")

                if len(parts) == 4:
                    # New format with worker type specified
                    _, worker_type, task_description, user_message = parts
                    background_task = {
                        "worker_type": worker_type.strip(),
                        "description": task_description.strip(),
                        "user_message": user_message.strip(),
                    }
                    return task_line, background_task, usage_info
                elif len(parts) == 3:
                    # Legacy format - defaults to code_worker
                    _, task_description, user_message = parts
                    background_task = {
                        "worker_type": "code_worker",  # Default worker
                        "description": task_description.strip(),
                        "user_message": user_message.strip(),
                    }
                    return task_line, background_task, usage_info

        # Direct answer
        return response_text, None, usage_info

    except Exception as e:
        logger.error(f"Error calling Claude API: {e}")
        return f"Error processing request: {str(e)}", None, None
