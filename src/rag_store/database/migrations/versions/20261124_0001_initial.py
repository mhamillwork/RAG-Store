"""Initial RAG Store schema, row-level security, and grants.

Revision ID: 20261124_0001
Revises:
Create Date: 2026-11-24
"""

from alembic import op
from sqlalchemy import text

from rag_store.database.models import Base
from rag_store.database.rls import RLS_SQL

revision = "20261124_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    present = bind.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
    if not present:
        raise RuntimeError(
            "pgvector is not installed in this database. A database administrator must run "
            "CREATE EXTENSION vector before this migration. RAG Store does not modify unrelated "
            "PostgreSQL installations and does not assume the server image contains pgvector."
        )
    bind.execute(text("SET search_path TO ragstore, public"))
    Base.metadata.create_all(bind)
    bind.execute(text(RLS_SQL))


def downgrade() -> None:
    raise RuntimeError(
        "The initial schema is not dropped automatically. Take a backup and drop the ragstore "
        "schema explicitly if a full teardown is intended."
    )
