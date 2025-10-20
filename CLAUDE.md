# AgentLab - Claude Code Context

> Repository etiquette, conventions, and project-specific guidance for Claude Code agents.

## Project Overview

**YetAnotherCodingBot** - Telegram bot with intelligent routing between Claude API (Haiku) for Q&A and Claude Code CLI (Sonnet) for coding tasks.

**Core Philosophy**: Right model for the right task. Fast & cheap for questions, powerful & thorough for code.

## Repository Conventions

### Python Style

- **Formatter**: Black (line length 120)
- **Import order**: isort
- **Linter**: Ruff
- **Type hints**: Required for public APIs, encouraged elsewhere
- **Async by default**: All handlers and long-running operations use asyncio

### File Organization

```
telegram_bot/
├── main.py              # Entry point - bot setup, command handlers
├── claude_api.py        # Claude API integration (Haiku - Q&A routing)
├── claude_interactive.py # Claude Code CLI sessions (Sonnet - coding)
├── tasks.py             # Background task tracking
├── agent_pool.py        # Bounded worker pool for async execution
├── session.py           # Conversation history management
├── message_queue.py     # Per-user message serialization
├── monitoring_server.py # Web dashboard (Flask + SSE)
├── metrics_aggregator.py # Real-time metrics from hooks
├── cost_tracker.py      # API usage tracking
└── formatter.py         # Telegram message formatting

.claude/
├── agents/              # Agent definitions
│   ├── orchestrator.md            # Task coordinator
│   ├── code_agent.md              # Backend implementation (Sonnet 4.5)
│   ├── frontend_agent.md          # UI/UX development (Sonnet 4.5)
│   ├── research_agent.md          # Analysis & proposals (Opus 4.5)
│   ├── Jenny.md                   # Spec verification
│   ├── claude-md-compliance-checker.md  # Project compliance
│   ├── code-quality-pragmatist.md       # Complexity detection
│   ├── karen.md                   # Reality checks
│   ├── task-completion-validator.md     # Functional validation
│   ├── ui-comprehensive-tester.md       # UI testing
│   └── ultrathink-debugger.md           # Deep debugging (Opus 4.5)
├── hooks/               # Tool usage tracking (pre/post-tool-use, session-end)
└── settings.local.json  # Permissions, output style

data/                    # Runtime state (sessions, tasks, costs)
logs/                    # Application logs
```

### Agent Architecture

#### Core Agents
- **orchestrator**: Coordinates tasks, delegates to specialized agents
- **code_agent**: Backend implementation (Python, Sonnet 4.5)
- **frontend_agent**: UI/UX development (HTML/CSS/JS, Sonnet 4.5)
- **research_agent**: Analysis, proposals, web research (Opus 4.5)

#### Quality Assurance Agents
- **Jenny**: Verifies implementation matches specifications
- **claude-md-compliance-checker**: Ensures CLAUDE.md adherence
- **code-quality-pragmatist**: Detects over-engineering
- **karen**: Reality check on project completion
- **task-completion-validator**: Validates tasks actually work
- **ui-comprehensive-tester**: Comprehensive UI testing
- **ultrathink-debugger**: Deep debugging (Opus 4.5 - expensive, use sparingly)

#### Agent Workflow Examples

**Code Implementation Flow:**
1. orchestrator receives task
2. research_agent (if research needed)
3. code_agent (implementation)
4. task-completion-validator (verify it works)
5. code-quality-pragmatist (check complexity)
6. claude-md-compliance-checker (verify CLAUDE.md compliance)

**Bug Investigation Flow:**
1. orchestrator receives bug report
2. ultrathink-debugger (deep root cause analysis)
3. code_agent (implement fix)
4. task-completion-validator (verify fix works)

**Spec Verification Flow:**
1. orchestrator receives verification request
2. Jenny (compare implementation vs specs)
3. task-completion-validator (if gaps found, verify fixes)

### Naming Conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions**: `snake_case()`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private**: Prefix with `_` (not enforced but encouraged)

### Git Workflow

**CRITICAL**: Always commit after code changes.

```bash
# Standard workflow
git add <modified_files>
git commit -m "Brief descriptive message

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Commit message style**:
- Start with verb: "Add", "Fix", "Update", "Refactor"
- Be specific: "Fix null pointer in auth.py:42" not "Fix bug"
- Reference file:line when applicable

**Never commit**:
- `.env` files (use `.env.example`)
- `data/*` (runtime state)
- `logs/*` (application logs)
- `__pycache__/`, `*.pyc`

### Pre-commit Hooks

**Installed**: black, isort, ruff, bandit, pytest, secret detection

**Before committing**: Hooks run automatically. Fix any failures before proceeding.

**Manual run**: `pre-commit run --all-files`

## Development Environment Setup

### Initial Setup

```bash
# Clone repo
git clone <repo_url>
cd agentlab

# Create venv (Python 3.12+)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install pre-commit
pre-commit install

# Configure environment
cp .env.example .env
# Edit .env with your tokens
```

### Required Environment Variables

```bash
TELEGRAM_BOT_TOKEN       # From @BotFather
ANTHROPIC_API_KEY        # For Claude API (Haiku)
ALLOWED_USERS            # Comma-separated Telegram user IDs
WORKSPACE_PATH           # Base path for repositories (/Users/matifuentes/Workspace)
```

### Optional Environment Variables

```bash
DAILY_COST_LIMIT=100             # Stop at $100/day
MONTHLY_COST_LIMIT=1000          # Stop at $1000/month
SESSION_TIMEOUT_MINUTES=60       # Clear inactive sessions
ANTHROPIC_ADMIN_API_KEY          # For usage API sync (optional)
LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR
```

### Running the Bot

```bash
# Activate venv
source venv/bin/activate

# Run bot
python telegram_bot/main.py

# Run monitoring dashboard (optional, separate terminal)
python telegram_bot/monitoring_server.py
# Open http://localhost:3000
```

## Project-Specific Patterns

### Security: Input Sanitization

**CRITICAL**: All user input goes through sanitization before Claude API calls.

```python
# In claude_api.py
safe_query = sanitize_xml_content(user_query)  # HTML escape + pattern removal
is_malicious, reason = detect_prompt_injection(user_query)  # Detect attacks
validate_file_path(path, base_path)  # Prevent directory traversal
```

**Why**: User input is embedded in XML prompts. Unsanitized input could break prompt structure or inject instructions.

### Cost Optimization

**Token minimization** in `claude_api.py`:
- Conversation history: Last 2 messages only, truncate to 500 chars
- Active tasks: Max 3 tasks, omit descriptions
- Logs: Last 50 lines only (not 200)
- Don't include `available_repositories` list (~100 tokens saved)

**Model selection**:
- Haiku 4.5 for Q&A (10x cheaper)
- Sonnet 4.5 for coding (more capable)
- Opus 4.5 for research_agent and ultrathink-debugger (most capable, most expensive)

**Cost-aware agent usage**:
- research_agent (Opus): Use for complex analysis only
- ultrathink-debugger (Opus): Reserve for critical bugs and deep debugging
- Other agents (Sonnet/inherited): Standard usage

**Model specification rationale**:
- Explicit model specifications added to agents for cost predictability
- code_agent, frontend_agent: Sonnet 4.5 for balance of capability/cost
- research_agent: Opus 4.5 for comprehensive research and analysis
- ultrathink-debugger: Opus 4.5 for deep reasoning in complex debugging

### Background Task Format

**CRITICAL**: Responses from Claude API using BACKGROUND_TASK must follow exact format:

```
BACKGROUND_TASK|task_description|user_message
```

**Rules**:
- Single line, pipe-delimited
- NO markdown code blocks
- NO extra text before/after
- `task_description`: Internal use (what needs doing)
- `user_message`: Shown to user immediately

**Parsing**: `claude_api.py` looks for `BACKGROUND_TASK|` anywhere in response, strips markdown blocks, splits on `|`.

### Session Management

**Per-user isolation**: Each Telegram user has independent:
- Conversation history (`session.py`)
- Message queue (serializes requests per user)
- Cost tracking
- Active tasks

**History limits**:
- Max 10 messages in memory
- Cleared on `/clear` or timeout

### Agent Communication

**Orchestrator → Agent**:
```python
await agent_pool.submit(
    execute_background_task,
    task_id=task.id,
    task_description=description,
    user_id=user_id
)
```

**Agent → User**:
- Agents return summary strings
- Orchestrator aggregates results
- Bot formats for Telegram (4096 char chunks)

### Logging Strategy

**Structured logging** with context:

```python
logger.info(f"User {user_id}: {action} - {details}")
logger.error(f"Error in {component}: {error}", exc_info=True)
```

**Log levels**:
- DEBUG: Detailed flow, tool calls, state changes
- INFO: User actions, task lifecycle, API calls
- WARNING: Recoverable issues, rate limits, retries
- ERROR: Failures, exceptions, blocked operations

**Log location**: `logs/bot.log` (auto-rotated)

## Common Pitfalls

### 1. **Modifying Running Code**

**Problem**: The bot runs `telegram_bot/main.py`. Modifying it while running causes unpredictable behavior.

**Solution**: Make changes, commit, then user must `/restart` for changes to take effect.

### 2. **Async/Await Forgotten**

**Problem**: Calling async functions without `await` returns coroutine objects, not results.

**Example**:
```python
# ❌ Wrong
result = async_function()

# ✅ Correct
result = await async_function()
```

### 3. **Uncommitted Changes**

**Problem**: Agents make changes but forget to commit. Git tracker blocks work on other repos.

**Solution**: `code_agent` ALWAYS commits after file modifications. Check `.claude/agents/code_agent.md` for policy.

### 4. **Token Bloat in API Calls**

**Problem**: Including full conversation history or all logs wastes tokens and increases cost.

**Solution**: Strict limits in `claude_api.py`:
- History: Last 2 messages, 500 chars each
- Logs: Last 50 lines
- Tasks: Max 3, no descriptions

### 5. **Background Task Format Errors**

**Problem**: Claude API returns BACKGROUND_TASK wrapped in markdown or with extra text.

**Example**:
```markdown
# ❌ Wrong
Here's the task:
```
BACKGROUND_TASK|Fix bug|Fixing the bug
```

# ✅ Correct
BACKGROUND_TASK|Fix bug|Fixing the bug
```

**Solution**: Check `claude_api.py` system prompt - instructs to return ONLY the pipe-delimited line.

### 6. **Tool Permission Violations**

**Problem**: Agents attempt restricted operations (e.g., `rm -rf`).

**Solution**: Check `.claude/settings.local.json` for allowed/denied commands. Add to allow list if needed.

### 7. **Rate Limit Confusion**

**Problem**: Telegram rate limits are PER USER (30/min, 500/hour), not global.

**Solution**: `message_queue.py` handles per-user serialization. Don't add global limits.

## Testing

### Running Tests

```bash
cd telegram_bot
pytest -v
pytest --cov=. --cov-report=html
```

### Test Structure

Tests in `telegram_bot/test_*.py`

**Coverage targets**:
- Critical paths: 80%+
- Utility functions: 100%
- Handlers: Best effort

**Mocking**: Use `unittest.mock` for external APIs (Telegram, Anthropic)

### Test Data

- No real API keys in tests
- Use fixtures for common setups
- Temporary directories for file operations

## Monitoring & Debugging

### Dashboard

**URL**: http://localhost:3000 (when `monitoring_server.py` running)

**Features**:
- Running tasks (click for live tool usage)
- Recent errors
- 24h API costs
- Tool usage stats

**Tech**: Flask + SSE for real-time updates

### Hook System

**Location**: `~/.claude/hooks/`

**Hooks**:
- `pre-tool-use`: Logs before tool execution
- `post-tool-use`: Logs results/errors
- `session-end`: Aggregates summary

**Data**: Written to JSONL logs + JSON databases

**Reading**: `hooks_reader.py` parses for metrics dashboard

### Cost Tracking

**File**: `data/cost_tracking.json`

**Command**: `/usage` in Telegram

**Tracking**:
- Per-model costs (Haiku, Sonnet)
- Daily/monthly totals
- Usage breakdown by operation type

**Limits**: Set `DAILY_COST_LIMIT` and `MONTHLY_COST_LIMIT` in `.env`

## Unexpected Behaviors

### Voice Input Transcription

**Issue**: Whisper transcription not always perfect (especially project names).

**Mitigation**: `claude_api.py` system prompt instructs permissiveness with voice input. Orchestrator does fuzzy matching on repo names.

**Example**: "group therapy" → matches "groovetherapy" or "group-therapy"

### Telegram Message Chunking

**Issue**: Telegram max message length is 4096 chars.

**Solution**: `formatter.py` splits long responses into chunks, sends sequentially.

**Caveat**: Code blocks may be split mid-block. Uses heuristics to avoid.

### Claude Code CLI Timeouts

**Issue**: Complex tasks can take >5 minutes, exceeding default timeout.

**Solution**: Timeout set to 300s (5 min) in `claude_interactive.py`. For longer tasks, use `--timeout` flag.

### Agent Pool Blocking

**Issue**: All 3 workers busy → new tasks queue indefinitely.

**Current**: Basic queue, no priority
**Future**: Priority queue for urgent vs background (see TODO #2)

### Git Dirty State Blocking

**Issue**: Uncommitted changes in one repo block work on other repos (defensive measure).

**Solution**: `code_agent` always commits. If stuck, check `git status` in affected repos.

## Troubleshooting Commands

```bash
# Check logs for errors
tail -100 logs/bot.log | grep ERROR

# Check running tasks
# Use /status in Telegram

# Check cost usage
# Use /usage in Telegram
# Or: cat data/cost_tracking.json | jq

# Clear stuck sessions
# Use /clear in Telegram

# Stop all background tasks
# Use /stopall in Telegram

# Restart bot
# Use /restart in Telegram (owner only)

# Check agent pool status
# Monitoring dashboard: http://localhost:3000
```

## Performance Optimization

### Token Reduction

**Current optimizations** in `claude_api.py`:
- ✅ History truncation (last 2 messages, 500 chars)
- ✅ Log truncation (last 50 lines)
- ✅ Task truncation (max 3)
- ✅ Omit repos list

**Future**:
- TODO: Semantic compression of history
- TODO: Smart log filtering (errors only)

### Response Speed

**Haiku 4.5**: 1-2s for Q&A
**Sonnet 4.5**: 5-60s for coding tasks

**Optimization**: Route correctly. Don't use Sonnet for simple questions.

### Agent Pool

**Current**: 3 workers, basic queue

**Future** (see TODOs):
- Priority queue
- Dynamic scaling (reduce workers under load)
- Task timeout/cancellation

## Resources

### Documentation

- [Claude Code Docs](https://docs.claude.com/claude-code)
- [Claude Code Best Practices](https://www.anthropic.com/engineering/claude-code-best-practices)
- [Anthropic API Docs](https://docs.anthropic.com/)
- [python-telegram-bot Docs](https://docs.python-telegram-bot.org/)

### Internal Docs

- `README.md` - Project overview, quick start
- `docs/archive/AGENT_ARCHITECTURE.md` - Detailed agent system design
- `.claude/agents/*.md` - Agent configurations

### External Tools

- Claude Code CLI: `claude --help`
- Pre-commit hooks: `pre-commit run --help`
- Monitoring dashboard: `http://localhost:3000`

---

**Last Updated**: 2025-10-20
**Maintained By**: Matias Fuentes
**Claude Code Version**: Latest (Sonnet 4.5)
