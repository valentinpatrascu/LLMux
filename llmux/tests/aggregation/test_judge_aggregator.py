from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock
from uuid import uuid7

import pytest

from aggregation.judge_aggregator import JudgeAggregator
from common.enums import AggregationStrategy, JobStatus, LLMEngine
from common.models import GenerationMetrics, GenerationResponse


def make_aggregator():
    config = Mock()
    config.get_config.return_value = SimpleNamespace(
        aggregation_strategy=AggregationStrategy.JUDGE,
        aggregation_system_prompt="Combine responses",
        llm_engine=LLMEngine.OLLAMA,
        models=SimpleNamespace(aggregator="judge-model"),
    )
    backend = Mock(generate_response=AsyncMock())
    jobs = Mock(
        get_job_record=AsyncMock(),
        update_job_record_details=AsyncMock(),
        update_job_record_status=AsyncMock(),
        complete_job=AsyncMock(),
    )
    conversations = Mock(add_conversation=AsyncMock())
    return JudgeAggregator(config, backend, jobs, conversations), backend, jobs, conversations


def test_build_aggregate_prompt():
    aggregator, _, _, _ = make_aggregator()

    prompt = aggregator.build_aggregate_prompt(
        "Question",
        [{"output": "Answer A"}, {"output": "Answer B"}],
    )

    assert prompt == (
        "<ORIGINAL_REQUEST>\nQuestion\n</ORIGINAL_REQUEST>\n\n"
        "<CANDIDATE 0>\nAnswer A\n</CANDIDATE>\n\n"
        "<CANDIDATE 1>\nAnswer B\n</CANDIDATE>"
    )


@pytest.mark.anyio
async def test_aggregate_success():
    aggregator, backend, jobs, conversations = make_aggregator()
    request_id = uuid7()
    jobs.get_job_record.return_value = SimpleNamespace(
        prompt="Question",
        worker_model_outputs=[{"output": "Answer"}],
    )
    result = GenerationResponse(
        response="Final answer",
        metrics=GenerationMetrics(
            total_duration_s=1,
            prompt_tokens=2,
            output_tokens=3,
        ),
    )
    backend.generate_response.return_value = result

    await aggregator.aggregate(request_id)

    backend.generate_response.assert_awaited_once_with(
        prompt=(
            "<ORIGINAL_REQUEST>\nQuestion\n</ORIGINAL_REQUEST>\n\n"
            "<CANDIDATE 0>\nAnswer\n</CANDIDATE>"
        ),
        model="judge-model",
        llm_engine=LLMEngine.OLLAMA,
        system="Combine responses",
    )
    conversations.add_conversation.assert_awaited_once_with(
        request_id=request_id,
        prompt="Question",
        response="Final answer",
    )
    jobs.update_job_record_details.assert_awaited_once_with(
        request_id,
        aggregation_strategy=AggregationStrategy.JUDGE,
        aggregation_model="judge-model",
    )
    jobs.update_job_record_status.assert_awaited_once_with(
        request_id,
        job_status=JobStatus.AGGREGATING,
    )
    jobs.complete_job.assert_awaited_once_with(
        request_id=request_id,
        job_status=JobStatus.COMPLETED,
        aggregation_output=result.model_dump(),
        finished_at=ANY,
    )


@pytest.mark.anyio
async def test_aggregate_failure_does_not_complete_job():
    aggregator, backend, jobs, conversations = make_aggregator()
    jobs.get_job_record.return_value = SimpleNamespace(
        prompt="Question",
        worker_model_outputs=[{"output": "Answer"}],
    )
    backend.generate_response.side_effect = RuntimeError("Failed")

    with pytest.raises(RuntimeError, match="Failed"):
        await aggregator.aggregate(uuid7())

    conversations.add_conversation.assert_not_awaited()
    jobs.complete_job.assert_not_awaited()
