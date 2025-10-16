# Development Guide

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
