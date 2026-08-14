"""Cascade career_facts.source_id when its evidence source is deleted.

A bare profile delete on PostgreSQL cascades into evidence_sources; the previous RESTRICT
on career_facts.source_id made that cascade fail. Facts now die with their source.

Revision ID: 20260814_0004
Revises: 20260808_0003
Create Date: 2026-08-14 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0004"
down_revision: str | None = "20260808_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("career_facts", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_career_facts_source_id_evidence_sources"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_career_facts_source_id_evidence_sources"),
            "evidence_sources",
            ["source_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("career_facts", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_career_facts_source_id_evidence_sources"),
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_career_facts_source_id_evidence_sources"),
            "evidence_sources",
            ["source_id"],
            ["id"],
            ondelete="RESTRICT",
        )
