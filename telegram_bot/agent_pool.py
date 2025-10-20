"""
Bounded agent pool for background task execution.

Prevents blocking by managing a fixed number of concurrent agents,
queuing excess tasks for processing when agents become available.

Supports priority-based task execution with four priority levels:
URGENT (0), HIGH (1), NORMAL (2), LOW (3)
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


# Sentinel object to signal agent shutdown
@dataclass(order=True)
class _Sentinel:
    """Sentinel for graceful shutdown, comparable for priority queue."""

    priority: int = field(default=-1)  # Highest priority to exit quickly


_SENTINEL = _Sentinel()


class TaskPriority(IntEnum):
    """
    Task priority levels for the agent pool.

    Lower numeric values = higher priority.
    Tasks are processed in priority order, with URGENT tasks first.
    """

    URGENT = 0  # User-facing errors, critical failures
    HIGH = 1  # User requests, interactive tasks
    NORMAL = 2  # Background tasks, routine operations (default)
    LOW = 3  # Maintenance, cleanup, analytics


class AgentPool:
    """
    Bounded agent pool for async task execution.

    Maintains a fixed number of agent coroutines that process tasks
    from a queue, ensuring concurrent work doesn't overwhelm the system.
    Uses poison pill pattern (SENTINEL) for graceful shutdown.
    """

    def __init__(self, max_agents: int = 3, max_queue_size: int = 1000, default_timeout: float = 300.0):
        """
        Initialize the agent pool.

        Args:
            max_agents: Maximum number of concurrent agents (default 3)
            max_queue_size: Maximum queue size, prevents unbounded growth (default 1000)
            default_timeout: Default task timeout in seconds (default 300s = 5min)
        """
        self.max_agents = max_agents
        self.max_queue_size = max_queue_size
        self.default_timeout = default_timeout
        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.agents: list[asyncio.Task] = []
        self.active_tasks = 0
        self._lock = asyncio.Lock()
        self._started = False
        self._task_counter = 0  # For FIFO ordering within same priority
        self._shutdown = False  # Track shutdown state

    async def start(self) -> None:
        """Start the agent pool by spawning agent coroutines."""
        async with self._lock:
            if self._started:
                logger.warning("Agent pool already started")
                return

            self._started = True
            self._shutdown = False

        logger.info(f"Starting agent pool with {self.max_agents} agents")

        # Spawn agent tasks
        for i in range(self.max_agents):
            agent_task = asyncio.create_task(self._agent(i))
            self.agents.append(agent_task)

    async def stop(self, timeout: float = 30.0) -> None:
        """
        Stop the agent pool gracefully.

        Args:
            timeout: Maximum time to wait for agents to finish (default 30s)
        """
        async with self._lock:
            if not self._started:
                logger.warning("Agent pool not started")
                return

            if self._shutdown:
                logger.warning("Agent pool already shutting down")
                return

            self._shutdown = True

        logger.info("Stopping agent pool...")

        # Send sentinel values to signal agents to stop
        for _ in range(self.max_agents):
            try:
                await asyncio.wait_for(self.task_queue.put(_SENTINEL), timeout=5.0)
            except TimeoutError:
                logger.error("Timeout sending shutdown signal to agents")

        # Wait for all agents to finish with timeout
        try:
            await asyncio.wait_for(asyncio.gather(*self.agents, return_exceptions=True), timeout=timeout)
            logger.info("Agent pool stopped successfully")
        except TimeoutError:
            logger.error(f"Agent pool shutdown timed out after {timeout}s, cancelling agents")
            for agent in self.agents:
                if not agent.done():
                    agent.cancel()
            # Wait briefly for cancellations
            await asyncio.gather(*self.agents, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error during agent pool shutdown: {e}", exc_info=True)

        self.agents.clear()
        self._started = False
        self._shutdown = False

    async def submit(
        self,
        task_func: Callable,
        *args: Any,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Submit a task for execution in the agent pool.

        Non-blocking - returns immediately after queueing the task.

        Args:
            task_func: Async callable to execute
            *args: Positional arguments for task_func
            priority: Task priority level (default: NORMAL)
            timeout: Task timeout in seconds (default: use pool default)
            **kwargs: Keyword arguments for task_func

        Raises:
            RuntimeError: If pool not started or shutting down
            asyncio.QueueFull: If queue is full (max_queue_size reached)
        """
        if not self._started:
            raise RuntimeError("Agent pool not started")

        if self._shutdown:
            raise RuntimeError("Agent pool is shutting down, cannot submit new tasks")

        # Use counter for FIFO ordering within same priority
        async with self._lock:
            counter = self._task_counter
            self._task_counter += 1

        # Use pool default if no timeout specified
        if timeout is None:
            timeout = self.default_timeout

        # Priority queue format: (priority, counter, (task_func, args, kwargs, timeout))
        # Lower priority number = processed first
        # Counter ensures FIFO for same priority
        try:
            self.task_queue.put_nowait((priority, counter, (task_func, args, kwargs, timeout)))
        except asyncio.QueueFull:
            logger.error(
                f"Task queue full ({self.max_queue_size}), rejecting task {task_func.__name__} "
                f"(priority: {priority.name})"
            )
            raise

        logger.debug(
            f"Task {task_func.__name__} submitted to agent pool "
            f"(priority: {priority.name}, timeout: {timeout}s, queue size: {self.task_queue.qsize()})"
        )

    async def _agent(self, agent_id: int) -> None:
        """
        Main agent loop - processes tasks from queue.

        Args:
            agent_id: Unique identifier for this agent
        """
        logger.info(f"Agent {agent_id} started")

        try:
            while True:
                item = None
                try:
                    # Get next task from queue (priority-ordered)
                    item = await self.task_queue.get()

                    # Check for shutdown signal
                    if isinstance(item, _Sentinel):
                        logger.info(f"Agent {agent_id} received shutdown signal")
                        self.task_queue.task_done()
                        break

                    # Unpack priority queue item: (priority, counter, (task_func, args, kwargs, timeout))
                    priority, counter, task_data = item
                    task_func, args, kwargs, timeout = task_data

                    # Execute task with timeout
                    task_name = getattr(task_func, "__name__", str(task_func))

                    try:
                        async with self._lock:
                            self.active_tasks += 1

                        logger.debug(
                            f"Agent {agent_id} executing {task_name} "
                            f"(priority: {TaskPriority(priority).name}, timeout: {timeout}s, active: {self.active_tasks})"
                        )

                        # Run the task with timeout
                        try:
                            await asyncio.wait_for(task_func(*args, **kwargs), timeout=timeout)
                            logger.debug(f"Agent {agent_id} completed {task_name}")
                        except TimeoutError:
                            logger.error(
                                f"Agent {agent_id} task {task_name} timed out after {timeout}s "
                                f"(priority: {TaskPriority(priority).name})"
                            )
                        except asyncio.CancelledError:
                            logger.warning(f"Agent {agent_id} task {task_name} cancelled")
                            raise
                        except Exception as e:
                            logger.error(
                                f"Agent {agent_id} error executing {task_name}: {e} "
                                f"(priority: {TaskPriority(priority).name})",
                                exc_info=True,
                            )

                    finally:
                        async with self._lock:
                            self.active_tasks -= 1

                    # Mark task as done
                    self.task_queue.task_done()

                except asyncio.CancelledError:
                    # Re-raise to exit loop during shutdown
                    logger.info(f"Agent {agent_id} cancelled during task processing")
                    if item is not None:
                        self.task_queue.task_done()
                    raise

                except Exception as e:
                    # Catch-all for unexpected errors (e.g., unpacking errors)
                    logger.error(f"Agent {agent_id} unexpected error in main loop: {e}", exc_info=True)
                    if item is not None:
                        self.task_queue.task_done()

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
            "max_queue_size": self.max_queue_size,
            "default_timeout": self.default_timeout,
            "started": self._started,
            "shutdown": self._shutdown,
            "active_tasks": self.active_tasks,
            "queued_tasks": self.queue_size,
            "total_agents": len(self.agents),
            "queue_utilization": f"{(self.queue_size / self.max_queue_size * 100):.1f}%",
        }
