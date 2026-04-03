"""add telegram_chat_id to financial_profiles

Revision ID: 56e1deed04bf
Revises: 6d331b0a5359
Create Date: 2026-04-02 22:53:40.736682

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56e1deed04bf'
down_revision: Union[str, None] = '6d331b0a5359'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('financial_profiles', sa.Column('telegram_chat_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('financial_profiles', 'telegram_chat_id')
