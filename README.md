# YetAnotherCodingBot

<p align="center">
  <img src="telegram_bot/logo.png" alt="Bot Logo" width="500"/>
</p>

> **Status: archived, October 2025.** Telegram front end for Claude: quick questions go to the API, coding tasks run in Claude Code CLI in the background, with a cost dashboard. Superseded by [AMIGA](https://github.com/mjfuentes/amiga) and then [cc+](https://github.com/kerplunkstudio/ccplus).

A Telegram bot powered by Claude AI that handles everything from quick questions to complex coding tasks. Routes intelligently between Claude API for speed and Claude Code CLI for deep work.

## What it does

**Questions**: Fast answers using Claude API (Haiku 4). Great for "what's the difference between X and Y?" or "check logs for errors."

**Coding**: Full-featured development using Claude Code CLI (Sonnet 4.5). Reads/writes files, makes commits, runs tests. Tasks run in the background - you get notified when done.

**Voice & Images**: Send voice notes (transcribed via Whisper) or screenshots for analysis.

**Monitoring**: Built-in dashboard at `http://localhost:3000` shows running tasks, errors, API costs, and tool usage in real-time.

## Quick Start

### Prerequisites

- Python 3.12+
- [Claude Code CLI](https://docs.claude.com/claude-code)
- Anthropic API key
- Telegram account

### Setup

```bash
# Create Telegram bot via @BotFather, save token
# Get your user ID from @userinfobot

# Install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your tokens and user ID

# Run
python telegram_bot/main.py

# Monitor (optional)
python telegram_bot/monitoring_server.py
# Open http://localhost:3000
```

### Environment Config

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
ANTHROPIC_API_KEY=your_api_key
ALLOWED_USERS=your_telegram_user_id

# Optional
DAILY_COST_LIMIT=100
MONTHLY_COST_LIMIT=1000
SESSION_TIMEOUT_MINUTES=60
```

## Commands

- `/start` - Reset and show welcome
- `/help` - Command reference
- `/status` - Session stats, active tasks, costs
- `/usage` - API usage breakdown
- `/clear` - Clear history
- `/stopall` - Cancel all running tasks
- `/restart` - Restart bot (owner only)

## Architecture

### Message Routing

```
Telegram Message
    ↓
Router
    ├─→ Simple commands (/help, /status) → Direct response
    ├─→ Questions → Claude API (Haiku 4)
    │   Fast, cheap, conversational
    │
    └─→ Coding tasks → Background worker (Claude Code CLI + Sonnet 4.5)
        Full file access, git, bash
        Async with notifications
```

### Why Two Models?

**Claude API** for questions:
- 10x cheaper ($0.0001 per question vs $0.01+ per task)
- Faster (1-2s vs 5-10s)
- Perfect for chat, log analysis, quick answers

**Claude Code CLI** for coding:
- Read/Write/Edit tools
- Git integration
- Bash commands
- Better for complex reasoning

### Background Tasks

Long-running work happens async. You get immediate acknowledgment, can keep chatting, and receive a notification when complete. Better UX on mobile.

## Monitoring Dashboard

Real-time web dashboard shows:
- **Running Tasks**: Click any task to see live tool usage
- **Errors**: Recent failures with timestamps
- **API Costs**: 24h spending across models
- **Tool Usage**: Which tools are being called

Built with Flask + SSE for live updates. Dark theme, minimal design.

## Project Structure

```
agentlab/
├── telegram_bot/
│   ├── main.py                  # Entry point, routing
│   ├── claude_api.py            # Claude API (questions)
│   ├── claude_interactive.py    # Claude Code CLI (coding)
│   ├── tasks.py                 # Background task tracking
│   ├── monitoring_server.py     # Web dashboard
│   ├── metrics_aggregator.py    # Real-time metrics
│   ├── hooks_reader.py          # Hook data parsing
│   ├── cost_tracker.py          # API usage
│   ├── session.py               # Conversation history
│   ├── message_queue.py         # Per-user queuing
│   ├── log_monitor.py           # Automatic log analysis
│   └── formatter.py             # Telegram formatting
├── .claude/
│   ├── agents/                  # Agent definitions
│   └── hooks/                   # Tool usage tracking
├── data/                        # Sessions, tasks, costs
├── logs/                        # Application logs
└── .pre-commit-config.yaml      # Code quality
```

## Hook System

Bash hooks (in `~/.claude/hooks/`) track every tool call:
- `pre-tool-use`: Logs tool name + params before execution
- `post-tool-use`: Logs results + errors after execution
- `session-end`: Aggregates session summary

Python inline for JSON parsing, bash for everything else. Resilient (`set +e`), writes to both JSONL logs and JSON databases.

Monitoring dashboard reads these hooks in real-time via SSE.

## Cost Estimates

### Typical Usage
- 500 questions/day @ Claude API: ~$15/month
- 10 coding tasks/day @ Claude Code: ~$60/month
- **Total: ~$75/month**

### Per Request
- Question (API): ~$0.0001
- Small fix (CLI): $0.01-0.05
- Large feature (CLI): $0.10-0.50

Set `DAILY_COST_LIMIT` and `MONTHLY_COST_LIMIT` in `.env`. Bot stops when limit reached.

## Development

### Pre-commit Hooks

```bash
pre-commit install
pre-commit run --all-files
```

Includes: black, isort, ruff, bandit, pytest, secret detection

### Testing

```bash
cd telegram_bot
pytest -v
pytest --cov=. --cov-report=html
```

### Running in Production

**macOS (launchd)**:
```bash
cp telegram_bot/com.agentlab.telegrambot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentlab.telegrambot.plist
```

**Linux (systemd)**: See SETUP.md

## Security

- User whitelist (only authorized IDs)
- No hardcoded secrets
- Rate limiting (30/min, 500/hour)
- Cost limits
- Git hooks prevent token commits

## Troubleshooting

**Bot not responding**:
```bash
tail -100 logs/bot.log | grep ERROR
```

**High costs**:
```bash
# Check usage
Use /usage command
# Review data/cost_tracking.json
```

**Task stuck**:
```bash
# Use /stopall to cancel running tasks
# Check monitoring dashboard for errors
```

## Built With

- Python 3.13
- Claude API (Haiku 4.0) + Claude Code CLI (Sonnet 4.5)
- python-telegram-bot
- Flask (monitoring dashboard)
- Whisper (voice transcription)

## Resources

- [Claude Code Docs](https://docs.claude.com/claude-code)
- [Anthropic API Docs](https://docs.anthropic.com/)
- [python-telegram-bot](https://docs.python-telegram-bot.org/)

---

*Personal project. Built to route the right work to the right model and keep costs reasonable.*
