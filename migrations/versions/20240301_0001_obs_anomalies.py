"""Add obs_anomalies table for detected metric anomalies.

Revision ID: obs_anomalies_001
Revises:
Create Date: 2024-03-01 00:01:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "obs_anomalies_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create obs_anomalies and obs_alert_receivers tables."""
    # Anomaly detection records
    op.create_table(
        "obs_anomalies",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("algorithm", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_obs_anomalies_tenant_metric", "obs_anomalies", ["tenant_id", "metric_name"])
    op.create_index("ix_obs_anomalies_detected_at", "obs_anomalies", ["detected_at"])

    op.execute("ALTER TABLE obs_anomalies ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY obs_anomalies_tenant_isolation ON obs_anomalies "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # Alert receivers
    op.create_table(
        "obs_alert_receivers",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("receiver_type", sa.String(length=50), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_obs_receiver_tenant_name"),
    )
    op.execute("ALTER TABLE obs_alert_receivers ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY obs_alert_receivers_tenant_isolation ON obs_alert_receivers "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # SLO reports
    op.create_table(
        "obs_slo_reports",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("slo_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("slo_target", sa.Float(), nullable=False),
        sa.Column("actual_availability", sa.Float(), nullable=False),
        sa.Column("error_budget_consumed_pct", sa.Float(), nullable=False),
        sa.Column("compliance_status", sa.String(length=20), nullable=False),
        sa.Column("incident_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("s3_pdf_key", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE obs_slo_reports ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY obs_slo_reports_tenant_isolation ON obs_slo_reports "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )


def downgrade() -> None:
    """Drop observability gap tables."""
    for table in ("obs_slo_reports", "obs_alert_receivers", "obs_anomalies"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.drop_table(table)
