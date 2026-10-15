"""Initial control-plane schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "owner_device",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "call_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_ref", sa.String(100), unique=True, nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("private", sa.Text(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "call_event",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("call_id", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_call_event_call_id", "call_event", ["call_id"])
    op.create_table(
        "budget_period",
        sa.Column("period", sa.String(7), primary_key=True),
        *[
            sa.Column(n, sa.Integer(), nullable=False)
            for n in ["limit", "confirmed", "estimated", "reserved"]
        ],
    )
    op.create_table(
        "owner_intent",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
    )
    op.create_table(
        "owner_policy",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("data", sa.Text(), nullable=False),
    )
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("call_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_notification_outbox_call_id", "notification_outbox", ["call_id"])
    # Content is intentionally not encrypted: this row is only a concurrency mutex.
    op.execute("INSERT INTO owner_policy (id, data) VALUES ('budget_lock', '')")


def downgrade():
    for name in [
        "notification_outbox",
        "owner_policy",
        "owner_intent",
        "budget_period",
        "call_event",
        "call_session",
        "owner_device",
    ]:
        op.drop_table(name)
