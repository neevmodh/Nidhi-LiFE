"""smart meters, meter readings, anomaly flags, outages, and DISCOM staff roles

Revision ID: a3c5e7b9d1f2
Revises: a9d3f5b7c1e2
Create Date: 2026-11-28 09:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c5e7b9d1f2"
down_revision: str | Sequence[str] | None = "a9d3f5b7c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = sa.Enum("citizen", "admin", "officer", "reviewer", "auditor", name="role")
NEW = sa.Enum(
    "citizen", "admin", "officer", "reviewer", "auditor", "discom_admin", "discom_engineer", "discom_auditor", name="role"
)
NEW_TABLES = ("meters", "meter_readings", "meter_events", "meter_flags", "outages")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in ("discom_admin", "discom_engineer", "discom_auditor"):
            op.execute(f"ALTER TYPE role ADD VALUE IF NOT EXISTS '{value}'")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("discom", sa.String(length=20), nullable=True))
        if bind.dialect.name != "postgresql":
            batch.alter_column("role", existing_type=OLD, type_=NEW, existing_nullable=False)

    op.create_table(
        "meters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("serial", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("discom", sa.String(length=20), nullable=False),
        sa.Column("feeder", sa.String(length=40), nullable=False),
        sa.Column("district_id", sa.Integer(), nullable=True),
        sa.Column("sanctioned_load_kw", sa.Float(), nullable=False),
        sa.Column("pv_kwp", sa.Float(), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["district_id"], ["districts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_meters_serial", "meters", ["serial"], unique=True)
    op.create_index("ix_meters_discom", "meters", ["discom"])
    op.create_index("ix_meters_feeder", "meters", ["feeder"])
    op.create_index("ix_meters_district_id", "meters", ["district_id"])

    op.create_table(
        "meter_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meter_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_kwh", sa.Float(), nullable=False),
        sa.Column("export_kwh", sa.Float(), nullable=False),
        sa.Column("load_kw", sa.Float(), nullable=False),
        sa.Column("pv_kw", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["meter_id"], ["meters.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meter_id", "ts"),
    )
    op.create_index("ix_meter_readings_meter_ts", "meter_readings", ["meter_id", "ts"])

    op.create_table(
        "meter_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meter_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delta_kw", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["meter_id"], ["meters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meter_events_meter_id", "meter_events", ["meter_id"])

    op.create_table(
        "meter_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meter_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["meter_id"], ["meters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meter_flags_meter_id", "meter_flags", ["meter_id"])
    op.create_index("ix_meter_flags_status", "meter_flags", ["status"])

    op.create_table(
        "outages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("discom", sa.String(length=20), nullable=False),
        sa.Column("feeder", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outages_discom", "outages", ["discom"])
    op.create_index("ix_outages_feeder", "outages", ["feeder"])

    if bind.dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("outages")
    op.drop_table("meter_flags")
    op.drop_table("meter_events")
    op.drop_table("meter_readings")
    op.drop_table("meters")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("discom")
