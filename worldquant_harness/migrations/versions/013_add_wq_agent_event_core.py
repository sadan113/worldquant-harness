"""add canonical WQ agent events and projections

Revision ID: 013
Revises: 012
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wq_agent_events",
        sa.Column("event_id", sa.String(48), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(200), nullable=False),
        sa.Column("attempt_uid", sa.String(64), nullable=False),
        sa.Column("candidate_uid", sa.String(64), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("owner_key", sa.String(100), nullable=False, server_default="local"),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("account", sa.String(50), nullable=False, server_default="primary"),
        sa.Column("region", sa.String(10), nullable=False, server_default="USA"),
        sa.Column("universe", sa.String(20), nullable=False, server_default="TOP3000"),
        sa.Column("delay", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("alpha_id", sa.String(50), nullable=True),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_artifact", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    for name, columns in (
        ("ix_wq_agent_events_event_type", ["event_type"]),
        ("ix_wq_agent_events_run_id", ["run_id"]),
        ("ix_wq_agent_events_attempt_uid", ["attempt_uid"]),
        ("ix_wq_agent_events_candidate_uid", ["candidate_uid"]),
        ("ix_wq_agent_events_scope_key", ["scope_key"]),
        ("ix_wq_agent_events_owner_key", ["owner_key"]),
        ("ix_wq_agent_events_alpha_id", ["alpha_id"]),
        ("ix_wq_agent_events_scope_candidate", ["scope_key", "candidate_uid"]),
        ("ix_wq_agent_events_run_attempt", ["run_id", "attempt_uid"]),
    ):
        op.create_index(name, "wq_agent_events", columns)

    op.create_table(
        "wq_candidate_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("owner_key", sa.String(100), nullable=False, server_default="local"),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("account", sa.String(50), nullable=False, server_default="primary"),
        sa.Column("region", sa.String(10), nullable=False, server_default="USA"),
        sa.Column("universe", sa.String(20), nullable=False, server_default="TOP3000"),
        sa.Column("delay", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("candidate_uid", sa.String(64), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("expression_normalized", sa.Text(), nullable=False),
        sa.Column("expression_hash", sa.String(64), nullable=False),
        sa.Column("settings_hash", sa.String(64), nullable=False),
        sa.Column("effective_settings", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(200), nullable=False),
        sa.Column("attempt_uid", sa.String(64), nullable=False),
        sa.Column("alpha_id", sa.String(50), nullable=True),
        sa.Column("lifecycle_status", sa.String(50), nullable=False, server_default="candidate"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("correlation", sa.JSON(), nullable=False),
        sa.Column("failure", sa.JSON(), nullable=False),
        sa.Column("source_meta", sa.JSON(), nullable=False),
        sa.Column("latest_event_id", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("uq_wq_candidate_states_scope_uid", "wq_candidate_states", ["scope_key", "candidate_uid"], unique=True)
    op.create_index("ix_wq_candidate_states_scope_status", "wq_candidate_states", ["scope_key", "lifecycle_status"])
    for column in ("scope_key", "owner_key", "candidate_uid", "expression_hash", "settings_hash", "run_id", "attempt_uid", "alpha_id", "lifecycle_status"):
        op.create_index(f"ix_wq_candidate_states_{column}", "wq_candidate_states", [column])

    op.create_table(
        "wq_memory_items",
        sa.Column("memory_id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("owner_key", sa.String(100), nullable=False, server_default="local"),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("account", sa.String(50), nullable=False, server_default="primary"),
        sa.Column("region", sa.String(10), nullable=False, server_default="USA"),
        sa.Column("universe", sa.String(20), nullable=False, server_default="TOP3000"),
        sa.Column("delay", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("memory_key", sa.String(200), nullable=False),
        sa.Column("memory_kind", sa.String(50), nullable=False),
        sa.Column("subject_key", sa.String(200), nullable=False),
        sa.Column("candidate_uid", sa.String(64), nullable=True),
        sa.Column("failure_kind", sa.String(50), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="note"),
        sa.Column("evidence_class", sa.String(40), nullable=False),
        sa.Column("polarity", sa.String(20), nullable=False, server_default="negative"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("support_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("contradiction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(20), nullable=False, server_default="active"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evidence_event_ids", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("uq_wq_memory_items_scope_key", "wq_memory_items", ["scope_key", "memory_key"], unique=True)
    op.create_index("ix_wq_memory_items_scope_kind", "wq_memory_items", ["scope_key", "memory_kind", "state"])
    for column in ("scope_key", "owner_key", "memory_kind", "subject_key", "candidate_uid", "failure_kind", "evidence_class", "state"):
        op.create_index(f"ix_wq_memory_items_{column}", "wq_memory_items", [column])


def downgrade() -> None:
    op.drop_table("wq_memory_items")
    op.drop_table("wq_candidate_states")
    op.drop_table("wq_agent_events")
