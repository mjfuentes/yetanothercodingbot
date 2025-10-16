#!/bin/bash
# Setup script for launchd auto-restart

set -e  # Exit on error

echo "🚀 Setting up Telegram bot with launchd..."

# Check if bot runs manually first
echo ""
echo "📋 Checking prerequisites..."

if [ ! -f "telegram_bot/main.py" ]; then
    echo "❌ Error: telegram_bot/main.py not found"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "❌ Error: venv/ not found. Run: python -m venv venv"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "⚠️  Warning: .env file not found"
    echo "   Make sure you configure environment variables"
fi

echo "✅ Prerequisites OK"

# Create LaunchAgents directory
echo ""
echo "📁 Creating LaunchAgents directory..."
mkdir -p ~/Library/LaunchAgents

# Copy plist
echo "📋 Installing service..."
cp com.agentlab.telegrambot.plist ~/Library/LaunchAgents/
chmod 644 ~/Library/LaunchAgents/com.agentlab.telegrambot.plist

echo "✅ Service installed"

# Check if already loaded
if launchctl list | grep -q "com.agentlab.telegrambot"; then
    echo ""
    echo "⚠️  Service already running. Reloading..."
    launchctl unload ~/Library/LaunchAgents/com.agentlab.telegrambot.plist 2>/dev/null || true
    sleep 2
fi

# Load service
echo ""
echo "🔄 Starting service..."
launchctl load ~/Library/LaunchAgents/com.agentlab.telegrambot.plist

# Wait a moment for it to start
sleep 3

# Check if running
echo ""
echo "🔍 Checking status..."
if launchctl list | grep -q "com.agentlab.telegrambot"; then
    echo "✅ Service is running!"

    # Show recent logs
    echo ""
    echo "📝 Recent logs:"
    tail -n 20 logs/bot_stdout.log 2>/dev/null || echo "   (No logs yet)"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Setup complete!"
    echo ""
    echo "📊 Monitor logs:"
    echo "   tail -f logs/bot_stdout.log"
    echo ""
    echo "🛑 Stop service:"
    echo "   launchctl unload ~/Library/LaunchAgents/com.agentlab.telegrambot.plist"
    echo ""
    echo "🔄 Restart service:"
    echo "   launchctl unload ~/Library/LaunchAgents/com.agentlab.telegrambot.plist"
    echo "   launchctl load ~/Library/LaunchAgents/com.agentlab.telegrambot.plist"
    echo ""
    echo "❌ Remove service:"
    echo "   launchctl unload ~/Library/LaunchAgents/com.agentlab.telegrambot.plist"
    echo "   rm ~/Library/LaunchAgents/com.agentlab.telegrambot.plist"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "❌ Service failed to start"
    echo ""
    echo "Check errors:"
    echo "   cat logs/bot_stderr.log"
    exit 1
fi
