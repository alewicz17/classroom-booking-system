"""Add bookings.reminder_sent_at (spec 005, ADR 0003).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bookings ADD COLUMN reminder_sent_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP COLUMN reminder_sent_at")
