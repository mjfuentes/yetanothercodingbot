#!/usr/bin/env python3
"""
Simple async test for message queue (no pytest required)
Run directly: python telegram_bot/test_queue_simple.py
"""

import asyncio
import sys
from datetime import datetime

from message_queue import MessageQueueManager


class MockUpdate:
    """Mock Telegram Update object"""

    def __init__(self, user_id: int, message_text: str = "test"):
        self.effective_user = type("obj", (object,), {"id": user_id})()
        self.message = type("obj", (object,), {"text": message_text})()


class MockContext:
    """Mock Telegram Context object"""

    pass


async def test_single_message():
    """Test single message processing"""
    print("\n✅ Test 1: Single message processing")
    queue_manager = MessageQueueManager()
    results = []

    async def handler(update, context):
        results.append(f"processed: {update.message.text}")
        await asyncio.sleep(0.1)

    update = MockUpdate(user_id=123, message_text="hello")
    await queue_manager.enqueue_message(123, update, MockContext(), handler, "test")
    await asyncio.sleep(0.3)

    assert len(results) == 1
    print(f"  Result: {results[0]}")
    print("  ✓ Single message processed successfully")


async def test_concurrent_messages_sequential():
    """Test concurrent messages are processed sequentially"""
    print("\n✅ Test 2: Concurrent messages processed sequentially")
    queue_manager = MessageQueueManager()
    results = []
    start_times = {}

    async def handler(update, context):
        msg = update.message.text
        start_times[msg] = datetime.now()
        results.append(f"start: {msg}")
        await asyncio.sleep(0.15)  # 150ms per message
        results.append(f"done: {msg}")

    # Send 3 messages rapidly (concurrently)
    tasks = []
    for i in range(3):
        update = MockUpdate(user_id=123, message_text=f"msg_{i}")
        task = queue_manager.enqueue_message(123, update, MockContext(), handler, f"test_{i}")
        tasks.append(task)

    await asyncio.gather(*tasks)
    await asyncio.sleep(0.8)  # 3 * 150ms + buffer

    # Verify sequential processing (FIFO order)
    expected = [
        "start: msg_0",
        "done: msg_0",
        "start: msg_1",
        "done: msg_1",
        "start: msg_2",
        "done: msg_2",
    ]

    print(f"  Results: {results}")
    assert results == expected, f"Expected {expected}, got {results}"
    print("  ✓ Messages processed sequentially in FIFO order")


async def test_different_users_parallel():
    """Test different users process in parallel"""
    print("\n✅ Test 3: Different users process messages in parallel")
    queue_manager = MessageQueueManager()
    results = []
    start_times = {}

    async def handler(update, context):
        user_id = update.effective_user.id
        if user_id not in start_times:
            start_times[user_id] = datetime.now()
        results.append(f"start: user_{user_id}")
        await asyncio.sleep(0.2)
        results.append(f"done: user_{user_id}")

    # Send from 3 different users
    tasks = []
    for user_id in [1, 2, 3]:
        update = MockUpdate(user_id=user_id, message_text=f"user_{user_id}")
        task = queue_manager.enqueue_message(user_id, update, MockContext(), handler, f"user_{user_id}")
        tasks.append(task)

    await asyncio.gather(*tasks)
    await asyncio.sleep(0.5)

    # Verify all users are active (parallel processing)
    start_count = sum(1 for r in results if r.startswith("start:"))
    print(f"  Results: {results}")
    print(f"  Concurrent starts detected: {start_count}")
    # Should have multiple starts before any dones if truly parallel
    assert start_count >= 2, "Different users should process in parallel"
    print("  ✓ Different users process messages in parallel")


async def test_queue_order_fifo():
    """Test FIFO ordering"""
    print("\n✅ Test 4: FIFO queue ordering")
    queue_manager = MessageQueueManager()
    results = []

    async def handler(update, context):
        results.append(update.message.text)
        await asyncio.sleep(0.05)

    # Queue 5 messages
    for i in range(5):
        update = MockUpdate(user_id=999, message_text=f"msg_{i:02d}")
        await queue_manager.enqueue_message(999, update, MockContext(), handler, f"test_{i}")

    await asyncio.sleep(0.5)

    expected = ["msg_00", "msg_01", "msg_02", "msg_03", "msg_04"]
    print(f"  Results: {results}")
    assert results == expected
    print("  ✓ Messages processed in FIFO order")


async def test_queue_status():
    """Test queue status reporting"""
    print("\n✅ Test 5: Queue status reporting")
    queue_manager = MessageQueueManager()

    async def handler(update, context):
        await asyncio.sleep(0.1)

    # No queues initially
    status = queue_manager.get_status()
    assert status["active_users"] == 0
    print(f"  Initial status: {status['active_users']} active users")

    # Enqueue message
    update = MockUpdate(user_id=777, message_text="test")
    await queue_manager.enqueue_message(777, update, MockContext(), handler, "test")
    await asyncio.sleep(0.05)

    # Should have one active user
    status = queue_manager.get_status()
    print(f"  After enqueue: {status['active_users']} active user(s)")
    assert status["active_users"] == 1

    # Check user-specific status
    user_status = await queue_manager.get_user_status(777)
    print(f"  User 777 status: processing={user_status['processing']}, queue_size={user_status['queue_size']}")
    assert user_status is not None
    assert user_status["user_id"] == 777
    print("  ✓ Queue status reporting works correctly")


async def test_exception_handling():
    """Test that exceptions in handlers don't crash queue"""
    print("\n✅ Test 6: Exception handling in handlers")
    queue_manager = MessageQueueManager()
    results = []

    async def handler(update, context):
        msg = update.message.text
        if "error" in msg:
            raise ValueError(f"Intentional error in {msg}")
        results.append(msg)

    # Send good, error, good
    for msg in ["good_1", "error_msg", "good_2"]:
        update = MockUpdate(user_id=555, message_text=msg)
        await queue_manager.enqueue_message(555, update, MockContext(), handler, "test")

    await asyncio.sleep(0.5)

    print(f"  Results: {results}")
    assert "good_1" in results and "good_2" in results
    print("  ✓ Queue continues processing after exception")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Message Queue Tests")
    print("=" * 60)

    try:
        await test_single_message()
        await test_concurrent_messages_sequential()
        await test_different_users_parallel()
        await test_queue_order_fifo()
        await test_queue_status()
        await test_exception_handling()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
