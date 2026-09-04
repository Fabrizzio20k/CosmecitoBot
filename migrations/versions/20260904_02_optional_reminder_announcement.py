"""Allow standalone reminders without an announcement."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "reminders",
        "announcement_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    # No es posible restaurar NOT NULL preservando recordatorios independientes.
    op.execute("DELETE FROM reminders WHERE announcement_id IS NULL")
    op.alter_column(
        "reminders",
        "announcement_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
