# Agent-Based Architecture

**Status**: Phase 5 - Proper Separation of Concerns (October 17, 2025)

## Overview

The Telegram bot uses Claude Code's native agent system with a clear separation of concerns:
- **Orchestrator**: Routes queries, answers questions, reads/analyzes files
- **code_worker**: Executes all file operations, edits, and git commands

This refactoring ensures orchestrator never attempts writes or bash execution - it spawns code_worker instead.

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

**Role**: Router and analyzer - handles ALL user interactions except code execution

**Can Do**:
- Answer questions and provide explanations
- Read and analyze files (Read, Glob, Grep)
- Route coding tasks to code_worker via Task tool
- Compose conversational responses
- Handle voice input with transcription error tolerance

**Cannot Do** (Must spawn code_worker):
- Create/write files
- Edit files
- Run bash commands
- Execute git operations

**Tools**: Task, Read, Glob, Grep

**Output**: Plain text user-facing message

**Spawning code_worker**: Uses Task tool with `subagent_type="code_worker"`

### 2. Code Worker Agent (`.claude/agents/code_worker.md`)

**Role**: Executes all file operations and code changes

**Responsibilities**:
- Read, write, edit files
- Execute bash commands (git, tests, builds)
- Search codebase
- Commit changes with descriptive messages
- Return concise summaries of work

**Tools**: Read, Write, Edit, Glob, Grep, Bash

**Spawned by**: Orchestrator via Task tool

**Key Policy**: Always commits changes after modifications

### 3. Orchestrator Integration (`telegram_bot/orchestrator.py`)

**Purpose**: Bridge between bot and Claude Code orchestrator agent

**Flow**:
1. Builds context (user query, input method, history, workspace, repos)
2. Invokes `claude chat --model haiku` with orchestrator agent
3. Orchestrator decides: answer directly, spawn code_worker, or BACKGROUND_TASK
4. Returns user-facing response (or BACKGROUND_TASK format)

**Context Provided to Orchestrator**:
```json
{
  "user_query": "user's message",
  "input_method": "voice" | "text",
  "conversation_history": [...last 3 messages...],
  "current_workspace": "/current/path",
  "available_repositories": [...discovered repos...],
  "bot_repository": "/path/to/bot/code",
  "active_tasks": [...]
}
```

**Routing Decision** (handled by orchestrator):
- **Direct response**: "What's async?" → Explain directly
- **Spawn code_worker**: "Fix bug in X" → Task tool with code_worker
- **Background task**: "Refactor auth system" → BACKGROUND_TASK format

## Task Routing Strategy

The orchestrator uses this decision tree for each user query:

### 1. Direct Response (Q&A, Explanations)
**Examples**: "What's async?", "Explain closures", "Show me status"
- Orchestrator answers using available context
- No Task tool usage
- Returns conversational response

### 2. Quick Code Tasks (Spawn code_worker)
**Examples**: "Fix bug in X", "Add feature Y", "Commit changes"
- Orchestrator uses Task tool: `subagent_type="code_worker"`
- Waits for code_worker result
- Composes user-facing response

### 3. Complex Tasks (BACKGROUND_TASK)
**Examples**: "Refactor entire auth system", "Create Tetris game", "Build new API"
- Orchestrator returns: `BACKGROUND_TASK: <description>`
- Bot creates background task
- code_worker executes asynchronously
- User notified when complete

**Decision Rules**:
- Estimated <2 minutes: Use Task tool (option 2)
- Estimated >2 minutes: Use BACKGROUND_TASK (option 3)
- Multiple complex files: Always BACKGROUND_TASK
- "Create/build" requests: Always BACKGROUND_TASK

## Voice Input Handling

When `input_method: "voice"`:
- Orchestrator is more permissive with typos and transcription errors
- Infers repository names despite errors
- Example: "group therapy" → fuzzy matches "grouptherapy" or "group-therapy"

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

## Implementation Details

### How code_worker is Spawned

1. User sends message to bot
2. Bot calls `invoke_orchestrator()` with user query and context
3. Orchestrator agent receives context prompt
4. For coding tasks, orchestrator uses Claude Code's Task tool:
   ```
   Task(
     subagent_type="code_worker",
     description="Brief description",
     prompt="Detailed task with workspace, file info, etc"
   )
   ```
5. code_worker agent executes with tools: Read, Write, Edit, Glob, Grep, Bash
6. code_worker returns summary
7. Orchestrator composes user-facing response
8. Bot sends response to user

### Logging Code_worker Spawning

When testing, check bot logs for:
```
INFO: Invoking orchestrator agent for: [user query]
DEBUG: [Claude Code loading orchestrator agent]
INFO: [code_worker spawned if task used]
INFO: Orchestrator response: [result]
```

## Testing Checklist

- [ ] Simple query: "What's async/await in Python?" (direct response)
- [ ] Code fix: "Fix the bug in auth.py line 42" (Task tool spawns code_worker)
- [ ] Own repo: "Add a /restart command to your code" (code_worker in bot_repository)
- [ ] Other repo: "in ~/myproject, fix bug in app.py" (code_worker in specified workspace)
- [ ] Voice input: "add a logging function" (permissive with errors)
- [ ] Background task: "refactor the entire authentication system" (BACKGROUND_TASK format)
- [ ] Check logs show code_worker being spawned for appropriate tasks

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

### Example 1: Simple Question (No spawning)
```
User: "Explain async/await in Python"
Bot: Orchestrator responds directly with explanation
Logs: "Invoking orchestrator..." → "Orchestrator response: [explanation]"
```

### Example 2: Quick Code Fix (code_worker spawned)
```
User: "Fix the null pointer error in auth.py line 42"
Bot: Orchestrator spawns code_worker via Task tool
code_worker: Reads auth.py, fixes error, commits change
Orchestrator: Composes response
Bot: "Fixed null pointer in auth.py:42 by adding user existence check"
Logs: "Task tool invoked with code_worker" → "code_worker returns: [summary]"
```

### Example 3: Own Code Modification (code_worker spawned)
```
User: "Add a /restart command to your code"
Bot: Orchestrator spawns code_worker with bot_repository workspace
code_worker: Modifies main.py, adds handler, commits
Orchestrator: Composes response
Bot: "Added /restart command. Use /restart to gracefully restart the bot."
```

### Example 4: Complex Task (BACKGROUND_TASK)
```
User: "Refactor the entire authentication system with OAuth2"
Orchestrator: Returns BACKGROUND_TASK format
Bot: Creates background task, sends: "Background Task Started (#xyz). Refactoring auth system... You'll be notified when complete."
Later: code_worker executes in background, bot notifies user when done
```

### Example 5: Voice Input with Transcription Error
```
User: (voice) "add logging to group therapy project"
Transcription: "add logging to group therapy project" (might be "groove therapy" etc)
Orchestrator: Fuzzy matches to "groovetherapy" workspace
code_worker: Adds logging in groovetherapy project
Bot: "Added logging to the groovetherapy project"
```

## Refactoring Summary (October 17, 2025)

**What Changed**:
1. Orchestrator no longer handles file writes or bash execution
2. Orchestrator spawns code_worker via Task tool for coding tasks
3. Added clear routing logic: Direct response, code_worker task, or background task
4. code_worker now commits changes automatically

**Benefits**:
- Clear separation of concerns
- Orchestrator focuses on routing and Q&A
- code_worker handles all state changes
- Easier to test and maintain
- Better error handling per agent
- Logs clearly show code_worker being spawned

**Files Modified**:
- `.claude/agents/orchestrator.md` - Updated with routing strategy and Task tool usage
- `.claude/agents/code_worker.md` - Added Git Commit Policy
- `telegram_bot/orchestrator.py` - Updated prompt to guide proper routing
- `AGENT_ARCHITECTURE.md` - Documented new architecture
