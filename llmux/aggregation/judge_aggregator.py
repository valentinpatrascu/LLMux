import logging
from uuid import UUID
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends

from core.config import ConfigProvider, get_config_provider
from common.enums import JobStatus, AggregationStrategy
from backend.backend_resolver import BackendResolver, get_backend_resolver
from persistence.repositories import JobRepository, get_job_repository, ConversationRepository, get_conversation_repository


logger = logging.getLogger(__name__)

class JudgeAggregator:
    def __init__(self, config_provider: ConfigProvider, backend_resolver: BackendResolver, job_repository: JobRepository, conversation_repository: ConversationRepository) -> None:
        self.config_provider = config_provider
        self.backend_resolver = backend_resolver
        self.job_repository = job_repository
        self.conversation_repository = conversation_repository

    def build_aggregate_prompt(self, prompt: str, worker_model_outputs: list[dict]) -> str:
        candidates = "\n\n".join(
            (
                f"<CANDIDATE {i}>\n"
                f'{output["output"]}\n'
                f"</CANDIDATE>"
            )
            for i, output in enumerate(worker_model_outputs)
        )

        return (
            "<ORIGINAL_REQUEST>\n"
            f"{prompt}\n"
            "</ORIGINAL_REQUEST>\n\n"
            f"{candidates}"
        )

    async def set_complete(self, request_id: UUID, prompt: str, response: str, aggregation_output: dict, finished_at: datetime) -> None:
        # TODO: bind them under the same session
        await self.conversation_repository.add_conversation(request_id=request_id, prompt=prompt, response=response)
        await self.job_repository.update_job_record(request_id=request_id, job_status=JobStatus.COMPLETED, aggregation_output=aggregation_output, finished_at=finished_at)

    async def store_aggregation_config(self, request_id: UUID, aggregation_strategy: AggregationStrategy, aggregation_model: str) -> None:
        await self.job_repository.update_job_record(request_id, aggregation_strategy=aggregation_strategy, aggregation_model=aggregation_model)
    
    async def mark_status(self, request_id: UUID, job_status: JobStatus) -> None:
        await self.job_repository.update_job_record(request_id, job_status=job_status)

    async def aggregate(self, request_id: UUID) -> None:
        config = self.config_provider.get_config()
        aggregation_strategy = config.aggregation_strategy
        aggregation_model = config.models.aggregator
        aggregation_system_prompt = config.aggregation_system_prompt
        llm_engine = config.llm_engine

        logger.info(f"Aggregating results using {aggregation_strategy} based strategy using {aggregation_model}")

        await self.store_aggregation_config(request_id=request_id, aggregation_strategy=aggregation_strategy, aggregation_model=aggregation_model)
        await self.mark_status(request_id=request_id, job_status=JobStatus.AGGREGATING)

        current_job = await self.job_repository.get_job_record(request_id=request_id)
        prompt = current_job.prompt

        response = await self.backend_resolver.generate_response(
            prompt=self.build_aggregate_prompt(prompt=prompt, worker_model_outputs=current_job.worker_model_outputs),
            model=aggregation_model, 
            llm_engine=llm_engine,
            system=aggregation_system_prompt
        )

        await self.set_complete(
            request_id=request_id, 
            prompt=prompt, 
            response=response.response, 
            aggregation_output=response.model_dump(),
            finished_at=datetime.now(timezone.utc)
        )


def get_aggregator(
    config_provider: Annotated[ConfigProvider, Depends(get_config_provider)],
    backend_resolver: Annotated[BackendResolver, Depends(get_backend_resolver)],
    job_repository: Annotated[JobRepository, Depends(get_job_repository)],
    conversation_repository: Annotated[ConversationRepository, Depends(get_conversation_repository)],
) -> JudgeAggregator:
    aggregator = JudgeAggregator(
        config_provider=config_provider, 
        backend_resolver=backend_resolver, 
        job_repository=job_repository, 
        conversation_repository=conversation_repository
    )
    return aggregator
