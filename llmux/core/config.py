import json
from pathlib import Path
from typing import Protocol
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.enums import LLMEngine, AggregationStrategy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )

    database_url: str
    config_path: str
    ollama_host: str

settings = Settings()


class ModelsConfig(BaseModel):
    workers: list[str] = []
    aggregator: str = ""


class AppConfig(BaseModel):
    total_workers: int = Field(gt=0)
    llm_engine: LLMEngine
    models: ModelsConfig
    aggregation_strategy: AggregationStrategy
    aggregation_system_prompt: str = ""
    generation_timeout_s: int
    max_prompt_length_char: int
    max_concurrent_jobs: int = Field(gt=0)
    max_queued_jobs: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_worker_count(self) -> "AppConfig":
        if self.total_workers != len(self.models.workers):
            raise ValueError(
                "total_workers should be equal to the number of configured models"
            )

        return self


class ConfigProvider(Protocol):
    """Interface through which the application accesses configuration."""

    def get_config(self) -> AppConfig:
        ...


class JsonConfigProvider:
    """Loads project configuration from a JSON file."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = self.load()

    def get_config(self) -> AppConfig:
        return self.config

    def load(self) -> AppConfig:
        try:
            with self.config_path.open(mode="r",encoding="utf-8") as config_file:
                raw_config = json.load(config_file)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Configuration file not found: {self.config_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON configuration: {self.config_path}"
            ) from exc

        return AppConfig.model_validate(raw_config)


@lru_cache
def get_config_provider() -> ConfigProvider:
    config_provider = JsonConfigProvider(
        Path(settings.config_path)
    )
    return config_provider
