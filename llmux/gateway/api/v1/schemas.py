import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, UUID7, StrictBool, StrictStr, field_validator

from core.config import get_config_provider
from common.enums import JobStatus, LLMEngine, AggregationStrategy
from common.models import FailureDetails

class PromptSubmit(BaseModel):
    text: StrictStr = Field(min_length=1, max_length=get_config_provider().get_config().max_prompt_length_char)

    @field_validator("text", mode="after")
    def normalize_text(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()

        if not normalized:
            raise ValueError("Prompt must not be empty or whitespace-only")

        return normalized

class JobSubmit(BaseModel):
    id: UUID7

class JobCancellation(BaseModel):
    id: UUID7
    job_status: JobStatus

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    prompt: str = Field(min_length=1)
    created_at: datetime
    job_status: JobStatus  
    done: StrictBool
    failure: FailureDetails | None = Field(default=None)
    llm_engine: LLMEngine | None = Field(default=None)
    aggregation_strategy: AggregationStrategy | None = Field(default=None)
    response: str | None = Field(default=None)
    finished_at: datetime | None = None
    