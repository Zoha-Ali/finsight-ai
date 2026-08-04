import calendar
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from ..mcp_server import get_budget, get_historical_monthly_average, get_monthly_summary
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

# Minimum prior months of spending in a category required before its
# historical average is used as a forecast baseline. Set to 1 rather than
# something higher so the fallback is actually useful early in a user's
# history, not just once they already have months of data - the point is
# to give a comparison where none existed before, not to be maximally
# statistically rigorous.
MIN_HISTORY_MONTHS = 1


def _forecast_line(forecast: dict) -> str:
    line = (
        f"- {forecast['category']}: spent ${forecast['spent_so_far']:.2f} so far, "
        f"projected to reach ${forecast['projected_total']:.2f} by month end"
    )

    comparison_type = forecast["comparison_type"]
    if comparison_type == "budget":
        line += f" (compared against your budget of ${forecast['budget_limit']:.2f})"
    elif comparison_type == "historical_average":
        line += (
            " (no budget set for this category, so compared against your "
            f"historical average of ${forecast['historical_average']:.2f}/month)"
        )
    else:
        line += " (no budget set and not enough history yet to compare against)"

    if forecast["on_track_to_overspend"]:
        baseline = forecast["budget_limit"] if comparison_type == "budget" else forecast["historical_average"]
        over_by = forecast["projected_total"] - baseline
        verb = "OVER BUDGET" if comparison_type == "budget" else "ABOVE YOUR TYPICAL SPENDING"
        line += f" - ON TRACK TO BE {verb} by ${over_by:.2f}"

    return line


async def _summarize(forecasts: list[dict]) -> str:
    """Ask claude-haiku-4-5 to phrase the pre-computed forecast as prose.

    The model only summarizes numbers that have already been calculated in
    Python; it does no math of its own. Each line tells it which
    comparison method (budget vs. historical average vs. none) applies to
    that category, so the summary can be transparent about it too.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    prompt = (
        "Here is a pre-computed monthly spending forecast, one line per "
        "category. Each line also states what it was compared against - a "
        "real budget, a historical average (when no budget is set), or "
        "neither. Write a short, human-readable summary (2-4 sentences) of "
        "this forecast for the user, and be clear about which comparison "
        "method applies where it matters (e.g. say \"based on your usual "
        "spending\" rather than implying something is a budget when it "
        "isn't). Only phrase and summarize the numbers given below - do "
        "not recalculate, estimate, or introduce any number that isn't "
        "already present.\n\n" + "\n".join(_forecast_line(f) for f in forecasts)
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

    return "".join(block["text"] for block in data["content"] if block.get("type") == "text").strip()


async def generate_forecast(owner_id: int) -> dict:
    """Project each spending category to month-end and flag overspend risk.

    Projects month-end spend per category from the user's pace so far this
    month (linear extrapolation, computed in Python). Each category is
    compared against a baseline: a real budget if one is set
    (comparison_type="budget"); otherwise the user's own historical
    average monthly spend in that category, excluding the current
    in-progress month (comparison_type="historical_average"); otherwise no
    comparison is possible (comparison_type="no_data"). on_track_to_overspend
    is flagged against whichever baseline applies. claude-haiku-4-5 then
    phrases the results as a short summary - the model never does the math
    itself.
    """
    today = date.today()
    days_elapsed = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    summary_rows = await get_monthly_summary(owner_id=owner_id, month=today.month, year=today.year)

    forecasts = []
    for row in summary_rows:
        spent_so_far = row["total_spent"]
        projected_total = (spent_so_far / days_elapsed) * days_in_month

        budget_limit = None
        historical_average = None
        comparison_type = "no_data"
        baseline = None

        if row["category_id"] is not None:
            budget = await get_budget(owner_id=owner_id, category_id=row["category_id"])
            if budget is not None:
                budget_limit = budget["monthly_limit"]
                comparison_type = "budget"
                baseline = budget_limit
            else:
                historical = await get_historical_monthly_average(
                    owner_id=owner_id,
                    category_id=row["category_id"],
                    exclude_month=today.month,
                    exclude_year=today.year,
                )
                if historical is not None and historical["months_counted"] >= MIN_HISTORY_MONTHS:
                    historical_average = historical["average_monthly_spend"]
                    comparison_type = "historical_average"
                    baseline = historical_average

        on_track_to_overspend = baseline is not None and projected_total > baseline

        forecasts.append(
            {
                "category": row["category_name"] or "uncategorized",
                "spent_so_far": spent_so_far,
                "projected_total": projected_total,
                "budget_limit": budget_limit,
                "historical_average": historical_average,
                "comparison_type": comparison_type,
                "on_track_to_overspend": on_track_to_overspend,
            }
        )

    summary = await _summarize(forecasts) if forecasts else "No spending recorded yet this month."

    result = {"forecasts": forecasts, "summary": summary}

    await save_trace(
        owner_id,
        "Generate forecast",
        "forecasting",
        [{"agent": "forecasting_agent", "action": "generate_forecast", "result": result}],
    )

    return result
