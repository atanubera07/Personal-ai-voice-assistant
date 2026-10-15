"""App-owned recording lifecycle metadata."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "recording",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("expiry_at", sa.String(40), nullable=True),
        sa.Column("receipt", sa.String(200), nullable=True),
    )
    op.create_index("ix_recording_call_id", "recording", ["call_id"])
    op.create_index("ix_recording_expiry_at", "recording", ["expiry_at"])


def downgrade():
    op.drop_table("recording")
