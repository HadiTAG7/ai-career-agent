"""Add persisted career-path conversations.

Revision ID: 20260807_0002
Revises: 20260806_0001
Create Date: 2026-08-07 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_0002"
down_revision: str | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "career_path_conversations",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_evidence_revision", sa.Integer(), nullable=True),
        sa.Column("consent_version", sa.String(length=40), nullable=True),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["career_profiles.id"],
            name=op.f("fk_career_path_conversations_profile_id_career_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_path_conversations")),
    )
    with op.batch_alter_table("career_path_conversations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_career_path_conversations_profile_id"),
            ["profile_id"],
            unique=True,
        )

    op.create_table(
        "career_path_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="career_path_message_role", native_enum=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("suggestions", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("evidence_revision", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["career_path_conversations.id"],
            name=op.f(
                "fk_career_path_messages_conversation_id_career_path_conversations"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_path_messages")),
        sa.UniqueConstraint(
            "conversation_id",
            "client_turn_id",
            name="uq_career_path_messages_conversation_client_turn",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_career_path_messages_conversation_sequence",
        ),
    )
    with op.batch_alter_table("career_path_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_career_path_messages_conversation_id"),
            ["conversation_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("career_path_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_career_path_messages_conversation_id"))
    op.drop_table("career_path_messages")

    with op.batch_alter_table("career_path_conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_career_path_conversations_profile_id"))
    op.drop_table("career_path_conversations")
