"""convert usd amounts to pkr

Revision ID: 814ead7da786
Revises: aa0d16fa7d94
Create Date: 2026-08-07 22:54:15.007611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.constants import USD_TO_PKR


# revision identifiers, used by Alembic.
revision: str = '814ead7da786'
down_revision: Union[str, Sequence[str], None] = 'aa0d16fa7d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One-time data migration (no schema change): multiplies every
    existing Transaction.amount and Budget.monthly_limit by USD_TO_PKR,
    converting pre-existing USD-denominated rows into PKR. This is a
    data-only conversion of already-stored values - every amount entered
    going forward is already in PKR directly, so nothing else in the app
    applies this conversion at insert time, and this migration only ever
    needs to run once (Alembic's own revision tracking in alembic_version
    prevents `alembic upgrade head` from silently re-running - and
    therefore double-converting - this same revision).

    Logs a handful of real before/after rows so the conversion can be
    visually confirmed from the migration output itself, not just trusted.
    """
    connection = op.get_bind()

    print(f"\n--- Converting stored amounts from USD to PKR (rate: {USD_TO_PKR}) ---")

    before_tx = connection.execute(
        sa.text("SELECT id, merchant, amount FROM transactions ORDER BY id LIMIT 5")
    ).fetchall()
    before_budgets = connection.execute(
        sa.text("SELECT id, category_id, monthly_limit FROM budgets ORDER BY id LIMIT 5")
    ).fetchall()

    tx_result = connection.execute(
        sa.text("UPDATE transactions SET amount = amount * :rate"), {"rate": USD_TO_PKR}
    )
    budget_result = connection.execute(
        sa.text("UPDATE budgets SET monthly_limit = monthly_limit * :rate"), {"rate": USD_TO_PKR}
    )

    after_tx = connection.execute(
        sa.text("SELECT id, merchant, amount FROM transactions ORDER BY id LIMIT 5")
    ).fetchall()
    after_budgets = connection.execute(
        sa.text("SELECT id, category_id, monthly_limit FROM budgets ORDER BY id LIMIT 5")
    ).fetchall()

    print(f"Converted {tx_result.rowcount} transaction row(s) and {budget_result.rowcount} budget row(s).\n")

    print("Sample transactions (id, merchant, amount before -> after):")
    for b, a in zip(before_tx, after_tx):
        print(f"  id={b.id} merchant={b.merchant!r}: {b.amount} -> {a.amount}")

    print("Sample budgets (id, category_id, monthly_limit before -> after):")
    for b, a in zip(before_budgets, after_budgets):
        print(f"  id={b.id} category_id={b.category_id}: {b.monthly_limit} -> {a.monthly_limit}")


def downgrade() -> None:
    """Reverses the conversion by dividing back out USD_TO_PKR."""
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE transactions SET amount = amount / :rate"), {"rate": USD_TO_PKR})
    connection.execute(sa.text("UPDATE budgets SET monthly_limit = monthly_limit / :rate"), {"rate": USD_TO_PKR})
