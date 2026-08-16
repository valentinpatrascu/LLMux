import asyncio

import pytest

from common.concurrency import BoundedSemaphore
from common.exceptions import ServerCapacityExceeded


@pytest.mark.anyio
async def test_bounded_semaphore_limits_waiting_jobs():
    semaphore = BoundedSemaphore(max_concurrent=1, max_waiting=1)
    processing_started = asyncio.Event()
    release_processing = asyncio.Event()
    waiting_started = asyncio.Event()

    async def process_job():
        async with semaphore:
            processing_started.set()
            await release_processing.wait()

    async def wait_for_processing_slot():
        waiting_started.set()
        async with semaphore:
            return

    processing = asyncio.create_task(process_job())
    await processing_started.wait()

    waiting = asyncio.create_task(wait_for_processing_slot())
    await waiting_started.wait()
    await asyncio.sleep(0)

    assert semaphore.at_capacity is True
    with pytest.raises(ServerCapacityExceeded):
        async with semaphore:
            pass

    release_processing.set()
    await asyncio.gather(processing, waiting)
    assert semaphore.at_capacity is False


@pytest.mark.anyio
async def test_bounded_semaphore_releases_slot_after_error():
    semaphore = BoundedSemaphore(max_concurrent=1, max_waiting=1)

    with pytest.raises(RuntimeError, match="job failed"):
        async with semaphore:
            raise RuntimeError("job failed")

    async with semaphore:
        pass

