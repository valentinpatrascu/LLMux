import httpx
import asyncio
import logging

from ollama import AsyncClient, RequestError, ResponseError

from backend.engines.base import BaseEngine
from common.exceptions import GenerationTimeout, GenerationError
from common.models import GenerationResponse, GenerationMetrics

logger = logging.getLogger(__name__)

class OllamaEngine(BaseEngine):
    def __init__(self, client: AsyncClient, models_list: list) -> None:
        self.client = client
        self.models_list = models_list

    def get_missing_models(self, required, installed):
        installed_names = [m.model for m in installed.models]

        return [
            model for model in required
            if model not in installed_names
            and f"{model}:latest" not in installed_names
        ]

    async def ensure_models(self, models_list):
        missing_models = self.get_missing_models(models_list, await self.client.list())

        if len(missing_models):
            logger.info(f"Models: {missing_models} not found locally. Pulling the models...")
            await asyncio.gather(*(self.client.pull(model=model) for model in missing_models))
            logger.info("All models pulled successfully")
            

    async def generate_response(self, prompt: str, model: str, think: bool = False, system: str = "") -> dict:
        try:
            await self.ensure_models(models_list=self.models_list)
            output = await self.client.generate(
                model=model,
                prompt=prompt,
                stream=False,
                think=think, 
                system=system
            )

            return GenerationResponse(
                response=output['response'],
                metrics=GenerationMetrics(
                    total_duration_s=output['total_duration'] / 1e9,
                    prompt_tokens=output['prompt_eval_count'],
                    output_tokens=output['eval_count'],
                )
            )

        except httpx.TimeoutException:
            raise GenerationTimeout

        except (ResponseError, RequestError, httpx.RemoteProtocolError):
            raise GenerationError

def get_engine(generation_timeout_s: int, models_list: list) -> OllamaEngine:
    return OllamaEngine(client=AsyncClient(timeout = generation_timeout_s), models_list=models_list)