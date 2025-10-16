# Setup Guide - Telegram Bot for Claude Code

Follow these steps to get your bot running.

## Step 1: Create Telegram Bot

1. **Open Telegram** on your phone or desktop
2. **Search for** `@BotFather`
3. **Send** `/newbot`
4. **Follow prompts:**
   - Enter bot name (e.g., "My Claude Assistant")
   - Enter username (e.g., "my_claude_bot")
5. **Save the token** (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Step 2: Get Your User ID

1. **Search for** `@userinfobot` on Telegram
2. **Start chat** - it will send you your user ID
3. **Save the number** (e.g., `123456789`)

## Step 3: Install Dependencies

```bash
# Navigate to project
cd /Users/matifuentes/Workspace/agentlab

# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install packages
pip install -r requirements.txt
```

## Step 4: Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit with your values
nano .env  # or use any text editor
```

**Edit `.env` file:**
```bash
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_FROM_STEP_1
ALLOWED_USERS=YOUR_USER_ID_FROM_STEP_2
```

## Step 5: Verify Claude Code

```bash
# Check Claude CLI is installed
which claude

# Should output: /usr/local/bin/claude or similar

# Test it
claude chat -p "test"

# Should get a response from Claude
```

If `claude` not found:
- Install from: https://docs.claude.com/en/docs/claude-code/getting-started
- Or use: `brew install claude` (macOS)

## Step 6: Run the Bot

```bash
# Make sure venv is activated
source venv/bin/activate

# Start the bot
python telegram_bot/main.py
```

You should see:
```
INFO - Starting Telegram bot...
INFO - Bot started successfully!
```

## Step 7: Test It

1. **Open Telegram**
2. **Find your bot** (search for username from Step 1)
3. **Send** `/start`

You should get a welcome message!

Try these:
- `What's 2+2?`
- `Explain Python decorators`
- `What's the difference between async and sync?`

## Troubleshooting

### "Unauthorized" message

❌ **Problem:** Bot says you're unauthorized

✅ **Fix:**
1. Verify your user ID: Talk to `@userinfobot`
2. Check `.env` file has correct `ALLOWED_USERS`
3. Restart bot: `Ctrl+C` then `python telegram_bot/main.py`

### "claude: command not found"

❌ **Problem:** Claude CLI not installed

✅ **Fix:**
```bash
# macOS
brew install claude

# Or download from:
# https://docs.claude.com/en/docs/claude-code/getting-started
```

### Bot doesn't respond

❌ **Problem:** No response to messages

✅ **Fix:**
1. Check bot logs: `tail -f logs/bot.log`
2. Verify token: Check `.env` has correct `TELEGRAM_BOT_TOKEN`
3. Test Claude manually: `claude chat -p "test"`

### "ModuleNotFoundError"

❌ **Problem:** Missing Python packages

✅ **Fix:**
```bash
# Activate venv
source venv/bin/activate

# Reinstall
pip install -r requirements.txt
```

## Next Steps

Once basic bot is working:

- **Phase 2** (next): Persistent chat sessions
- **Phase 3-4**: Background task orchestration
- **Phase 5**: Voice message support
- **Phase 6**: Rich formatting and commands
- **Phase 7**: Production hardening
- **Phase 8**: Research workflow

See [TELEGRAM_BOT_PLAN.md](TELEGRAM_BOT_PLAN.md) for full roadmap.

## Running in Background

### Option 1: screen (recommended)

```bash
# Start screen session
screen -S claude-bot

# Run bot
python telegram_bot/main.py

# Detach: Ctrl+A, then D

# Reattach later
screen -r claude-bot
```

### Option 2: nohup

```bash
nohup python telegram_bot/main.py > bot_output.log 2>&1 &

# Check if running
ps aux | grep main.py

# Stop it
kill <process_id>
```

### Option 3: systemd (Linux)

Create `/etc/systemd/system/claude-bot.service`:
```ini
[Unit]
Description=Claude Code Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/agentlab
Environment="PATH=/path/to/venv/bin:/usr/bin"
ExecStart=/path/to/venv/bin/python telegram_bot/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable claude-bot
sudo systemctl start claude-bot
sudo systemctl status claude-bot
```

## Security

- ✅ Only authorized users can use bot (via `ALLOWED_USERS`)
- ✅ Never commit `.env` file
- ✅ Keep bot token secret
- ✅ Review logs regularly: `tail logs/bot.log`

## Cost Monitoring

Track costs in Phase 7. Expected:
- Light use: ~$86/month
- Moderate use: ~$184/month

Set limits in `.env`:
```bash
DAILY_COST_LIMIT=100
MONTHLY_COST_LIMIT=1000
```

## Support

- Check logs: `tail -f logs/bot.log`
- Review plan: `cat TELEGRAM_BOT_PLAN.md`
- Claude docs: https://docs.claude.com

---

**Ready to use!** 🚀

Send messages to your bot and it will respond via Claude Code.
