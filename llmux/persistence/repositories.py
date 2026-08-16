from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from persistence.database import AsyncSessionLocal
from persistence.models import IngressLog, JobRecord, Conversation
from common.exceptions import EntityNotFoundError
from common.enums import JobStatus, FailureCodes
from common.models import FailureDetails


class JobRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_job_record(self, **values) -> None:
        async with self.session_factory() as db:
            db.add(JobRecord(
                **values
            ))

            await db.commit()

    async def get_job_record(self, request_id: UUID) -> JobRecord:
        async with self.session_factory() as db:
            result = await db.execute(
                select(JobRecord)
                .where(JobRecord.request_id == request_id),
            )
            job = result.scalar_one_or_none()

            if job is None:
                raise EntityNotFoundError(f"No JobRecord found for request_id={request_id}")
            return job

    async def update_job_record(self, request_id: UUID, **values) -> None:
        async with self.session_factory() as db:
            result = await db.execute(
                update(JobRecord)
                .where(JobRecord.request_id == request_id)
                .values(**values)
            )
            if result.rowcount == 0:
                raise EntityNotFoundError(f"No JobRecord found for request_id={request_id}")
            
            await db.commit()

    async def fail_unfinished_jobs(self) -> int:
        failing_statuses = [status for status in JobStatus if status not in {JobStatus.COMPLETED, JobStatus.FAILED}]
        async with self.session_factory() as db:
            result = await db.execute(
                update(JobRecord)
                .where(JobRecord.job_status.in_(failing_statuses))
                .values(
                    job_status=JobStatus.FAILED,
                    failure=FailureDetails(code=FailureCodes.PROCESS_INTERRUPTED, details="Process interrupted").model_dump(),
                    finished_at=datetime.now(timezone.utc))
            )
            
            await db.commit()

            return result.rowcount
        
class ConversationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_conversation(self, **values) -> None:
        async with self.session_factory() as db:
            db.add(Conversation(
                **values
            ))

            await db.commit()

    async def get_conversation(self, request_id: UUID) -> Conversation:
        async with self.session_factory() as db:
            result = await db.execute(
                select(Conversation)
                .where(Conversation.request_id == request_id),
            )
            conversation = result.scalar_one_or_none()

            if conversation is None:
                raise EntityNotFoundError(f"No conversation found for request_id={request_id}")
            return conversation

class IngressLogsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def add_ingress_log(self, **values) -> None:
        async with self.session_factory() as db:
            db.add(IngressLog(
                **values
            ))

            await db.commit()


def get_job_repository() -> JobRepository:
    return JobRepository(session_factory=AsyncSessionLocal)

def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository(session_factory=AsyncSessionLocal)

def get_ingress_log_repository() -> IngressLogsRepository:
    return IngressLogsRepository(session_factory=AsyncSessionLocal)