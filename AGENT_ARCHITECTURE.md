# Agent-Based Architecture

**Status**: Phase 3-4 Implementation Complete (October 2025)

## Overview

The Telegram bot now uses Claude Code's native agent system with a simplified orchestrator pattern. All user queries are handled by an orchestrator agent that can spawn specialized code workers when needed.

## Architecture

```
User Message (text or voice)
    ↓
Telegram Bot (main.py)
    ↓
Orchestrator Integration (orchestrator.py)
    ↓ Invokes claude chat
Claude Code Orchestrator Agent (.claude/agents/orchestrator.md)
    ↓ Uses Task tool to spawn
Code Worker Agent (.claude/agents/code_worker.md)
    ↓ Returns result
Orchestrator composes response
    ↓
Bot sends to user
```

## Key Components

### 1. Orchestrator Agent (`.claude/agents/orchestrator.md`)

**Role**: Single entry point for all user interactions

**Capabilities**:
- Analyzes user queries using natural language understanding
- Responds directly for conversational queries
- Spawns code_worker agents for code modifications
- Composes ALL user-facing messages (no hardcoded responses)
- Handles voice input with transcription error tolerance

**Tools**: Task, Read, Glob, Grep

**Output**: Plain text user-facing message

### 2. Code Worker Agent (`.claude/agents/code_worker.md`)

**Role**: Executes code modifications and file operations

**Capabilities**:
- Read, write, edit files
- Execute bash commands (git, tests, builds)
- Search codebase
- Return concise summaries

**Tools**: Read, Write, Edit, Glob, Grep, Bash

**Spawned by**: Orchestrator via Task tool

### 3. Orchestrator Integration (`telegram_bot/orchestrator.py`)

**Purpose**: Bridge between bot and Claude Code

**Flow**:
1. Builds context (user query, input method, history, workspace, repos)
2. Invokes `claude chat` with context
3. Returns orchestrator's response

**Context Provided**:
```json
{
  "user_query": "user's message",
  "input_method": "voice" | "text",
  "conversation_history": [...last 5 messages...],
  "current_workspace": "/current/path",
  "available_repositories": [...discovered repos...],
  "bot_repository": "/path/to/bot/code",
  "active_tasks": []
}
```

## Voice Input Handling

When `input_method: "voice"`:
- Orchestrator is more permissive with typos
- Infers repository names despite transcription errors
- Example: "group therapy" → "grouptherapy" or "group-therapy"

## Self-Awareness

The orchestrator knows its own codebase at `bot_repository`:
- `telegram_bot/main.py` - Bot logic, handlers
- `telegram_bot/orchestrator.py` - Orchestrator integration
- `telegram_bot/session.py` - Session management
- `telegram_bot/tasks.py` - Task tracking (legacy, may be deprecated)
- `.claude/agents/` - Agent configurations

When users say "you", "your code", "the bot" → refers to bot's own code

## Simplified Flow

**Old Architecture** (Deprecated):
```
User → Bot → detect_task_type → create_task → claude_interactive.py → execute → notify
```
Problems:
- Hardcoded task detection (keyword matching)
- Hardcoded workspace extraction (regex)
- Hardcoded user messages
- Separate JSON-based action system

**New Architecture**:
```
User → Bot → orchestrator → Claude Code (with agents) → response
```
Benefits:
- Natural language understanding
- Orchestrator composes all messages
- Agents spawn sub-agents as needed
- No JSON, no action parsing
- Simpler, more flexible

## Migration Notes

### Removed Components
- `detect_task_type()` - Replaced by orchestrator's NLU
- `extract_workspace_from_message()` - Replaced by orchestrator's understanding
- `execute_action()` - No longer needed (orchestrator returns text)
- JSON action intents - Simplified to text responses

### Deprecated (But Kept for Now)
- `execute_code_task()` - Not used, may remove later
- `show_task_status()` - Not used, may remove later
- `claude_interactive.py` - Legacy session management, replaced by agents

### Current Usage
- `claude_client` (ClaudeCodeSession) - Still used as fallback if orchestrator fails
- `session_manager` - Still tracks conversation history
- `task_manager` - Exists but not actively used by orchestrator yet

## Testing Checklist

- [ ] Simple query: "What's async/await in Python?"
- [ ] Code modification (own repo): "Add a /version command to your code"
- [ ] Code modification (other repo): "in ~/myproject, fix bug in app.py"
- [ ] Voice input with transcription errors
- [ ] Workspace awareness with /cd command
- [ ] Repository name fuzzy matching (voice)
- [ ] Self-reference queries ("show me your logs", "update your README")

## Future Enhancements

1. **Task persistence**: Have orchestrator create/update tasks in TaskManager
2. **Background execution**: Long-running code_worker tasks with status updates
3. **Multi-step workflows**: Orchestrator chains multiple agents
4. **Specialized agents**: Add data_analyst, debugger, researcher agents
5. **Cost tracking**: Monitor Claude API usage per user/task

## Configuration

Agent files location: `.claude/agents/`
- `orchestrator.md` - Main orchestrator
- `code_worker.md` - Code execution worker

Bot configuration: `.env`
```bash
WORKSPACE_PATH=/Users/matifuentes/Workspace  # Base workspace
BOT_REPOSITORY=/Users/matifuentes/Workspace/agentlab  # Bot's own code
```

## Example Interactions

**Q: "Explain async/await"**
→ Orchestrator responds directly (no agent spawning)

**Q: "Add logging to your main.py"**
→ Orchestrator spawns code_worker in bot_repository → returns result

**Q: "in ~/myproject, create a README"**
→ Orchestrator spawns code_worker in ~/myproject → returns result

**Q (voice): "list files in group therapy repository"** (transcribed incorrectly)
→ Orchestrator fuzzy matches "grouptherapy" repo → lists files
