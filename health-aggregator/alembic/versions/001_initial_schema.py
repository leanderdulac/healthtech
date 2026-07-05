"""health_records schema

Revision ID: 001
Revises:
Create Date: 2026-07-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", sa.String(), unique=True, nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("steps", sa.Integer(), default=0),
        sa.Column("heart_rate_bpm", sa.Float(), nullable=True),
        sa.Column("hrv", sa.Float(), nullable=True),
        sa.Column("spo2", sa.Float(), nullable=True),
        sa.Column("calories_burned", sa.Float(), default=0),
        sa.Column("sleep_duration_min", sa.Integer(), default=0),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("body_fat", sa.Float(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
    )
    op.create_index("ix_health_records_id", "health_records", ["id"])
    op.create_index("ix_health_records_user_id", "health_records", ["user_id"])
    op.create_index("ix_health_records_source", "health_records", ["source"])
    op.create_index("ix_health_records_date", "health_records", ["date"])

    op.create_table(
        "aggregation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("sources_json", sa.Text(), default="[]"),
        sa.Column("records_count", sa.Integer(), default=0),
        sa.Column("status", sa.String(32), default="pending"),
        sa.Column("detail_json", sa.Text(), default="{}"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_aggregation_runs_user_id", "aggregation_runs", ["user_id"])


def downgrade() -> None:
    op.drop_table("aggregation_runs")
    op.drop_table("health_records")