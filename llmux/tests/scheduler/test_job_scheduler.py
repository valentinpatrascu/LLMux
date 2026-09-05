from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid7

import pytest

from common.enums import FailureCodes, JobStatus, LLMEngine
from common.exceptions import GenerationError, GenerationTimeout, JobCancelledError
from common.models import GenerationMetrics, GenerationResponse
from common.concurrency import BoundedSemaphore
from scheduler.job_scheduler import Scheduler


def make_scheduler():
    config = Mock()
    config.get_config.return_value = SimpleNamespace(
        llm_engine=LLMEngine.OLLAMA,
        models=SimpleNamespace(workers=["model-a", "model-b"]),
    )
    backend = Mock(generate_response=AsyncMock())
    aggregator = Mock(aggregate=AsyncMock())
    jobs = Mock(
        update_job_record_details=AsyncMock(),
        update_job_record_status=AsyncMock(),
        fail_job=AsyncMock(),
    )
    return Scheduler(config, backend, aggregator, jobs), backend, aggregator, jobs


def make_semaphore():
    return BoundedSemaphore(max_concurrent=1, max_waiting=1)


@pytest.mark.anyio
async def test_dispatch_success():
    scheduler, backend, aggregator, jobs = make_scheduler()
    request_id = uuid7()
    backend.generate_response.side_effect = [
        GenerationResponse(
            response=text,
            metrics=GenerationMetrics(
                total_duration_s=1,
                prompt_tokens=2,
                output_tokens=3,
            ),
        )
        for text in ["Response A", "Response B"]
    ]

    await scheduler.dispatch("Prompt", request_id, make_semaphore())

    assert backend.generate_response.await_args_list == [
        call(prompt="Prompt", model="model-a", llm_engine=LLMEngine.OLLAMA),
        call(prompt="Prompt", model="model-b", llm_engine=LLMEngine.OLLAMA),
    ]
    assert jobs.update_job_record_details.await_args_list[-1].kwargs[
        "worker_model_outputs"
    ] == [
        {
            "model": "model-a",
            "output": "Response A",
            "metrics": {
                "total_duration_s": 1.0,
                "prompt_tokens": 2,
                "output_tokens": 3,
            },
        },
        {
            "model": "model-b",
            "output": "Response B",
            "metrics": {
                "total_duration_s": 1.0,
                "prompt_tokens": 2,
                "output_tokens": 3,
            },
        },
    ]
    aggregator.aggregate.assert_awaited_once_with(request_id=request_id)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (GenerationTimeout(), FailureCodes.GENERATION_TIMEOUT),
        (GenerationError(), FailureCodes.GENERATION_ERROR),
        (RuntimeError(), FailureCodes.PIPELINE_ERROR),
    ],
)
async def test_dispatch_failure(error: Exception, code: FailureCodes):
    scheduler, backend, aggregator, jobs = make_scheduler()
    backend.generate_response.side_effect = error

    await scheduler.dispatch("Prompt", uuid7(), make_semaphore())

    failure = jobs.fail_job.await_args
    assert failure.kwargs["job_status"] == JobStatus.FAILED
    assert failure.kwargs["failure"]["code"] == code
    assert failure.kwargs["finished_at"].tzinfo is not None
    aggregator.aggregate.assert_not_awaited()


@pytest.mark.anyio
async def test_dispatch_ignores_failure_storage_error():
    scheduler, backend, _, jobs = make_scheduler()
    backend.generate_response.side_effect = GenerationError()
    jobs.fail_job.side_effect = RuntimeError()

    await scheduler.dispatch("Prompt", uuid7(), make_semaphore())

    jobs.fail_job.assert_awaited_once()


@pytest.mark.anyio
async def test_dispatch_stops_when_job_was_cancelled():
    scheduler, backend, aggregator, jobs = make_scheduler()
    jobs.update_job_record_status.side_effect = JobCancelledError()

    await scheduler.dispatch("Prompt", uuid7(), make_semaphore())

    backend.generate_response.assert_not_awaited()
    aggregator.aggregate.assert_not_awaited()
    assert jobs.update_job_record_details.await_count == 2
    assert jobs.update_job_record_details.await_args.kwargs[
        "finished_at"
    ].tzinfo is not None
