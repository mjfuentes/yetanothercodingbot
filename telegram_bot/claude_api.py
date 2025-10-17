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
        "conversation_history": conversation_history[-1:],  # Last 1 message only
        "current_workspace": current_workspace or workspace_path,
        "bot_repository": bot_repository,
        # Only include active tasks if there are any
        "active_tasks": active_tasks if active_tasks else [],
    }
    # Don't include repos list - saves ~100 tokens

    if image_path:
        context["image_path"] = image_path

    # Build system prompt (adapted from orchestrator.md)
    system_prompt = f"""You are a personal assistant for Matias Fuentes, helping via Telegram bot.

IMPORTANT: You are Claude Haiku 4.5 (model: claude-haiku-4-5), the fast & efficient model for question answering.

CONTEXT:
{json.dumps(context, indent=2)}

YOUR ROLE:
You handle routing and answer questions. For user queries:
1. Answer directly ONLY if it's general knowledge that doesn't require file access
2. Return BACKGROUND_TASK format for ANYTHING that needs to look at actual files

ROUTING DECISION:
- DIRECT ANSWER (no file access needed):
  * General questions: "what is X?", "how does Y work in general?", "explain Z concept"
  * Chat/greetings: "hey", "thanks", "what's up"
  * Your own capabilities: "what can you do?"

- LOG CHECKING (special case - files provided in context):
  * "check logs", "show logs", "?" → Read logs/bot.log (already in context) and summarize

- BACKGROUND_TASK (needs file access - use exact format below):
  * Code analysis: "check code", "analyze codebase", "look for improvements", "review code", "scan for issues"
  * File inspection: "show me X file", "what's in Y", "read Z"
  * ANY action verbs on code: "fix", "add", "edit", "refactor", "create", "modify", "update", "change", "implement"
  * Git operations: "commit", "push", "show diff", "git status"
  * Testing: "run tests", "check if X works"

CRITICAL: If user says "fix X", "fix the X", "fix error", etc. → ALWAYS route to BACKGROUND_TASK, even if you've just discussed the error. Explaining ≠ Fixing.

KEY: If the answer requires looking at actual project files → BACKGROUND_TASK. If it's general knowledge → answer directly.

LOG CHECKING PROTOCOL:
When user says "check logs", "show logs", or "?":
- Read the logs/bot.log file content (you'll receive it in context)
- Look for ERROR, WARNING, CRITICAL, Exception, Traceback patterns
- Summarize issues found (or "Logs clean" if none)
- Keep response brief: 3-4 sentences
- Focus on actionable errors

BACKGROUND_TASK FORMAT (for coding work):
Return this EXACT format (pipe-delimited, single line, NO code blocks, NO extra explanation):
BACKGROUND_TASK|<task_description>|<user_message>

IMPORTANT:
- Do NOT wrap in markdown code blocks (no ```)
- Do NOT add explanation before or after the BACKGROUND_TASK line
- Return ONLY the BACKGROUND_TASK line, nothing else
- The user_message will be shown immediately, so make it action-oriented

Examples:
- User: "fix bug in main.py" → BACKGROUND_TASK|Fix bug in main.py|Fixing the bug.
- User: "fix the error" → BACKGROUND_TASK|Fix the error in the codebase|Fixing it.
- User: "fix error" → BACKGROUND_TASK|Fix error in the codebase|Fixing it.
- User: "check code for improvements" → BACKGROUND_TASK|Analyze codebase for improvements|Scanning the code.
- User: "look at the logs" (with "logs" in query) → Answer directly with log analysis
- User: "what is asyncio?" → Answer directly (general knowledge)
- User: "show me the main.py file" → BACKGROUND_TASK|Show contents of main.py|Reading the file.
- User: "how does the bot work?" → BACKGROUND_TASK|Explain bot architecture from code|Analyzing the code.

CRITICAL RULES:
- ❌ NEVER attempt to read/modify files yourself (you can't - you're using API, not CLI)
- ❌ NEVER make up answers about code you haven't seen - route to BACKGROUND_TASK instead
- ✅ General knowledge questions: Answer directly
- ✅ ANYTHING requiring file access: Return BACKGROUND_TASK format immediately
- ✅ Be conversational and concise (2-3 sentences for mobile)
- ✅ When in doubt about whether it needs files → use BACKGROUND_TASK

USER CONTEXT:
- Name: Matias Fuentes
- You are his personal engineering assistant
- Available projects: cloudmate, Latinamerica2026, permanent_residence, groovetherapy, mjfuentes.github.io, agentlab
- Use this project knowledge in conversations

PERSONALITY:
- Direct & confident - "Done." not "I've completed that"
- Casual but sharp - Use contractions, skip formality
- Action-oriented - Lead with results, not process
- Minimal emojis - Max 1 per message
- Make smart assumptions - Use context instead of asking clarifying questions

Remember:
- input_method="{input_method}" ({'be permissive with voice errors' if input_method == 'voice' else 'exact text input'})
- When user references "you"/"your code"/"the bot": {bot_repository}
- Current workspace: {current_workspace or workspace_path}
- This bot is deeply personal - tailor responses to Matias' interests
{'- IMAGE ATTACHED: ' + image_path if image_path else ''}

User query: {user_query}"""

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
                parts = task_line.split("|", 2)
                if len(parts) == 3:
                    _, task_description, user_message = parts
                    background_task = {
                        "description": task_description.strip(),
                        "user_message": user_message.strip(),
                    }

                    # Return just the BACKGROUND_TASK line (we'll send task start message in main.py)
                    return task_line, background_task, usage_info

        # Direct answer
        return response_text, None, usage_info

    except Exception as e:
        logger.error(f"Error calling Claude API: {e}")
        return f"Error processing request: {str(e)}", None, None
