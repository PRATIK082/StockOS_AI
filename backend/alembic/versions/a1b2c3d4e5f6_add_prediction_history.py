"""add prediction_history

Revision ID: a1b2c3d4e5f6
Revises: e26dadc3a029
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e26dadc3a029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('prediction_history',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=64), nullable=False),
    sa.Column('timeframe', sa.String(length=16), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_prediction_history_user_id'), 'prediction_history', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_prediction_history_user_id'), table_name='prediction_history')
    op.drop_table('prediction_history')
