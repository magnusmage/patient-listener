"""Distinguish old clips from processed hint audio without deleting cached data."""
from alembic import op
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("ALTER TABLE hint_audio ADD COLUMN profile TEXT NOT NULL DEFAULT 'legacy'")


def downgrade():
    raise RuntimeError('Restore a verified backup rather than dropping cache metadata')
