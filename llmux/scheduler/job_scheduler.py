import logging
from datetime import datetime, timezone
from uuid import UUID
from typing import Annotated

from fastapi import Depends
from asyncio import Semaphore

from core.config import ConfigProvider, get_config_provider
from common.enums import JobStatus, LLMEngine, FailureCodes
from common.models import FailureDetails
from common.exceptions import GenerationTimeout, GenerationError
from backend.backend_resolver import BackendResolver, get_backend_resolver
from persistence.repositories import JobRepository, get_job_repository
from aggregation.judge_aggregator import JudgeAggregator, get_aggregator


logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, config_provider: ConfigProvider, backend_resolver: BackendResolver, aggregator: JudgeAggregator, job_repository: JobRepository) -> None:
        self.config_provider = config_provider
        self.backend_resolver = backend_resolver
        self.aggregator = aggregator
        self.job_repository = job_repository

    async def store_inference_config(self, request_id: UUID, llm_engine: LLMEngine, worker_models: list[str]) -> None:
        await self.job_repository.update_job_record(request_id=request_id, llm_engine=llm_engine, worker_models=worker_models)

    async def mark_status(self, request_id: UUID, job_status: JobStatus) -> None:
        await self.job_repository.update_job_record(request_id=request_id, job_status=job_status)

    async def store_worker_model_outputs(self, request_id: UUID, worker_model_outputs: list[dict]) -> None:
        await self.job_repository.update_job_record(request_id=request_id, worker_model_outputs=worker_model_outputs)

    async def set_failure(self, request_id: UUID, job_status: JobStatus, failure: FailureDetails, finished_at: datetime) -> None:
        await self.job_repository.update_job_record(request_id=request_id, job_status=job_status, failure=failure.model_dump(), finished_at=finished_at)
    
    async def dispatch(self, prompt: str, request_id: UUID, semaphore: Semaphore) -> None:

        async with semaphore:

            try:
                config = self.config_provider.get_config()
                worker_models = config.models.workers
                llm_engine = config.llm_engine

                await self.store_inference_config(request_id=request_id, llm_engine=llm_engine, worker_models=worker_models)
                await self.mark_status(request_id=request_id, job_status=JobStatus.PROCESSING)

                outputs = []
                
                for model in worker_models:
                    logger.info(f"Dispatching model {model} on {llm_engine} llm_engine for request_id={request_id}.")

                    response = await self.backend_resolver.generate_response(prompt=prompt, model=model, llm_engine=llm_engine)

                    outputs.append(
                        {
                            "model": model,
                            "output": response.response,
                            "metrics": response.metrics.model_dump()
                        }
                    )

                await self.store_worker_model_outputs(request_id=request_id, worker_model_outputs=outputs)

                await self.aggregator.aggregate(request_id=request_id)

            except GenerationTimeout:
                logger.exception(f"Generation timeout for request_id={request_id}.")

                failure = FailureDetails(code=FailureCodes.GENERATION_TIMEOUT, details=f"Generation timeout for request_id={request_id}.")

                try: 
                    await self.set_failure(request_id=request_id, job_status=JobStatus.FAILED, failure=failure, finished_at=datetime.now(timezone.utc))
                except Exception:
                    logger.exception(f"Failed to log failure in the db for request_id={request_id}.")

            except GenerationError:
                logger.exception(f"Generate results failed for request_id={request_id}.")

                failure = FailureDetails(code=FailureCodes.GENERATION_ERROR, details=f"Generate results failed for request_id={request_id}.")

                try:
                    await self.set_failure(request_id=request_id, job_status=JobStatus.FAILED, failure=failure, finished_at=datetime.now(timezone.utc))
                except Exception:
                    logger.exception(f"Failed to log failure in the db for request_id={request_id}.")

            except Exception:
                logger.exception(f"Job processing failed for request_id={request_id}.")

                failure = FailureDetails(code=FailureCodes.PIPELINE_ERROR, details=f"Job processing failed for request_id={request_id}.")

                try:
                    await self.set_failure(request_id=request_id, job_status=JobStatus.FAILED, failure=failure, finished_at=datetime.now(timezone.utc))
                except Exception:
                    logger.exception(f"Failed to log failure in the db for request_id={request_id}.")

        
def get_scheduler(
    config_provider: Annotated[ConfigProvider, Depends(get_config_provider)],
    backend_resolver: Annotated[BackendResolver, Depends(get_backend_resolver)],
    aggregator: Annotated[JudgeAggregator, Depends(get_aggregator)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
) -> Scheduler:
    return Scheduler(config_provider=config_provider, backend_resolver=backend_resolver, aggregator=aggregator, job_repository=job_repository)
