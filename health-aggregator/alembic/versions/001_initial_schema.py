"""initial schema

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
        "patients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), default=""),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("risk_factor", sa.Float(), default=0.0),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("patient_id"),
    )
    op.create_index("ix_patients_patient_id", "patients", ["patient_id"])

    op.create_table(
        "telemetry_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("metric_type", sa.String(32), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(16), default=""),
        sa.Column("vendor", sa.String(32), default=""),
        sa.Column("timestamp_utc", sa.DateTime(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_event_id"),
    )
    op.create_index("ix_telemetry_records_patient_id", "telemetry_records", ["patient_id"])
    op.create_index("ix_telemetry_records_event_id", "telemetry_records", ["event_id"])

    op.create_table(
        "clinical_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("conditions_json", sa.Text(), default="[]"),
        sa.Column("medications_json", sa.Text(), default="[]"),
        sa.Column("fhir_live", sa.Integer(), default=0),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_clinical_snapshots_patient_id", "clinical_snapshots", ["patient_id"])

    op.create_table(
        "prediction_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("prob_6h", sa.Float(), default=0.0),
        sa.Column("prob_24h", sa.Float(), default=0.0),
        sa.Column("prob_72h", sa.Float(), default=0.0),
        sa.Column("horizon_at_risk", sa.String(8), default=""),
        sa.Column("conformal_json", sa.Text(), default="{}"),
        sa.Column("modo", sa.String(64), default=""),
        sa.Column("predicted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_prediction_snapshots_patient_id", "prediction_snapshots", ["patient_id"])

    op.create_table(
        "aggregation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=True),
        sa.Column("sources_json", sa.Text(), default="[]"),
        sa.Column("telemetry_count", sa.Integer(), default=0),
        sa.Column("status", sa.String(32), default="pending"),
        sa.Column("detail_json", sa.Text(), default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_aggregation_runs_patient_id", "aggregation_runs", ["patient_id"])


def downgrade() -> None:
    op.drop_table("aggregation_runs")
    op.drop_table("prediction_snapshots")
    op.drop_table("clinical_snapshots")
    op.drop_table("telemetry_records")
    op.drop_table("patients")