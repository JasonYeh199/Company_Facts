"""Initial Company Facts schema."""

from alembic import op
from company_facts import models  # noqa: F401
from company_facts.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        for remainder in range(16):
            op.execute(
                f"CREATE TABLE IF NOT EXISTS facts_p{remainder} PARTITION OF facts "
                f"FOR VALUES WITH (MODULUS 16, REMAINDER {remainder})"
            )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_companies_name_trgm "
            "ON companies USING gin (name gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_securities_ticker_trgm "
            "ON securities USING gin (ticker gin_trgm_ops)"
        )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
