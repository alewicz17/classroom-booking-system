"""Create rooms, users and bookings, and seed rooms and users.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        CREATE TABLE rooms (
            id uuid PRIMARY KEY,
            name text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE users (
            id uuid PRIMARY KEY,
            name text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE bookings (
            id uuid PRIMARY KEY,
            room_id uuid NOT NULL REFERENCES rooms (id),
            user_id uuid NOT NULL REFERENCES users (id),
            period tstzrange NOT NULL CHECK (NOT isempty(period)),
            status text NOT NULL CHECK (status IN ('confirmed', 'cancelled'))
        )
        """
    )
    # ADR 0004: the database, not the service pre-check, guarantees no overlaps.
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT no_overlap
            EXCLUDE USING gist (room_id WITH =, period WITH &&)
            WHERE (status = 'confirmed')
        """
    )
    op.execute(
        """
        INSERT INTO rooms (id, name) VALUES
            ('10000000-0000-4000-8000-000000000001', 'Room 1'),
            ('10000000-0000-4000-8000-000000000002', 'Room 2')
        """
    )
    op.execute(
        """
        INSERT INTO users (id, name) VALUES
            ('20000000-0000-4000-8000-00000000000a', 'User A'),
            ('20000000-0000-4000-8000-00000000000b', 'User B')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE bookings")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE rooms")
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
