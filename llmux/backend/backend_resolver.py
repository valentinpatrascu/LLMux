import logging
from importlib import import_module
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from core.config import ConfigProvider, get_config_provider
from common.enums import LLMEngine
from common.models import GenerationResponse


logger = logging.getLogger(__name__)

class BackendResolver:
    def __init__(self, config_provider: ConfigProvider) -> None:
        config = config_provider.get_config()
        self.engines = {}
        for engine in LLMEngine:
            # TODO: make backend path env var
            module = import_module(f"backend.engines.{engine.value}")
            if not hasattr(module, "get_engine"):
                raise ImportError(f"backend.engines.{engine.value} must expose get_engine()")
            self.engines[engine.value] = module.get_engine(generation_timeout_s=config.generation_timeout_s, models_list=config.models.workers + [config.models.aggregator])

    async def generate_response(self, prompt: str, model: str, llm_engine: LLMEngine, think: bool = False, system: str = "") -> GenerationResponse:
        return await self.engines[llm_engine].generate_response(prompt=prompt, model=model, think=think, system=system)

@lru_cache
def get_backend_resolver(config_provider: Annotated[ConfigProvider, Depends(get_config_provider)]) -> BackendResolver:
    return BackendResolver(config_provider)