from abc import ABC, abstractmethod


class BaseEngine(ABC):

    @abstractmethod
    async def ensure_models(self, models_list):
        pass

    @abstractmethod
    async def generate_response(self, prompt: str, model: str, think: bool = False, system: str = "") -> dict:
        pass

