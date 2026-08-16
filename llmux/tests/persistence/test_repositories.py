from uuid import uuid7

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.enums import FailureCodes, JobStatus
from common.exceptions import EntityNotFoundError
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
    await jobs.update_job_record(request_id, job_status=JobStatus.PROCESSING)

    job = await jobs.get_job_record(request_id)
    assert job.prompt == "Prompt"
    assert job.job_status == JobStatus.PROCESSING


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
        await jobs.update_job_record(uuid7(), job_status=JobStatus.FAILED)
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

        if previous_status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            assert job.job_status == previous_status
            assert job.finished_at is None
        else:
            assert job.job_status == JobStatus.FAILED
            assert job.failure["code"] == FailureCodes.PROCESS_INTERRUPTED.value
            assert job.finished_at is not None

    assert await jobs.fail_unfinished_jobs() == 0
