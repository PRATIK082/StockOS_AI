"""add autopilot run telemetry

Revision ID: f7d8e9a0b1c2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7d8e9a0b1c2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('autopilot_runs',
    sa.Column('user_id', sa.String(length=32), nullable=False),
    sa.Column('mission', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('summary_json', sa.Text(), nullable=True),
    sa.Column('report', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_autopilot_runs_user_id'), 'autopilot_runs', ['user_id'], unique=False)

    op.create_table('autopilot_run_nodes',
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('phase', sa.String(length=32), nullable=False),
    sa.Column('agent', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('evidence_json', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['autopilot_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_autopilot_run_nodes_run_id'), 'autopilot_run_nodes', ['run_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_autopilot_run_nodes_run_id'), table_name='autopilot_run_nodes')
    op.drop_table('autopilot_run_nodes')
    op.drop_index(op.f('ix_autopilot_runs_user_id'), table_name='autopilot_runs')
    op.drop_table('autopilot_runs')