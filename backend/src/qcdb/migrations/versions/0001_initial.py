"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_suffix(".sql")


def upgrade() -> None:
    op.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS sample_run_summary")
    for table in (
        "audit_log",
        "species_abundance",
        "amr_hit",
        "qc_check",
        "metric_value",
        "tool_result",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE sample_run DROP CONSTRAINT IF EXISTS sample_run_current_fk")
    for table in (
        "result_version",
        "sample_run",
        "run_membership",
        "run",
        "source_document",
        "load_batch",
        "order_sample",
        "sample",
        "sample_field_definition",
        "sample_order",
        "owner",
        "metric_label",
        "metric_definition",
        "metric_dictionary_import",
        "user_session",
        "app_user",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
