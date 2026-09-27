"""Keep the current username unambiguous during assignee lookup.

Revision ID: 0002_unique_usernames
Revises: 0001_initial
"""

from alembic import op

revision = "0002_unique_usernames"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing duplicate names cannot identify a safe owner.  Require another
    # interaction from those people before their names may be used for tasks.
    op.execute(
        """
        UPDATE users SET username = NULL
        WHERE id IN (
            SELECT id FROM (
                SELECT id, count(*) OVER (PARTITION BY lower(username)) AS holders
                FROM users WHERE username IS NOT NULL
            ) duplicate_names
            WHERE holders > 1
        )
        """
    )
    # 0001 uses the current model metadata for fresh databases, so the index
    # may already be present when this revision runs.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_ci ON users (lower(username))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_username_ci")
