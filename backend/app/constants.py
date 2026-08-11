# FinSight AI stores and displays every monetary amount in Pakistani
# Rupees (PKR) - USD_TO_PKR is only used by the one-time data migration
# that converted pre-existing USD-denominated Transaction.amount and
# Budget.monthly_limit rows (see
# alembic/versions/814ead7da786_convert_usd_amounts_to_pkr.py). It is NOT
# applied at insert time - every amount entered going forward is already
# in PKR directly, so there is no ongoing conversion logic anywhere else
# in the app.
USD_TO_PKR = 280
