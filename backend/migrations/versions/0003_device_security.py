"""Device proof, one-use enrollment, replay protection and shared throttling."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column("owner_device", sa.Column("public_key", sa.Text(), nullable=True))
    op.add_column(
        "owner_device", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_table(
        "device_pairing",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("expires", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "device_challenge",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("nonce", sa.String(100), nullable=False),
        sa.Column("expires", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_device_challenge_device_id", "device_challenge", ["device_id"])
    op.create_index("ix_device_challenge_expires", "device_challenge", ["expires"])
    op.create_table(
        "request_nonce",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("expires", sa.Integer(), nullable=False),
    )
    op.create_index("ix_request_nonce_expires", "request_nonce", ["expires"])
    op.create_table(
        "rate_bucket",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("window", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade():
    for name in ("rate_bucket", "request_nonce", "device_challenge", "device_pairing"):
        op.drop_table(name)
    op.drop_column("owner_device", "session_version")
    op.drop_column("owner_device", "public_key")
