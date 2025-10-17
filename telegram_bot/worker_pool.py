"""
Bounded worker pool for background task execution.

Prevents blocking by managing a fixed number of concurrent workers,
queuing excess tasks for processing when workers become available.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel object to signal worker shutdown
_SENTINEL = object()


class WorkerPool:
    """
    Bounded worker pool for async task execution.

    Maintains a fixed number of worker coroutines that process tasks
    from a queue, ensuring concurrent work doesn't overwhelm the system.
    Uses poison pill pattern (SENTINEL) for graceful shutdown.
    """

    def __init__(self, max_workers: int = 3):
        """
        Initialize the worker pool.

        Args:
            max_workers: Maximum number of concurrent workers (default 3)
        """
        self.max_workers = max_workers
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.active_tasks = 0
        self._lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        """Start the worker pool by spawning worker coroutines."""
        if self._started:
            logger.warning("Worker pool already started")
            return

        self._started = True
        logger.info(f"Starting worker pool with {self.max_workers} workers")

        # Spawn worker tasks
        for i in range(self.max_workers):
            worker_task = asyncio.create_task(self._worker(i))
            self.workers.append(worker_task)

    async def stop(self) -> None:
        """Stop the worker pool gracefully."""
        if not self._started:
            logger.warning("Worker pool not started")
            return

        logger.info("Stopping worker pool...")

        # Send sentinel values to signal workers to stop
        for _ in range(self.max_workers):
            await self.task_queue.put(_SENTINEL)

        # Wait for all workers to finish
        try:
            async with asyncio.timeout(30):
                await asyncio.gather(*self.workers)
            logger.info("Worker pool stopped successfully")
        except TimeoutError:
            logger.warning("Worker pool stop timeout, cancelling workers")
            for worker in self.workers:
                worker.cancel()
            try:
                await asyncio.gather(*self.workers)
            except asyncio.CancelledError:
                pass

        self.workers.clear()
        self._started = False

    async def submit(self, task_func: Callable, *args: Any, **kwargs: Any) -> None:
        """
        Submit a task for execution in the worker pool.

        Non-blocking - returns immediately after queueing the task.

        Args:
            task_func: Async callable to execute
            *args: Positional arguments for task_func
            **kwargs: Keyword arguments for task_func
        """
        if not self._started:
            raise RuntimeError("Worker pool not started")

        # Queue the task (non-blocking)
        await self.task_queue.put((task_func, args, kwargs))
        logger.debug(f"Task submitted to worker pool (queue size: {self.task_queue.qsize()})")

    async def _worker(self, worker_id: int) -> None:
        """
        Main worker loop - processes tasks from queue.

        Args:
            worker_id: Unique identifier for this worker
        """
        logger.info(f"Worker {worker_id} started")

        try:
            while True:
                try:
                    # Get next task from queue
                    item = await self.task_queue.get()

                    # Check for shutdown signal
                    if item is _SENTINEL:
                        logger.info(f"Worker {worker_id} received shutdown signal")
                        break

                    # Unpack task
                    task_func, args, kwargs = item

                    # Execute task
                    try:
                        async with self._lock:
                            self.active_tasks += 1

                        logger.debug(
                            f"Worker {worker_id} executing {task_func.__name__} " f"({self.active_tasks} active)"
                        )

                        # Run the task
                        await task_func(*args, **kwargs)

                        logger.debug(f"Worker {worker_id} completed {task_func.__name__}")

                    except Exception as e:
                        logger.error(f"Worker {worker_id} error executing {task_func.__name__}: {e}", exc_info=True)
                    finally:
                        async with self._lock:
                            self.active_tasks -= 1

                    # Mark task as done
                    self.task_queue.task_done()

                except Exception as e:
                    logger.error(f"Worker {worker_id} unexpected error: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"Worker {worker_id} cancelled")
            raise
        finally:
            logger.info(f"Worker {worker_id} stopped")

    @property
    def active_worker_count(self) -> int:
        """Get count of currently active tasks being processed."""
        return self.active_tasks

    @property
    def queue_size(self) -> int:
        """Get number of tasks waiting in queue."""
        return self.task_queue.qsize()

    def get_status(self) -> dict:
        """Get pool status for monitoring."""
        return {
            "max_workers": self.max_workers,
            "started": self._started,
            "active_tasks": self.active_tasks,
            "queued_tasks": self.queue_size,
            "total_workers": len(self.workers),
        }
