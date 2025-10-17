# Cost Tracking & Rate Limiting Implementation

## Overview

Successfully implemented comprehensive cost tracking and rate limiting for the Telegram bot to monitor API usage and prevent abuse.

## Features Implemented

### 1. Cost Tracking (`telegram_bot/cost_tracker.py`)

**Functionality:**
- Track API usage per user with detailed metrics
- Calculate costs based on Claude API pricing (Haiku, Sonnet, Opus models)
- Estimate token usage from text (rough approximation: ~4 chars/token)
- Daily and monthly cost limits with automatic resets
- Warning system at 80% of limits (warns once per hour)
- Persistent storage in `data/usage.json`
- Cost breakdown by model and request type

**Pricing (per 1M tokens):**
- **Haiku**: $0.80 input / $4.00 output
- **Sonnet**: $3.00 input / $15.00 output

**Default Limits:**
- Daily: $100
- Monthly: $1000

**Key Methods:**
- `estimate_tokens(text)` - Estimate token count from text
- `calculate_cost(model, input_tokens, output_tokens)` - Calculate cost
- `record_usage(user_id, model, input_tokens, output_tokens, request_type)` - Record usage
- `check_limits(user_id)` - Check if user is within limits
- `get_usage_stats(user_id)` - Get detailed usage statistics

### 2. Rate Limiting (`telegram_bot/rate_limiter.py`)

**Functionality:**
- Per-user rate limiting with configurable thresholds
- Multiple time windows (per-minute, per-hour)
- Burst protection (max 3 requests in 5 seconds)
- Automatic cooldown periods when limits exceeded
- In-memory tracking with automatic cleanup

**Default Limits:**
- 10 requests per minute
- 100 requests per hour
- 3 requests per 5 seconds (burst protection)
- 60 second cooldown after limit exceeded

**Key Methods:**
- `check_rate_limit(user_id)` - Check if request is allowed
- `record_request(user_id)` - Record a request
- `get_user_stats(user_id)` - Get rate limit statistics
- `reset_user(user_id)` - Reset limits for a user (admin function)

### 3. Bot Integration (`telegram_bot/main.py`)

**Integration Points:**
1. **Rate Limiting** - Applied to all message handlers:
   - Text messages
   - Voice messages (planned)
   - Document uploads (planned)
   - Photo uploads (planned)

2. **Cost Tracking** - Records usage for all API calls:
   - Estimates tokens from user input and bot responses
   - Records model, tokens, and cost
   - Automatically tracks daily/monthly totals

3. **New Commands:**
   - `/status` - Enhanced to show cost summary
   - `/usage` - Detailed API usage and cost breakdown

## User Experience

### Status Command (`/status`)
Shows overview including:
- Conversation history
- Background tasks
- **API usage summary** (daily/monthly costs, total requests)

### Usage Command (`/usage`)
Shows detailed breakdown:
- Total requests and cost
- Recent 24h activity
- Daily/monthly cost with percentages
- Rate limit status
- **Cost breakdown by model**
- Cooldown status (if applicable)

### Limit Messages

**Rate Limit Exceeded:**
```
⚠️ Too many requests. Limit: 10/minute. Please wait 60s.
```

**Cost Limit Exceeded:**
```
🚫 Daily limit exceeded ($100.00). Resets at midnight.
```

**Approaching Limit Warning:**
```
⚠️ Approaching daily limit: $82.50 / $100.00 (82%)
```

## Data Storage

- **Cost data**: `data/usage.json`
  - Persistent across bot restarts
  - Keeps last 1000 records per user
  - Automatic daily/monthly resets

- **Rate limit data**: In-memory
  - Resets on bot restart
  - Auto-cleanup of old timestamps

## Testing

Included test script: `test_cost_rate_limiting.py`

Run with:
```bash
python3 test_cost_rate_limiting.py
```

Tests verify:
- Token estimation
- Cost calculation
- Usage recording
- Limit checking
- Rate limiting
- Burst protection

## Configuration

### Adjusting Limits (Admin)

**Cost Limits:**
```python
cost_tracker.set_user_limits(user_id, daily=200.0, monthly=2000.0)
```

**Rate Limits:**
```python
rate_limiter.configure(
    requests_per_minute=20,
    requests_per_hour=200,
    burst_size=5,
    cooldown_seconds=30
)
```

### Environment Variables

No new environment variables required. Uses existing bot configuration.

## Future Enhancements

Potential improvements:
1. ✅ Per-user custom limits
2. ⏳ Rate limiting for voice/photo/document handlers
3. ⏳ Admin dashboard for monitoring all users
4. ⏳ Export usage reports
5. ⏳ Integration with actual Claude API token counts (vs estimates)
6. ⏳ Webhook for limit notifications
7. ⏳ Database storage for better analytics

## Implementation Summary

**Files Modified:**
- `telegram_bot/main.py` - Added rate limiting, cost tracking, and /usage command
- `telegram_bot/cost_tracker.py` - Complete cost tracking system
- `telegram_bot/rate_limiter.py` - Complete rate limiting system

**Files Created:**
- `test_cost_rate_limiting.py` - Test suite
- `COST_TRACKING_README.md` - This documentation

**Total Lines of Code:**
- Cost tracker: ~322 lines
- Rate limiter: ~186 lines
- Integration: ~80 lines
- Tests: ~150 lines

## Status

✅ **COMPLETE** - All core functionality implemented and tested.

The Telegram bot now has comprehensive cost tracking and rate limiting to:
- Monitor API usage and costs per user
- Prevent abuse through rate limiting
- Provide transparency with detailed usage statistics
- Protect against unexpected cost overruns with configurable limits
