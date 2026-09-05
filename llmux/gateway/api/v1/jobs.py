import logging
from datetime import datetime, timezone
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import HTTPException, status
from fastapi import BackgroundTasks
from fastapi.requests import Request
from sqlalchemy.exc import SQLAlchemyError

from common.enums import JobStatus, FailureCodes
from common.models import FailureDetails
from common.exceptions import EntityNotFoundError, JobCancelledError, JobTerminalStateError
from persistence.repositories import JobRepository, get_job_repository, ConversationRepository, get_conversation_repository
from gateway.api.v1.schemas import JobSubmit, JobResponse, PromptSubmit, JobCancellation
from scheduler.job_scheduler import Scheduler, get_scheduler


router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("", response_model=JobSubmit, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    request: Request,
    prompt: PromptSubmit, 
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    scheduler: Annotated[Scheduler, Depends(get_scheduler)],
    background_tasks: BackgroundTasks
):
    request_id = request.state.request_id
    semaphore = request.app.state.semaphore

    if semaphore.at_capacity:

        failure = FailureDetails(code=FailureCodes.SERVER_CAPACITY_EXCEEDED, details=f"Server capacity exceeded at request_id={request_id}.")

        try:
            await job_repository.add_job_record(
                    request_id=request_id,
                    prompt=prompt.text,
                    job_status=JobStatus.FAILED,
                    failure=failure.model_dump(), 
                    finished_at=datetime.now(timezone.utc)
                    
                )
        except Exception as e:
            logger.exception(e, extra={"request_id": str(request_id)})
        finally:
            raise HTTPException(
                status_code=503,
                detail="Server at capacity. Please retry shortly.",
            )
    
    try:
        await job_repository.add_job_record(
            request_id=request_id,
            prompt=prompt.text,
            job_status=JobStatus.SUBMITTED,
        )
    except SQLAlchemyError:
        logger.exception("Could not create job", extra={"request_id": str(request_id)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not accept the job. Please retry.",
        )

    try:
        background_tasks.add_task(scheduler.dispatch, prompt=prompt.text, request_id=request_id, semaphore=semaphore)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while processing. Please retry.",
        )   

    return JobSubmit(id=request_id)

@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    conversation_repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
):

    try:
        job = await job_repository.get_job_record(request_id=job_id)
    except SQLAlchemyError:
        logger.exception("Could not get job", extra={"request_id": str(job_id)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not get the job. Please retry.",
        )
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Job not found."
        )

    conversation = None

    if job.job_status == JobStatus.COMPLETED:
        try:
            conversation = await conversation_repository.get_conversation(request_id=job_id)
        except SQLAlchemyError:
            logger.exception("Could not get the conversation", extra={"request_id": str(job_id)})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not get the conversation. Please retry.",
            )
        except EntityNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="Internal incosistency. Conversation not found."
            )

    return {
        "prompt": job.prompt,
        'created_at': job.created_at,
        'job_status': job.job_status,
        'done': job.job_status in {JobStatus.COMPLETED,JobStatus.FAILED},
        'failure': job.failure,
        'llm_engine': job.llm_engine,
        'aggregation_strategy': job.aggregation_strategy,
        'response': conversation.response if conversation else None,
        'finished_at': job.finished_at
    }

@router.post("/{job_id}/cancel", response_model=JobCancellation, status_code=status.HTTP_200_OK)
async def cancel_job(
    job_id: UUID,
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
):
    try:
        await job_repository.cancel_job(request_id=job_id)
    except SQLAlchemyError:
        logger.exception("Could not get job", extra={"request_id": str(job_id)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not get the job. Please retry.",
        )
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Job not found."
        )
    except JobTerminalStateError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Job cannot be cancelled because it is already in terminal state."
        )
    except JobCancelledError:
        logger.info("Job already cancelled", extra={"request_id": str(job_id)})

    return JobCancellation(id=job_id, job_status=JobStatus.CANCELLED)

    

