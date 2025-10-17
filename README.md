# Claude Code Telegram Bot

Personal Telegram bot powered by Claude AI for question answering and code assistance.

## 🌟 Features

- 🤖 **Smart AI Routing**: Claude API (Haiku 4) for fast question answering, Claude Code CLI (Sonnet 4.5) for coding tasks
- 💬 **Conversational**: Maintains conversation history and context
- 🎤 **Voice Support**: Send voice messages (transcribed with Whisper)
- 📸 **Image Analysis**: Send photos for Claude to analyze
- 📁 **Document Upload**: Attach files for analysis
- 🔄 **Background Tasks**: Long-running coding tasks run async with notifications
- 📊 **Cost Tracking**: Monitor API usage and set daily/monthly limits
- 🔐 **Secure**: User whitelist - only authorized users can access
- ⚡ **Queue System**: Sequential message processing per user
- 🔍 **Log Monitoring**: Automatic log analysis with alerts

## Architecture

### Message Flow

```
User Message (Telegram)
    ↓
Python Routing (main.py)
    ↓
├─→ Simple Commands (/status, /help) → Direct Response
├─→ Questions/Chat → Claude API (Haiku 4.0)
│   └─ "check logs", "explain X", etc.
│   └─ Fast (1-2s), cheap ($0.03/1M input)
│
└─→ Coding Tasks → Background Worker (Claude Code CLI + Sonnet 4.5)
    └─ "fix bug", "add feature", "create X"
    └─ Full tool access (Read, Write, Edit, Git, Bash)
    └─ Async execution with completion notification
```

### Key Design Decisions

**Why Claude API for Questions?**
- ~10x cheaper than Claude Code CLI
- Faster response times (1-2s vs 5-10s)
- Perfect for quick questions, log checking, explanations
- Can read log files and provide context-aware answers

**Why Claude Code CLI for Coding?**
- Full file system access (Read, Write, Edit tools)
- Git integration for commits
- Bash commands for testing
- Sonnet 4.5 model for complex reasoning

**Why Async Background Tasks?**
- User gets immediate acknowledgment
- Can continue chatting while task runs
- Notification when complete
- Better mobile UX

## Quick Start

### Prerequisites

- Python 3.12+ (3.13 recommended)
- [Claude Code CLI](https://docs.claude.com/claude-code) installed
- Telegram account
- Anthropic API key (for Claude API)

### 1. Create Telegram Bot

1. Open Telegram → [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow prompts
3. Save the bot token

### 2. Get Your Telegram User ID

1. Open Telegram → [@userinfobot](https://t.me/userinfobot)
2. Send any message
3. Copy your numeric user ID

### 3. Setup Project

```bash
# Clone repository
cd agentlab

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
```

### 4. Configure .env

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ALLOWED_USERS=your_telegram_user_id

# Optional (defaults shown)
CLAUDE_CLI_PATH=claude
WORKSPACE_PATH=/Users/yourname/Workspace/agentlab
SESSION_TIMEOUT_MINUTES=60
DAILY_COST_LIMIT=100
MONTHLY_COST_LIMIT=1000
LOG_LEVEL=INFO
```

### 5. Run Bot

```bash
# Start bot (foreground)
python telegram_bot/main.py

# Or run as macOS service
# See: telegram_bot/com.agentlab.telegrambot.plist
```

### 6. Test

1. Find your bot on Telegram
2. Send `/start`
3. Try: "What's 2+2?"
4. Try: "check logs"
5. Try: "fix the bug in main.py" (background task)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Reset conversation, show welcome |
| `/help` | Show available commands |
| `/status` | Session stats, active tasks, API costs |
| `/usage` | Detailed API usage breakdown |
| `/clear` | Clear conversation history |
| `/restart` | Restart the bot (owner only) |

## Usage Examples

### Quick Questions (Claude API)

```
You: What's the difference between async and await?
Bot: Async defines a coroutine function, await pauses execution
     until the awaited coroutine completes. Async makes functions
     non-blocking, await is how you call them.
```

### Log Checking (Claude API + File Reading)

```
You: check logs
Bot: Found 3 errors in last hour:
     • Line 452: KeyError in task_manager.get_task()
     • Line 789: Timeout connecting to Telegram API
     • Line 901: JSON decode error in session.json

     Most critical: KeyError - task ID not found in tasks dict.
     Want me to fix it?
```

### Coding Tasks (Background Worker)

```
You: fix the KeyError bug
Bot: **Background Task Started** (#abc123)

     Fixing KeyError in task_manager.get_task()

     I'll notify you when it's complete!

[2 minutes later...]

Bot: *Task Complete* (#abc123)

     Fixing KeyError in task_manager.get_task()

     **Result:**
     Fixed by adding defensive check in get_task():
     - Returns None if task_id not in tasks dict
     - Prevents KeyError crashes
     - Updated 2 callers to handle None return

     Committed: "Fix KeyError in task_manager.get_task()"
```

### Voice Messages

```
You: [voice message] "What does the orchestrator agent do?"
Bot: The orchestrator routes your messages. Questions go to Claude API
     for fast answers. Coding tasks spawn background workers with full
     file access. It's like a traffic controller for your requests.
```

### Image Analysis

```
You: [photo of error message]
Bot: That's a Python import error - module 'anthropic' not found.
     Run: pip install anthropic

     Want me to add it to requirements.txt?
```

## Project Structure

```
agentlab/
├── telegram_bot/                # Bot application
│   ├── main.py                 # Entry point, message routing
│   ├── claude_api.py           # Claude API integration (questions)
│   ├── claude_interactive.py   # Claude Code CLI (coding tasks)
│   ├── orchestrator.py         # Repo discovery, git checks
│   ├── session.py              # Conversation history
│   ├── tasks.py                # Background task tracking
│   ├── cost_tracker.py         # API usage monitoring
│   ├── rate_limiter.py         # Request rate limiting
│   ├── message_queue.py        # Sequential processing
│   ├── worker_pool.py          # Bounded concurrency
│   ├── git_tracker.py          # Uncommitted changes detection
│   ├── log_monitor.py          # Automatic log analysis
│   ├── formatter.py            # Telegram message formatting
│   └── ...
├── .claude/
│   └── agents/                 # Agent definitions (code_worker, etc.)
├── data/
│   ├── sessions.json           # Persistent conversation history
│   ├── tasks.json              # Task status and results
│   └── cost_tracking.json      # API usage data
├── logs/
│   └── bot.log                 # Application logs
├── .pre-commit-config.yaml     # Code quality hooks
├── pyproject.toml              # Tool configuration
├── requirements.txt
├── .env
└── README.md
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | From @BotFather |
| `ANTHROPIC_API_KEY` | Yes | - | For Claude API |
| `ALLOWED_USERS` | Yes | - | Comma-separated user IDs |
| `CLAUDE_CLI_PATH` | No | `claude` | Path to Claude Code CLI |
| `WORKSPACE_PATH` | No | `cwd` | Default workspace |
| `BOT_REPOSITORY` | No | `cwd` | Bot's own code location |
| `SESSION_TIMEOUT_MINUTES` | No | `60` | Session expiry |
| `DAILY_COST_LIMIT` | No | `100` | Daily spend limit ($) |
| `MONTHLY_COST_LIMIT` | No | `1000` | Monthly spend limit ($) |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |

## Cost Estimates

### Claude API (Questions)
- Model: Claude Haiku 4.0 20250514
- Input: $0.03 / 1M tokens (~750k words)
- Output: $0.15 / 1M tokens (~750k words)
- Typical question: ~$0.0001 ($0.10 per 1000 questions)

### Claude Code CLI (Coding)
- Model: Sonnet 4.5 (via CLI)
- Costs vary by task complexity
- Typical fix: $0.01-0.05
- Large feature: $0.10-0.50

### Example Monthly Cost (Moderate Use)
- 500 questions/day: ~$15/month
- 10 coding tasks/day: ~$60/month
- **Total: ~$75/month**

See [COST_TRACKING_README.md](COST_TRACKING_README.md) for detailed breakdown.

## Development

### Setup Pre-commit Hooks

```bash
# Install pre-commit (already in requirements.txt)
pip install pre-commit

# Install git hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### Hooks Included

- **black**: Code formatting (line length: 120)
- **isort**: Import sorting
- **ruff**: Fast linting (pycodestyle, pyflakes, etc.)
- **bandit**: Security checks
- **pytest**: Unit tests
- **Python syntax**: Compile check
- **Secrets detection**: Prevent committing tokens

### Running Tests

```bash
# Run all tests
cd telegram_bot
pytest -v

# Run specific test
pytest test_formatter.py -v

# Run with coverage
pytest --cov=. --cov-report=html
```

## Production Deployment

### macOS Service (launchd)

```bash
# Edit plist with your paths
vim telegram_bot/com.agentlab.telegrambot.plist

# Install service
cp telegram_bot/com.agentlab.telegrambot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.agentlab.telegrambot.plist

# Check status
launchctl list | grep agentlab

# View logs
tail -f /path/to/agentlab/logs/bot.log
```

### Linux Service (systemd)

```ini
[Unit]
Description=Claude Code Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/agentlab
Environment="PATH=/path/to/venv/bin:/usr/bin"
ExecStart=/path/to/venv/bin/python telegram_bot/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Troubleshooting

### Bot not responding

```bash
# Check logs
tail -100 logs/bot.log | grep ERROR

# Verify config
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('TELEGRAM_BOT_TOKEN')[:10])"

# Test Claude API
python -c "import anthropic; print(anthropic.__version__)"
```

### Claude API errors

```bash
# Verify API key
echo $ANTHROPIC_API_KEY

# Test connection
python -c "from anthropic import Anthropic; client = Anthropic(); print('OK')"
```

### Claude Code CLI errors

```bash
# Check installation
claude --version

# Test command
claude chat -p "test" --model haiku

# Check PATH
which claude
```

### Permission errors

1. Check `ALLOWED_USERS` in `.env`
2. Get your ID: [@userinfobot](https://t.me/userinfobot)
3. Restart bot after changes

### High costs

1. Check usage: `/usage` command
2. Review `DAILY_COST_LIMIT` in `.env`
3. Monitor `data/cost_tracking.json`
4. Use `/status` to see model usage breakdown

## Security

- ✅ User whitelist - only authorized users can interact
- ✅ No hardcoded secrets - all in `.env`
- ✅ Rate limiting (30 req/min, 500 req/hour)
- ✅ Cost limits (daily & monthly)
- ✅ Git hooks prevent committing secrets
- ⚠️ Keep `.env` private (in `.gitignore`)
- ⚠️ Rotate tokens if exposed

## Monitoring

### Log Analysis

Bot automatically monitors `logs/bot.log` for:
- Errors and exceptions
- Performance issues
- Rate limit hits
- API failures

Critical issues trigger Telegram notifications with suggested fixes.

### Manual Log Checking

```bash
# Recent errors
grep ERROR logs/bot.log | tail -20

# Today's activity
grep "$(date +%Y-%m-%d)" logs/bot.log | wc -l

# User activity
grep "User 123456789" logs/bot.log | tail -50
```

## Roadmap

- [x] **Phase 1**: Basic bot + Claude API integration
- [x] **Phase 2**: Persistent sessions
- [x] **Phase 3-4**: Background task system
- [x] **Phase 5**: Voice support with Whisper
- [x] **Phase 6**: Cost tracking & limits
- [x] **Phase 7**: Production hardening (logging, monitoring, queue system)
- [ ] **Phase 8**: Multi-repo awareness
- [ ] **Phase 9**: Rich formatting & UX improvements

## Contributing

This is a personal project. Feel free to fork and adapt for your needs.

## License

Personal use only. See LICENSE.

## Resources

- [Claude Code Documentation](https://docs.claude.com/claude-code)
- [Anthropic API Docs](https://docs.anthropic.com/)
- [python-telegram-bot Docs](https://docs.python-telegram-bot.org/)
- [Whisper Docs](https://github.com/openai/whisper)

## Support

For issues or questions:
1. Check logs: `tail -f logs/bot.log`
2. Try `/help` command
3. Ask the bot: "check logs" or "explain error in logs"
4. Review this README

---

**Built with:**
- Python 3.13
- Claude API (Haiku 4.0)
- Claude Code CLI (Sonnet 4.5)
- python-telegram-bot
- Whisper (voice transcription)
