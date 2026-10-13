"""Create idempotency_keys (spec 004, ADR 0007).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            user_id      uuid  NOT NULL REFERENCES users (id),
            key          uuid  NOT NULL,
            request_hash text  NOT NULL,
            response     jsonb NOT NULL,
            PRIMARY KEY (user_id, key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_keys")
