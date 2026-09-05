import asyncio
from datetime import datetime, timezone
from uuid import uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.enums import FailureCodes, JobStatus
from common.exceptions import (
    EntityNotFoundError,
    JobCancelledError,
    JobTerminalStateError,
)
from persistence.repositories import ConversationRepository, JobRepository


def repositories(test_engine):
    sessions = async_sessionmaker(test_engine, class_=AsyncSession)
    return JobRepository(sessions), ConversationRepository(sessions)


@pytest.mark.anyio
async def test_job_repository_lifecycle(test_engine, setup_database):
    jobs, _ = repositories(test_engine)
    request_id = uuid7()

    await jobs.add_job_record(
        request_id=request_id,
        prompt="Prompt",
        job_status=JobStatus.SUBMITTED,
    )
    await jobs.update_job_record_status(request_id, job_status=JobStatus.PROCESSING)

    job = await jobs.get_job_record(request_id)
    assert job.prompt == "Prompt"
    assert job.job_status == JobStatus.PROCESSING


@pytest.mark.anyio
async def test_update_job_record_details_rejects_status_changes(test_engine):
    jobs, _ = repositories(test_engine)

    with pytest.raises(
        ValueError,
        match="Job status must be changed through a lifecycle transition method",
    ):
        await jobs.update_job_record_details(
            uuid7(),
            job_status=JobStatus.COMPLETED,
        )


@pytest.mark.anyio
async def test_conversation_repository_lifecycle(test_engine, setup_database):
    _, conversations = repositories(test_engine)
    request_id = uuid7()

    await conversations.add_conversation(
        request_id=request_id,
        prompt="Prompt",
        response="Response",
    )

    conversation = await conversations.get_conversation(request_id)
    assert conversation.prompt == "Prompt"
    assert conversation.response == "Response"


@pytest.mark.anyio
async def test_repositories_raise_when_entity_is_missing(test_engine, setup_database):
    jobs, conversations = repositories(test_engine)

    with pytest.raises(EntityNotFoundError):
        await jobs.get_job_record(uuid7())
    with pytest.raises(EntityNotFoundError):
        await jobs.update_job_record_status(uuid7(), job_status=JobStatus.FAILED)
    with pytest.raises(EntityNotFoundError):
        await conversations.get_conversation(uuid7())


@pytest.mark.anyio
async def test_fail_unfinished_jobs_marks_only_non_terminal_jobs(
    test_engine,
    setup_database,
):
    jobs, _ = repositories(test_engine)

    # Normalize records committed by earlier repository tests because this test
    # suite intentionally shares one PostgreSQL schema for the session.
    await jobs.fail_unfinished_jobs()

    jobs_by_status = {}
    for job_status in JobStatus:
        request_id = uuid7()
        jobs_by_status[job_status] = request_id
        await jobs.add_job_record(
            request_id=request_id,
            prompt=f"Prompt for {job_status.value}",
            job_status=job_status,
        )

    recovered = await jobs.fail_unfinished_jobs()

    assert recovered == 4
    for previous_status, request_id in jobs_by_status.items():
        job = await jobs.get_job_record(request_id)

        if previous_status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            assert job.job_status == previous_status
            assert job.finished_at is None
        else:
            assert job.job_status == JobStatus.FAILED
            assert job.failure["code"] == FailureCodes.PROCESS_INTERRUPTED.value
            assert job.finished_at is not None

    assert await jobs.fail_unfinished_jobs() == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "initial_status",
    [
        JobStatus.SUBMITTED,
        JobStatus.PROCESSING,
        JobStatus.PARTIAL,
        JobStatus.AGGREGATING,
    ],
)
async def test_cancel_job_from_active_status(
    test_engine,
    setup_database,
    initial_status: JobStatus,
):
    jobs, _ = repositories(test_engine)
    request_id = uuid7()
    await jobs.add_job_record(
        request_id=request_id,
        prompt="Prompt",
        job_status=initial_status,
    )

    await jobs.cancel_job(request_id)

    job = await jobs.get_job_record(request_id)
    assert job.job_status == JobStatus.CANCELLED


@pytest.mark.anyio
async def test_cancel_job_reports_existing_state(test_engine, setup_database):
    jobs, _ = repositories(test_engine)

    cancelled_id = uuid7()
    await jobs.add_job_record(
        request_id=cancelled_id,
        prompt="Prompt",
        job_status=JobStatus.CANCELLED,
    )

    with pytest.raises(JobCancelledError):
        await jobs.cancel_job(cancelled_id)

    for terminal_status in (JobStatus.COMPLETED, JobStatus.FAILED):
        request_id = uuid7()
        await jobs.add_job_record(
            request_id=request_id,
            prompt="Prompt",
            job_status=terminal_status,
        )

        with pytest.raises(JobTerminalStateError):
            await jobs.cancel_job(request_id)

    with pytest.raises(EntityNotFoundError):
        await jobs.cancel_job(uuid7())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "transition",
    ["status", "fail", "complete"],
)
async def test_cancelled_job_rejects_later_state_transition(
    test_engine,
    setup_database,
    transition: str,
):
    jobs, _ = repositories(test_engine)
    request_id = uuid7()
    await jobs.add_job_record(
        request_id=request_id,
        prompt="Prompt",
        job_status=JobStatus.CANCELLED,
    )

    with pytest.raises(JobCancelledError):
        if transition == "status":
            await jobs.update_job_record_status(
                request_id,
                job_status=JobStatus.PROCESSING,
            )
        elif transition == "fail":
            await jobs.fail_job(
                request_id,
                job_status=JobStatus.FAILED,
                failure={"code": FailureCodes.PIPELINE_ERROR.value},
                finished_at=None,
            )
        else:
            await jobs.complete_job(
                request_id,
                job_status=JobStatus.COMPLETED,
                aggregation_output={},
                finished_at=None,
            )

    job = await jobs.get_job_record(request_id)
    assert job.job_status == JobStatus.CANCELLED


@pytest.mark.anyio
async def test_cancel_and_complete_are_atomic_competing_transitions(
    test_engine,
    setup_database,
):
    jobs, _ = repositories(test_engine)
    request_id = uuid7()
    await jobs.add_job_record(
        request_id=request_id,
        prompt="Prompt",
        job_status=JobStatus.AGGREGATING,
    )

    results = await asyncio.gather(
        jobs.cancel_job(request_id),
        jobs.complete_job(
            request_id,
            job_status=JobStatus.COMPLETED,
            aggregation_output={},
            finished_at=datetime.now(timezone.utc),
        ),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    error = next(result for result in results if isinstance(result, Exception))
    assert isinstance(error, (JobCancelledError, JobTerminalStateError))

    job = await jobs.get_job_record(request_id)
    assert job.job_status in {JobStatus.CANCELLED, JobStatus.COMPLETED}
