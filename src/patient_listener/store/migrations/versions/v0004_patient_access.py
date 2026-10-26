"""Patient device enrollment, separate from session token signing."""
from alembic import op
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('CREATE TABLE IF NOT EXISTS patient_invites (\n    code_hash TEXT PRIMARY KEY, person_id TEXT NOT NULL,\n    actor_id TEXT NOT NULL, expires_at TEXT NOT NULL\n)')
    op.execute('CREATE TABLE IF NOT EXISTS patient_devices (\n    authorization_id TEXT PRIMARY KEY, person_id TEXT NOT NULL,\n    device_hash TEXT NOT NULL, secret_hash TEXT NOT NULL UNIQUE,\n    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,\n    UNIQUE (person_id, device_hash)\n)')


def downgrade():
    raise RuntimeError('Device enrollment must not be silently discarded; restore a verified backup')
