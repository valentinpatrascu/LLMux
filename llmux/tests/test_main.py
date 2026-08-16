from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

import main
from common.concurrency import BoundedSemaphore


@pytest.mark.anyio
async def test_lifespan_initializes_capacity_and_recovers_jobs(monkeypatch):
    config_provider = Mock()
    config_provider.get_config.return_value = SimpleNamespace(
        max_concurrent_jobs=2,
        max_queued_jobs=4,
    )
    job_repository = Mock(fail_unfinished_jobs=AsyncMock(return_value=3))
    engine = Mock(dispose=AsyncMock())

    monkeypatch.setattr(main, "get_config_provider", lambda: config_provider)
    monkeypatch.setattr(main, "get_job_repository", lambda: job_repository)
    monkeypatch.setattr(main, "engine", engine)

    test_app = FastAPI()

    async with main.lifespan(test_app):
        assert isinstance(test_app.state.semaphore, BoundedSemaphore)
        job_repository.fail_unfinished_jobs.assert_awaited_once_with()
        engine.dispose.assert_not_awaited()

    engine.dispose.assert_awaited_once_with()

