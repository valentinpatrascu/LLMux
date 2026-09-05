"""initial schema

Revision ID: 6a04dc130819
Revises: 
Create Date: 2026-09-05 16:43:35.818043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6a04dc130819"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


job_status_enum = sa.Enum(
    "SUBMITTED",
    "PROCESSING",
    "PARTIAL",
    "AGGREGATING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    name="jobstatus",
)
llm_engine_enum = sa.Enum("OLLAMA", name="llmengine")
aggregation_strategy_enum = sa.Enum("JUDGE", name="aggregationstrategy")


def upgrade() -> None:
    """Create the complete initial schema."""
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_request_id"),
        "conversations",
        ["request_id"],
        unique=True,
    )

    op.create_table(
        "ingress_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("request_body_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingress_logs_request_id"),
        "ingress_logs",
        ["request_id"],
        unique=True,
    )

    op.create_table(
        "job_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("job_status", job_status_enum, nullable=False),
        sa.Column("llm_engine", llm_engine_enum, nullable=True),
        sa.Column("worker_models", sa.JSON(), nullable=True),
        sa.Column("worker_model_outputs", sa.JSON(), nullable=True),
        sa.Column(
            "aggregation_strategy",
            aggregation_strategy_enum,
            nullable=True,
        ),
        sa.Column("aggregation_model", sa.Text(), nullable=True),
        sa.Column("aggregation_output", sa.JSON(), nullable=True),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_job_records_request_id"),
        "job_records",
        ["request_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove the complete initial schema."""
    op.drop_index(op.f("ix_job_records_request_id"), table_name="job_records")
    op.drop_table("job_records")
    op.drop_index(op.f("ix_ingress_logs_request_id"), table_name="ingress_logs")
    op.drop_table("ingress_logs")
    op.drop_index(
        op.f("ix_conversations_request_id"),
        table_name="conversations",
    )
    op.drop_table("conversations")

    aggregation_strategy_enum.drop(op.get_bind(), checkfirst=True)
    llm_engine_enum.drop(op.get_bind(), checkfirst=True)
    job_status_enum.drop(op.get_bind(), checkfirst=True)
