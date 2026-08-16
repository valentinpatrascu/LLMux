from unittest.mock import AsyncMock, Mock

import pytest

from backend.backend_resolver import BackendResolver
from common.enums import LLMEngine


@pytest.mark.anyio
async def test_backend_resolver_forwards_generation_request():
    engine = Mock(generate_response=AsyncMock(return_value="result"))
    resolver = BackendResolver.__new__(BackendResolver)
    resolver.engines = {LLMEngine.OLLAMA: engine}

    result = await resolver.generate_response(
        prompt="Prompt",
        model="model",
        llm_engine=LLMEngine.OLLAMA,
        think=True,
        system="System",
    )

    assert result == "result"
    engine.generate_response.assert_awaited_once_with(
        prompt="Prompt",
        model="model",
        think=True,
        system="System",
    )
