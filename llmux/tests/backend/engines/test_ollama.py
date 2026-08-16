from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from ollama import RequestError

from backend.engines.ollama import OllamaEngine
from common.exceptions import GenerationError, GenerationTimeout


@pytest.mark.anyio
async def test_ensure_models_pulls_only_missing_models():
    client = AsyncMock()
    client.list.return_value = SimpleNamespace(
        models=[SimpleNamespace(model="installed:latest")]
    )
    engine = OllamaEngine(client, ["installed", "missing"])

    await engine.ensure_models(["installed", "missing"])

    client.pull.assert_awaited_once_with(model="missing")


@pytest.mark.anyio
async def test_generate_response():
    client = AsyncMock()
    client.list.return_value = SimpleNamespace(
        models=[SimpleNamespace(model="model:latest")]
    )
    client.generate.return_value = {
        "response": "Answer",
        "total_duration": 2_000_000_000,
        "prompt_eval_count": 10,
        "eval_count": 20,
    }

    response = await OllamaEngine(client, ["model"]).generate_response(
        "Prompt",
        "model",
    )

    assert response.response == "Answer"
    assert response.metrics.total_duration_s == 2
    assert response.metrics.prompt_tokens == 10
    assert response.metrics.output_tokens == 20


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.TimeoutException("Timeout"), GenerationTimeout),
        (RequestError("Request failed"), GenerationError),
    ],
)
async def test_generate_response_translates_errors(error: Exception, expected):
    client = AsyncMock()
    client.list.side_effect = error

    with pytest.raises(expected):
        await OllamaEngine(client, ["model"]).generate_response("Prompt", "model")
