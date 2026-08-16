from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, Integer, String, Text, UUID, JSON, Enum, Float
from sqlalchemy.orm import Mapped, mapped_column

from common.enums import JobStatus, LLMEngine, AggregationStrategy
from common.models import FailureDetails
from persistence.database import Base



class IngressLog(Base):
    __tablename__ = "ingress_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), index=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    method: Mapped[str] = mapped_column(String(10))
    route: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_status: Mapped[int] = mapped_column(Integer)
    request_body_bytes: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class JobRecord(Base):
    __tablename__ = "job_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    request_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), index=True, unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    job_status: Mapped[JobStatus] = mapped_column(Enum(JobStatus))
    llm_engine: Mapped[LLMEngine | None] = mapped_column(Enum(LLMEngine))
    worker_models: Mapped[list[str] | None] = mapped_column(JSON)
    worker_model_outputs: Mapped[list[dict] | None] = mapped_column(JSON)
    aggregation_strategy: Mapped[AggregationStrategy | None] = mapped_column(Enum(AggregationStrategy))
    aggregation_model: Mapped[str | None] = mapped_column(Text)
    aggregation_output: Mapped[dict | None] = mapped_column(JSON)
    failure: Mapped[dict | None] = mapped_column(JSON)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    request_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), index=True, unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)

