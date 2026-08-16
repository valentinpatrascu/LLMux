from pydantic import BaseModel

from common.enums import FailureCodes

class FailureDetails(BaseModel):
    code: FailureCodes
    details: str | None = None

class GenerationMetrics(BaseModel):
    total_duration_s: float
    prompt_tokens: int
    output_tokens: int

class GenerationResponse(BaseModel):
    response: str
    metrics: GenerationMetrics