"""Add Tiingo EOD price analysis tables."""

from alembic import op
from company_facts import models  # noqa: F401
from company_facts.db import Base

revision = "0002_price_analysis"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


PRICE_TABLES = (
    "price_instruments",
    "daily_prices",
    "daily_price_indicators",
    "price_ranks",
    "price_sync_items",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in PRICE_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(PRICE_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
