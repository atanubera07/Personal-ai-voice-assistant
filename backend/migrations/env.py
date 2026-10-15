from alembic import context
from app.config import Settings
from app.db import Base, Database

config = context.config
engine = Database(Settings.from_env()).engine
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
