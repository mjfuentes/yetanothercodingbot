# Development Guide

## Background Task System

### How It Works

The bot now intelligently determines when tasks are "big enough" to run in the background:

1. **User sends message** → Telegram bot receives it
2. **Orchestrator analyzes** → Determines if task is simple (answer immediately) or complex (run in background)
3. **For complex tasks**:
   - Orchestrator responds with: `BACKGROUND_TASK: <description>`
   - Bot creates task via `TaskManager`
   - Task executes in background using `ClaudeSessionPool`
   - User gets immediate acknowledgment: "🚀 Background Task Started"
4. **When task completes**:
   - Bot sends notification to user with results
   - Task marked as "completed" in `data/tasks.json`

### What Tasks Run in Background?

**Complex tasks** (background execution):
- "refactor the entire authentication system"
- "implement a new feature with tests"
- "fix all type errors in the codebase"
- "build a new API endpoint with documentation"
- "migrate database schema and update all models"

**Simple tasks** (immediate response):
- "what does this function do?"
- "explain the architecture"
- "show me the status"
- "read and summarize this file"

### Key Files

- `telegram_bot/orchestrator.py`: Analyzes tasks, returns `BACKGROUND_TASK|desc|message` format
- `telegram_bot/main.py`: Parses orchestrator response, creates background tasks
- `telegram_bot/tasks.py`: Tracks task status (pending/in_progress/completed/failed)
- `telegram_bot/claude_interactive.py`: Executes tasks with full Claude Code tool access
- `data/tasks.json`: Persistent task storage

### Task Notifications

When a background task completes, the bot automatically sends:

**On Success:**
```
✅ Task Complete (#abc123)
📝 [Task description]
**Result:**
[What was done]
```

**On Failure:**
```
❌ Task Failed (#abc123)
📝 [Task description]
**Error:**
[Error message]
```

## When to Restart the Bot

### 🔴 RESTART REQUIRED
These files are loaded once at bot startup. Changes need restart:

| File | What it does | Why restart needed |
|------|-------------|-------------------|
| `telegram_bot/main.py` | Bot logic, handlers | Python imports loaded at startup |
| `telegram_bot/session.py` | Session management | Classes/functions imported once |
| `telegram_bot/tasks.py` | Task tracking | Classes/functions imported once |
| `telegram_bot/orchestrator.py` | Orchestrator integration | Functions imported at startup |
| `telegram_bot/formatter.py` | Response formatting | Module imported at startup |
| `telegram_bot/claude_interactive.py` | Claude Code sessions | Classes imported at startup |
| `.env` | Environment variables | Read once at startup with `load_dotenv()` |

**How to restart:**
```bash
pkill -9 -f "python.*main.py" && sleep 1 && source venv/bin/activate && nohup python telegram_bot/main.py > logs/bot_stdout.log 2>&1 &
```

**Verify it restarted:**
```bash
tail -5 logs/bot_stdout.log
# Should show: "Bot started successfully!"
```

### 🟢 NO RESTART NEEDED
These files are loaded fresh on every use:

| File | What it does | Why no restart needed |
|------|-------------|----------------------|
| `.claude/agents/orchestrator.md` | Personality, instructions | Loaded fresh by `claude chat` each query |
| `.claude/agents/code_worker.md` | Code worker agent config | Loaded when spawned via Task tool |
| `data/sessions.json` | User conversation history | Read/written dynamically at runtime |
| `data/tasks.json` | Background tasks state | Read/written dynamically at runtime |

**How to test changes:**
- Just send a message on Telegram
- Changes apply immediately
- Check logs: `tail -f logs/bot_stdout.log`

## Testing Changes

### After Bot Restart
1. Send a test message to Telegram bot
2. Check `tail -f logs/bot_stdout.log` for errors
3. Verify response appears in Telegram

### For Agent Config Changes (no restart)
1. Just send a message - new config loads automatically
2. Check logs to verify orchestrator invocation
3. Personality/tone changes appear immediately

## Quick Commands

**View logs in real-time:**
```bash
tail -f logs/bot_stdout.log
```

**Check if bot is running:**
```bash
ps aux | grep "python.*main.py" | grep -v grep
```

**View recent logs:**
```bash
tail -50 logs/bot_stdout.log
```

**Check orchestrator responses:**
```bash
tail -100 logs/bot_stdout.log | grep -E "(orchestrator|User|response)"
```
