# Claude Code Telegram Orchestrator

Control Claude Code from your phone via Telegram bot.

## Features

- 🤖 Conversational AI assistant via Telegram
- 💬 Smart routing (Haiku 4.5 for chat, Sonnet 4.5 for code)
- 🔄 Background task management
- 🎤 Voice message support (Phase 5)
- 📊 Cost tracking and limits
- 🔒 User whitelist security

## Current Status: Phase 2 Complete

✅ Basic Telegram bot
✅ Claude Code CLI integration
✅ Session management with conversation history
⏳ Task orchestration (Phase 3-4)
⏳ Voice & rich formatting (Phase 5-6)
⏳ Production hardening (Phase 7)
⏳ Research workflow (Phase 8)

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Claude Code CLI installed (`claude --version`)
- Telegram account

### 2. Create Telegram Bot

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Copy the bot token

### 3. Get Your Telegram User ID

1. Talk to [@userinfobot](https://t.me/userinfobot)
2. Copy your numeric user ID

### 4. Setup

```bash
# Clone/navigate to project
cd agentlab

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your values:
# - TELEGRAM_BOT_TOKEN
# - ALLOWED_USERS (your Telegram user ID)
```

### 5. Run the Bot

```bash
# Make sure Claude Code is in your PATH
which claude

# Start the bot
python telegram_bot/main.py
```

### 6. Test

1. Find your bot on Telegram (search for the username you created)
2. Send `/start`
3. Try: "What's 2+2?"
4. Try: "Explain async/await in Python"

## Usage Examples

### Simple Questions
```
You: What's the weather API for Python?
Bot: The most popular Python weather API is...
```

### Code Generation (Phase 4+)
```
You: Build a REST API for user management
Bot: Creating background task #1...
     Estimated: 15-20 minutes
     I'll notify when complete.
```

### Research & Planning (Phase 8)
```
You: Research WebSocket implementations
Bot: 🔍 Starting research...
     📄 PLAN.md created
     Review and reply "implement" to start building.
```

## Configuration

### .env File

```bash
# Required
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Security (comma-separated user IDs)
ALLOWED_USERS=123456789,987654321

# Cost Limits
DAILY_COST_LIMIT=100
MONTHLY_COST_LIMIT=1000

# Optional
CLAUDE_CLI_PATH=claude
WORKSPACE_PATH=/path/to/workspace
LOG_LEVEL=INFO
```

## Commands

- `/start` - Show welcome message
- `/help` - Get help
- `/status` - Check session stats and message count
- `/clear` - Reset conversation history
- `/cost` - Show usage costs (Phase 7+)

## Project Structure

```
agentlab/
├── telegram_bot/
│   ├── main.py              # Bot entry point
│   ├── handlers.py          # Message handlers (Phase 2+)
│   ├── session.py           # Session management (Phase 2+)
│   └── tasks.py             # Task tracking (Phase 4+)
├── .claude/
│   └── agents/              # Agent configurations (Phase 3+)
├── data/
│   ├── sessions.json        # Active sessions (Phase 2+)
│   └── tasks.json           # Task history (Phase 4+)
├── logs/
│   └── bot.log             # Application logs
├── requirements.txt
├── .env
└── README.md
```

## Costs

Estimated monthly costs with Haiku 4.5 default:

- **Light use**: ~$86/month
- **Moderate use**: ~$184/month
- **Heavy use**: ~$365/month

See [TELEGRAM_BOT_PLAN.md](TELEGRAM_BOT_PLAN.md) for detailed breakdown.

## Development Roadmap

- [x] **Phase 1**: Basic bot + Claude integration (Week 1)
- [x] **Phase 2**: Persistent sessions (Week 1)
- [ ] **Phase 3**: Orchestrator agent (Week 2)
- [ ] **Phase 4**: Worker agents (Week 2-3)
- [ ] **Phase 5**: Voice support (Week 3)
- [ ] **Phase 6**: Rich UX (Week 3-4)
- [ ] **Phase 7**: Production hardening (Week 4)
- [ ] **Phase 8**: Research workflow (Week 5)

## Troubleshooting

### Bot doesn't respond
- Check `TELEGRAM_BOT_TOKEN` is correct
- Check your user ID is in `ALLOWED_USERS`
- Check logs: `tail -f logs/bot.log`

### Claude Code errors
- Verify Claude CLI is installed: `claude --version`
- Check `CLAUDE_CLI_PATH` in `.env`
- Test manually: `claude chat -p "test"`

### Permission denied
- Check your Telegram user ID: [@userinfobot](https://t.me/userinfobot)
- Add it to `ALLOWED_USERS` in `.env`
- Restart the bot

## Security Notes

- Bot uses user whitelist - only specified users can interact
- Never commit `.env` file
- Keep `TELEGRAM_BOT_TOKEN` secret
- Review costs regularly to avoid surprises

## Contributing

This is a personal project. See [TELEGRAM_BOT_PLAN.md](TELEGRAM_BOT_PLAN.md) for implementation details.

## License

Personal use only.
