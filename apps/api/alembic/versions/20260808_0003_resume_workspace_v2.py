"""Add the persisted conversational resume workspace.

Revision ID: 20260808_0003
Revises: 20260807_0002
Create Date: 2026-08-08 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0003"
down_revision: str | None = "20260807_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_workspaces",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column(
            "language",
            sa.Enum("ar", "en", name="resume_workspace_language", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                "understanding",
                "writing",
                "review",
                "complete",
                name="resume_workspace_stage",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("evidence_revision", sa.Integer(), nullable=False),
        sa.Column("readiness_score", sa.Integer(), nullable=False),
        sa.Column("section_coverage", sa.JSON(), nullable=False),
        sa.Column("current_draft", sa.JSON(), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("contact", sa.JSON(), nullable=False),
        sa.Column("pending_understanding", sa.JSON(), nullable=True),
        sa.Column("pending_suggestion", sa.JSON(), nullable=True),
        sa.Column("consent_version", sa.String(length=40), nullable=True),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "draft_revision >= 0", name=op.f("ck_resume_workspaces_draft_revision_non_negative")
        ),
        sa.CheckConstraint(
            "evidence_revision >= 0",
            name=op.f("ck_resume_workspaces_evidence_revision_non_negative"),
        ),
        sa.CheckConstraint(
            "readiness_score >= 0 AND readiness_score <= 100",
            name=op.f("ck_resume_workspaces_readiness_range"),
        ),
        sa.CheckConstraint(
            "revision >= 0", name=op.f("ck_resume_workspaces_revision_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["career_profiles.id"],
            name=op.f("fk_resume_workspaces_profile_id_career_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_workspaces")),
    )
    with op.batch_alter_table("resume_workspaces", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_resume_workspaces_profile_id"), ["profile_id"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_resume_workspaces_stage"), ["stage"], unique=False)

    op.create_table(
        "resume_messages",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="resume_message_role", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "text",
                "question",
                "understanding",
                "suggestion",
                "status",
                name="resume_message_kind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "sent",
                "pending",
                "confirmed",
                "corrected",
                "dismissed",
                "failed",
                name="resume_message_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("client_turn_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence >= 1", name=op.f("ck_resume_messages_sequence_positive")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["resume_workspaces.id"],
            name=op.f("fk_resume_messages_workspace_id_resume_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_messages")),
        sa.UniqueConstraint(
            "workspace_id",
            "client_turn_id",
            name="uq_resume_messages_workspace_client_turn",
        ),
        sa.UniqueConstraint(
            "workspace_id", "sequence", name="uq_resume_messages_workspace_sequence"
        ),
    )
    with op.batch_alter_table("resume_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_resume_messages_status"), ["status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_resume_messages_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            "ix_resume_messages_workspace_status", ["workspace_id", "status"], unique=False
        )

    op.create_table(
        "resume_draft_versions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "reason",
            sa.Enum(
                "initial_generation",
                "manual_edit",
                "ai_rewrite",
                "restore",
                "review",
                name="resume_draft_version_reason",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "reviewed",
                "export_ready",
                name="resume_draft_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("evidence_revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_owner_id", sa.String(length=255), nullable=True),
        sa.Column("review_hash", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_revision >= 0",
            name=op.f("ck_resume_draft_versions_evidence_revision_non_negative"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_resume_draft_versions_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["resume_draft_versions.id"],
            name=op.f("fk_resume_draft_versions_base_version_id_resume_draft_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["resume_workspaces.id"],
            name=op.f("fk_resume_draft_versions_workspace_id_resume_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resume_draft_versions")),
        sa.UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_resume_draft_versions_workspace_version",
        ),
    )
    with op.batch_alter_table("resume_draft_versions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_resume_draft_versions_base_version_id"),
            ["base_version_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_resume_draft_versions_status"), ["status"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_resume_draft_versions_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            "ix_resume_draft_versions_workspace_status",
            ["workspace_id", "status"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("resume_draft_versions", schema=None) as batch_op:
        batch_op.drop_index("ix_resume_draft_versions_workspace_status")
        batch_op.drop_index(batch_op.f("ix_resume_draft_versions_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_resume_draft_versions_status"))
        batch_op.drop_index(batch_op.f("ix_resume_draft_versions_base_version_id"))
    op.drop_table("resume_draft_versions")

    with op.batch_alter_table("resume_messages", schema=None) as batch_op:
        batch_op.drop_index("ix_resume_messages_workspace_status")
        batch_op.drop_index(batch_op.f("ix_resume_messages_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_resume_messages_status"))
    op.drop_table("resume_messages")

    with op.batch_alter_table("resume_workspaces", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_resume_workspaces_stage"))
        batch_op.drop_index(batch_op.f("ix_resume_workspaces_profile_id"))
    op.drop_table("resume_workspaces")
