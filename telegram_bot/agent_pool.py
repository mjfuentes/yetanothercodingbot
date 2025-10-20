"""
Bounded agent pool for background task execution.

Prevents blocking by managing a fixed number of concurrent agents,
queuing excess tasks for processing when agents become available.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel object to signal agent shutdown
_SENTINEL = object()


class AgentPool:
    """
    Bounded agent pool for async task execution.

    Maintains a fixed number of agent coroutines that process tasks
    from a queue, ensuring concurrent work doesn't overwhelm the system.
    Uses poison pill pattern (SENTINEL) for graceful shutdown.
    """

    def __init__(self, max_agents: int = 3):
        """
        Initialize the agent pool.

        Args:
            max_agents: Maximum number of concurrent agents (default 3)
        """
        self.max_agents = max_agents
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.agents: list[asyncio.Task] = []
        self.active_tasks = 0
        self._lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        """Start the agent pool by spawning agent coroutines."""
        if self._started:
            logger.warning("Agent pool already started")
            return

        self._started = True
        logger.info(f"Starting agent pool with {self.max_agents} agents")

        # Spawn agent tasks
        for i in range(self.max_agents):
            agent_task = asyncio.create_task(self._agent(i))
            self.agents.append(agent_task)

    async def stop(self) -> None:
        """Stop the agent pool gracefully."""
        if not self._started:
            logger.warning("Agent pool not started")
            return

        logger.info("Stopping agent pool...")

        # Send sentinel values to signal agents to stop
        for _ in range(self.max_agents):
            await self.task_queue.put(_SENTINEL)

        # Wait for all agents to finish
        try:
            await asyncio.gather(*self.agents)
            logger.info("Agent pool stopped successfully")
        except asyncio.CancelledError:
            logger.warning("Agent pool tasks cancelled")
            pass

        self.agents.clear()
        self._started = False

    async def submit(self, task_func: Callable, *args: Any, **kwargs: Any) -> None:
        """
        Submit a task for execution in the agent pool.

        Non-blocking - returns immediately after queueing the task.

        Args:
            task_func: Async callable to execute
            *args: Positional arguments for task_func
            **kwargs: Keyword arguments for task_func
        """
        if not self._started:
            raise RuntimeError("Agent pool not started")

        # Queue the task (non-blocking)
        await self.task_queue.put((task_func, args, kwargs))
        logger.debug(f"Task submitted to agent pool (queue size: {self.task_queue.qsize()})")

    async def _agent(self, agent_id: int) -> None:
        """
        Main agent loop - processes tasks from queue.

        Args:
            agent_id: Unique identifier for this agent
        """
        logger.info(f"Agent {agent_id} started")

        try:
            while True:
                try:
                    # Get next task from queue
                    item = await self.task_queue.get()

                    # Check for shutdown signal
                    if item is _SENTINEL:
                        logger.info(f"Agent {agent_id} received shutdown signal")
                        break

                    # Unpack task
                    task_func, args, kwargs = item

                    # Execute task
                    try:
                        async with self._lock:
                            self.active_tasks += 1

                        logger.debug(
                            f"Agent {agent_id} executing {task_func.__name__} " f"({self.active_tasks} active)"
                        )

                        # Run the task
                        await task_func(*args, **kwargs)

                        logger.debug(f"Agent {agent_id} completed {task_func.__name__}")

                    except Exception as e:
                        logger.error(f"Agent {agent_id} error executing {task_func.__name__}: {e}", exc_info=True)
                    finally:
                        async with self._lock:
                            self.active_tasks -= 1

                    # Mark task as done
                    self.task_queue.task_done()

                except Exception as e:
                    logger.error(f"Agent {agent_id} unexpected error: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"Agent {agent_id} cancelled")
            raise
        finally:
            logger.info(f"Agent {agent_id} stopped")

    @property
    def active_agent_count(self) -> int:
        """Get count of currently active tasks being processed."""
        return self.active_tasks

    @property
    def queue_size(self) -> int:
        """Get number of tasks waiting in queue."""
        return self.task_queue.qsize()

    def get_status(self) -> dict:
        """Get pool status for monitoring."""
        return {
            "max_agents": self.max_agents,
            "started": self._started,
            "active_tasks": self.active_tasks,
            "queued_tasks": self.queue_size,
            "total_agents": len(self.agents),
        }
