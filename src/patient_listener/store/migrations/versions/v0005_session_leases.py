"""Shared API/voice admission ownership."""
from alembic import op
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('CREATE TABLE IF NOT EXISTS session_leases (resource TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL)')


def downgrade():
    raise RuntimeError('Stop all workers before changing the shared admission schema')
