import os
from collections.abc import AsyncGenerator

os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://app_user:valentin@localhost/test_app"
)

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from common.enums import JobStatus
from common.concurrency import BoundedSemaphore
from persistence.repositories import ConversationRepository, JobRepository
from persistence.database import Base, get_db
from main import app

import asyncio
import sys

pytest_plugins = ["anyio"]

@pytest.fixture(scope="session")
def anyio_backend():
    if sys.platform == "win32":
        # psycopg's async implementation requires an event loop with add_reader().
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}

    return "asyncio"

@pytest.fixture(scope="session")
def test_engine():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        poolclass=NullPool
    )
    return engine

@pytest.fixture(scope="session")
async def setup_database(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()

@pytest.fixture
async def db_session(
    test_engine,
    setup_database,
) -> AsyncGenerator[AsyncSession]:
    conn = await test_engine.connect()
    trans = await conn.begin()

    test_async_session = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async with test_async_session() as session:
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
            await conn.close()

@pytest.fixture
async def client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient]:

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.state.semaphore = BoundedSemaphore(max_concurrent=1, max_waiting=3)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()

async def create_job(
    test_engine,
    job_id: UUID,
    prompt: str = "Mock prompt",
    job_status: JobStatus = JobStatus.SUBMITTED,
    **values,
) -> None:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    job_repository = JobRepository(session_factory)

    await job_repository.add_job_record(
        request_id=job_id,
        prompt=prompt,
        job_status=job_status,
        **values,
    )


async def create_conversation(
    test_engine,
    job_id: UUID,
    prompt: str = "Mock prompt",
    response: str = "Mock response",
) -> None:
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    conversation_repository = ConversationRepository(session_factory)

    await conversation_repository.add_conversation(
        request_id=job_id,
        prompt=prompt,
        response=response,
    )


