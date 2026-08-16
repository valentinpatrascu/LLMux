import asyncio

from common.exceptions import ServerCapacityExceeded

class BoundedSemaphore:
    """
    Drop-in replacement for asyncio.Semaphore with a bounded waiting queue.
    Raises ServerCapacityExceeded if max_waiting is already reached.
    """

    def __init__(self, max_concurrent: int, max_waiting: int) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_waiting = max_waiting
        self._waiting = 0

    @property
    def at_capacity(self) -> bool:
        return self._waiting >= self._max_waiting

    async def __aenter__(self) -> "BoundedSemaphore":
        if self.at_capacity:
            raise ServerCapacityExceeded()
        self._waiting += 1
        try:
            await self._semaphore.acquire()
        finally:
            self._waiting -= 1  # moved from waiting → processing
        return self

    async def __aexit__(self, *args) -> None:
        self._semaphore.release()