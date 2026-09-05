from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import UUID, uuid7

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from common.enums import AggregationStrategy, FailureCodes, JobStatus, LLMEngine
from common.concurrency import BoundedSemaphore
from core.config import get_config_provider
from gateway.api.v1.jobs import get_conversation_repository, get_job_repository
from main import app
from persistence.models import JobRecord
from scheduler.job_scheduler import get_scheduler
from tests.conftest import create_conversation, create_job


class StubScheduler:
    def __init__(self):
        self.calls = []

    async def dispatch(
        self,
        prompt: str,
        request_id: UUID,
        semaphore: BoundedSemaphore,
    ) -> None:
        self.calls.append((prompt, request_id, semaphore))


class BrokenRepository:
    async def add_job_record(self, **values) -> None:
        raise SQLAlchemyError()

    async def get_job_record(self, request_id: UUID) -> JobRecord:
        raise SQLAlchemyError()

    async def get_conversation(self, request_id: UUID) -> None:
        raise SQLAlchemyError()

    async def cancel_job(self, request_id: UUID) -> None:
        raise SQLAlchemyError()


@pytest.mark.anyio
async def test_submit_job(client: AsyncClient, test_engine):
    scheduler = StubScheduler()
    app.dependency_overrides[get_scheduler] = lambda: scheduler

    response = await client.post("/api/v1/jobs", json={"text": "  Hello   world  "})

    assert response.status_code == 202
    job_id = UUID(response.json()["id"])
    assert scheduler.calls == [("Hello world", job_id, app.state.semaphore)]

    async with AsyncSession(test_engine) as session:
        job = await session.scalar(
            select(JobRecord).where(JobRecord.request_id == job_id)
        )
    assert job.prompt == "Hello world"
    assert job.job_status == JobStatus.SUBMITTED


@pytest.mark.anyio
@pytest.mark.parametrize(
    "text",
    [
        "   ",
        "x" * (get_config_provider().get_config().max_prompt_length_char + 1),
    ],
    ids=["whitespace", "too-long"],
)
async def test_submit_job_rejects_invalid_prompt(client: AsyncClient, text: str):
    response = await client.post("/api/v1/jobs", json={"text": text})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_submit_job_handles_database_error(client: AsyncClient):
    app.dependency_overrides[get_job_repository] = BrokenRepository
    app.dependency_overrides[get_scheduler] = StubScheduler

    response = await client.post("/api/v1/jobs", json={"text": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not accept the job. Please retry."


@pytest.mark.anyio
async def test_submit_job_rejects_when_server_is_at_capacity(
    client: AsyncClient,
    test_engine,
):
    semaphore = Mock(at_capacity=True)
    app.state.semaphore = semaphore
    prompt = f"Capacity test {uuid7()}"

    response = await client.post("/api/v1/jobs", json={"text": prompt})

    assert response.status_code == 503
    assert response.json()["detail"] == "Server at capacity. Please retry shortly."

    async with AsyncSession(test_engine) as session:
        job = await session.scalar(
            select(JobRecord)
            .where(JobRecord.prompt == prompt)
        )

    assert job.job_status == JobStatus.FAILED
    assert job.failure["code"] == FailureCodes.SERVER_CAPACITY_EXCEEDED.value


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "done"),
    [
        (JobStatus.SUBMITTED, False),
        (JobStatus.PROCESSING, False),
        (JobStatus.PARTIAL, False),
        (JobStatus.AGGREGATING, False),
        (JobStatus.FAILED, True),
        (JobStatus.CANCELLED, True),
    ],
)
async def test_get_job_status(
    client: AsyncClient,
    test_engine,
    status: JobStatus,
    done: bool,
):
    job_id = uuid7()
    await create_job(test_engine, job_id, job_status=status)

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["job_status"] == status.value
    assert response.json()["done"] is done


@pytest.mark.anyio
async def test_get_completed_job(client: AsyncClient, test_engine):
    job_id = uuid7()
    finished_at = datetime.now(timezone.utc)
    await create_job(
        test_engine,
        job_id,
        job_status=JobStatus.COMPLETED,
        llm_engine=LLMEngine.OLLAMA,
        aggregation_strategy=AggregationStrategy.JUDGE,
        finished_at=finished_at,
    )
    await create_conversation(test_engine, job_id, response="Final response")

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["done"] is True
    assert body["response"] == "Final response"
    assert body["llm_engine"] == LLMEngine.OLLAMA.value
    assert body["aggregation_strategy"] == AggregationStrategy.JUDGE.value
    assert datetime.fromisoformat(body["finished_at"]) == finished_at


@pytest.mark.anyio
async def test_get_failed_job(client: AsyncClient, test_engine):
    job_id = uuid7()
    await create_job(
        test_engine,
        job_id,
        job_status=JobStatus.FAILED,
        failure={"code": FailureCodes.GENERATION_ERROR.value},
    )

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["failure"]["code"] == FailureCodes.GENERATION_ERROR.value


@pytest.mark.anyio
async def test_get_unknown_job(client: AsyncClient):
    response = await client.get(f"/api/v1/jobs/{uuid7()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


@pytest.mark.anyio
async def test_get_completed_job_without_conversation(client: AsyncClient, test_engine):
    job_id = uuid7()
    await create_job(test_engine, job_id, job_status=JobStatus.COMPLETED)

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal incosistency. Conversation not found."


@pytest.mark.anyio
@pytest.mark.parametrize("dependency", [get_job_repository, get_conversation_repository])
async def test_get_job_handles_database_error(
    client: AsyncClient,
    test_engine,
    dependency,
):
    job_id = uuid7()
    if dependency is get_conversation_repository:
        await create_job(test_engine, job_id, job_status=JobStatus.COMPLETED)
    app.dependency_overrides[dependency] = BrokenRepository

    response = await client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 503


@pytest.mark.anyio
@pytest.mark.parametrize(
    "job_status",
    [
        JobStatus.SUBMITTED,
        JobStatus.PROCESSING,
        JobStatus.PARTIAL,
        JobStatus.AGGREGATING,
    ],
)
async def test_cancel_job(
    client: AsyncClient,
    test_engine,
    job_status: JobStatus,
):
    job_id = uuid7()
    await create_job(test_engine, job_id, job_status=job_status)

    response = await client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(job_id),
        "job_status": JobStatus.CANCELLED.value,
    }

    async with AsyncSession(test_engine) as session:
        stored_status = await session.scalar(
            select(JobRecord.job_status).where(JobRecord.request_id == job_id)
        )

    assert stored_status == JobStatus.CANCELLED


@pytest.mark.anyio
async def test_cancel_job_is_idempotent(client: AsyncClient, test_engine):
    job_id = uuid7()
    await create_job(test_engine, job_id, job_status=JobStatus.CANCELLED)

    response = await client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert response.json()["job_status"] == JobStatus.CANCELLED.value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "job_status",
    [JobStatus.COMPLETED, JobStatus.FAILED],
)
async def test_cancel_job_rejects_terminal_job(
    client: AsyncClient,
    test_engine,
    job_status: JobStatus,
):
    job_id = uuid7()
    await create_job(test_engine, job_id, job_status=job_status)

    response = await client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Job cannot be cancelled because it is already in terminal state."
    )


@pytest.mark.anyio
async def test_cancel_unknown_job(client: AsyncClient):
    response = await client.post(f"/api/v1/jobs/{uuid7()}/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found."


@pytest.mark.anyio
async def test_cancel_job_handles_database_error(client: AsyncClient):
    app.dependency_overrides[get_job_repository] = BrokenRepository

    response = await client.post(f"/api/v1/jobs/{uuid7()}/cancel")

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not get the job. Please retry."
