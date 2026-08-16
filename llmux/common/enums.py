from enum import Enum


class JobStatus(str, Enum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    PARTIAL = "partial"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"


class LLMEngine(str, Enum):
    OLLAMA = "ollama"


class AggregationStrategy(str, Enum):
    JUDGE = "judge"


class FailureCodes(str, Enum):
    GENERATION_TIMEOUT = "generation_timeout"
    GENERATION_ERROR = "generation_error"
    AGGREGATION_CONTEXT_EXCEEDED = "aggregation_context_exceeded"
    PIPELINE_ERROR = "pipeline_error"
    SERVER_CAPACITY_EXCEEDED = "server_capacity_exceeded"
    PROCESS_INTERRUPTED = "process_interrupted"
    