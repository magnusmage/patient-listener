"""Persistent deletion confirmation and anti-reseeding receipts."""
from alembic import op
revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS privacy_challenges (
    token_hash TEXT PRIMARY KEY, person_id TEXT NOT NULL, actor_id TEXT NOT NULL,
    expires_at TEXT NOT NULL
)""")
    op.execute("""CREATE TABLE IF NOT EXISTS deleted_people (
    person_key TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL UNIQUE, actor_hash TEXT NOT NULL,
    deleted_at TEXT NOT NULL, consent_person_id TEXT,
    consent_delete_after TEXT NOT NULL, consent_purged_at TEXT
)""")



def downgrade():
    raise RuntimeError('Privacy receipts must not be dropped; restore a verified backup')
