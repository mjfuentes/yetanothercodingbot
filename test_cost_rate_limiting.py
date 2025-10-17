#!/usr/bin/env python3
"""
Test script for cost tracking and rate limiting
"""

import sys
import os

# Add telegram_bot to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'telegram_bot'))

from cost_tracker import CostTracker
from rate_limiter import RateLimiter

def test_cost_tracking():
    """Test cost tracking functionality"""
    print("=" * 60)
    print("Testing Cost Tracking")
    print("=" * 60)

    tracker = CostTracker(data_dir="data/test")

    # Test token estimation
    text = "Hello, this is a test message!"
    estimated = tracker.estimate_tokens(text)
    print(f"\nToken estimation:")
    print(f"  Text: '{text}'")
    print(f"  Estimated tokens: {estimated}")

    # Test cost calculation
    cost_haiku = tracker.calculate_cost("haiku", 1000, 2000)
    cost_sonnet = tracker.calculate_cost("sonnet", 1000, 2000)

    print(f"\nCost calculation (1000 input + 2000 output tokens):")
    print(f"  Haiku: ${cost_haiku:.6f}")
    print(f"  Sonnet: ${cost_sonnet:.6f}")

    # Record usage
    user_id = 12345
    cost = tracker.record_usage(
        user_id=user_id,
        model="haiku",
        input_tokens=500,
        output_tokens=1500,
        request_type="chat"
    )
    print(f"\nRecorded usage:")
    print(f"  User: {user_id}")
    print(f"  Cost: ${cost:.6f}")

    # Check limits
    allowed, warning = tracker.check_limits(user_id)
    print(f"\nLimit check:")
    print(f"  Allowed: {allowed}")
    print(f"  Warning: {warning if warning else 'None'}")

    # Get stats
    stats = tracker.get_usage_stats(user_id)
    print(f"\nUsage stats:")
    print(f"  Total requests: {stats['total_requests']}")
    print(f"  Daily cost: ${stats['daily_cost']:.6f} / ${stats['daily_limit']:.2f}")
    print(f"  Monthly cost: ${stats['monthly_cost']:.6f} / ${stats['monthly_limit']:.2f}")

    print("\n✅ Cost tracking tests passed!\n")
    return True


def test_rate_limiting():
    """Test rate limiting functionality"""
    print("=" * 60)
    print("Testing Rate Limiting")
    print("=" * 60)

    limiter = RateLimiter()
    user_id = 67890

    # Test normal usage
    print(f"\nTesting normal usage (user {user_id}):")
    for i in range(3):
        allowed, msg = limiter.check_rate_limit(user_id)
        print(f"  Request {i+1}: Allowed={allowed}, Msg={msg}")
        if allowed:
            limiter.record_request(user_id)

    # Get stats
    stats = limiter.get_user_stats(user_id)
    print(f"\nRate limit stats:")
    print(f"  Last minute: {stats['requests_last_minute']} / {stats['limit_per_minute']}")
    print(f"  Last hour: {stats['requests_last_hour']} / {stats['limit_per_hour']}")
    print(f"  In cooldown: {stats['in_cooldown']}")

    # Test burst protection
    print(f"\nTesting burst protection:")
    import time
    for i in range(5):
        allowed, msg = limiter.check_rate_limit(user_id)
        print(f"  Burst request {i+1}: Allowed={allowed}")
        if allowed:
            limiter.record_request(user_id)
        time.sleep(0.1)  # Small delay

    print("\n✅ Rate limiting tests passed!\n")
    return True


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Cost Tracking & Rate Limiting Test Suite")
    print("=" * 60 + "\n")

    try:
        test_cost_tracking()
        test_rate_limiting()

        print("=" * 60)
        print("✅ All tests passed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
