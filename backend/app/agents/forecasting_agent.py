import asyncio
import calendar
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from ..mcp_server import get_all_budgets, get_budget, get_historical_monthly_average, get_monthly_summary
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
        f"- {forecast['category']}: spent Rs. {forecast['spent_so_far']:.2f} so far, "
        f"projected to reach Rs. {forecast['projected_total']:.2f} by month end"
    )

    comparison_type = forecast["comparison_type"]
    if comparison_type == "budget":
        line += f" (compared against your budget of Rs. {forecast['budget_limit']:.2f})"
    elif comparison_type == "historical_average":
        line += (
            " (no budget set for this category, so compared against your "
            f"historical average of Rs. {forecast['historical_average']:.2f}/month)"
        )
    else:
        line += " (no budget set and not enough history yet to compare against)"

    if forecast["on_track_to_overspend"]:
        baseline = forecast["budget_limit"] if comparison_type == "budget" else forecast["historical_average"]
        over_by = forecast["projected_total"] - baseline
        verb = "OVER BUDGET" if comparison_type == "budget" else "ABOVE YOUR TYPICAL SPENDING"
        line += f" - ON TRACK TO BE {verb} by Rs. {over_by:.2f}"

    return line


def _fallback_summary(forecasts: list[dict]) -> str:
    """A deterministic, no-LLM-required summary used when _summarize's API
    call fails (network error, rate limit, missing key) - the numbers in
    `forecasts` were already fully computed in Python before the LLM call,
    so a summary being unavailable shouldn't take the whole forecast down
    with it. Not as polished as the real summary, but still says whether
    anything needs attention rather than a bare "something went wrong."
    """
    over_budget = [f["category"] for f in forecasts if f["on_track_to_overspend"]]
    if not over_budget:
        return (
            "Your spending forecast has been calculated below - you're on track in every "
            "category with a baseline to compare against. (A written summary couldn't be "
            "generated right now.)"
        )

    categories = ", ".join(over_budget)
    return (
        f"Your spending forecast has been calculated below - {len(over_budget)} "
        f"categor{'y is' if len(over_budget) == 1 else 'ies are'} projected to go over "
        f"budget or typical spending: {categories}. (A written summary couldn't be "
        "generated right now.)"
    )


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
        "already present. All amounts are in Pakistani Rupees - use the "
        "same \"Rs. \" notation shown below, never \"$\".\n\n"
        + "\n".join(_forecast_line(f) for f in forecasts)
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

    The category list is the union of get_monthly_summary (categories with
    at least one transaction this month) and get_all_budgets (every
    budgeted category, regardless of spending) - get_monthly_summary alone
    would silently omit a category the user just set a budget for but
    hasn't spent in yet this month, even though it has a real budget worth
    showing progress against (spent_so_far=0, never flagged as over
    budget).
    """
    today = date.today()
    days_elapsed = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    summary_rows = await get_monthly_summary(owner_id=owner_id, month=today.month, year=today.year)

    all_budgets = await get_all_budgets(owner_id=owner_id)
    spent_category_ids = {row["category_id"] for row in summary_rows}
    summary_rows = summary_rows + [
        {"category_id": b["category_id"], "category_name": b["category_name"], "total_spent": 0.0}
        for b in all_budgets
        if b["category_id"] not in spent_category_ids
    ]

    # Each category's budget/historical-average lookup is an independent DB
    # round trip with no dependency on any other category, so run them
    # concurrently rather than one at a time - awaiting them sequentially
    # just adds up per-call network latency for no benefit. Budgets are
    # looked up first for every category at once; historical averages are
    # then looked up, also all at once, only for the categories that came
    # back with no budget.
    async def _lookup_budget(category_id: int | None) -> dict | None:
        if category_id is None:
            return None
        return await get_budget(owner_id=owner_id, category_id=category_id)

    budgets = await asyncio.gather(*(_lookup_budget(row["category_id"]) for row in summary_rows))

    async def _lookup_historical(category_id: int) -> dict | None:
        return await get_historical_monthly_average(
            owner_id=owner_id,
            category_id=category_id,
            exclude_month=today.month,
            exclude_year=today.year,
        )

    need_historical = [
        i
        for i, (row, budget) in enumerate(zip(summary_rows, budgets))
        if row["category_id"] is not None and budget is None
    ]
    historical_results = await asyncio.gather(
        *(_lookup_historical(summary_rows[i]["category_id"]) for i in need_historical)
    )
    historical_by_index = dict(zip(need_historical, historical_results))

    forecasts = []
    for i, row in enumerate(summary_rows):
        spent_so_far = row["total_spent"]
        projected_total = (spent_so_far / days_elapsed) * days_in_month

        budget_limit = None
        historical_average = None
        comparison_type = "no_data"
        baseline = None

        budget = budgets[i]
        if budget is not None:
            budget_limit = budget["monthly_limit"]
            comparison_type = "budget"
            baseline = budget_limit
        else:
            historical = historical_by_index.get(i)
            if historical is not None and historical["months_counted"] >= MIN_HISTORY_MONTHS:
                historical_average = historical["average_monthly_spend"]
                comparison_type = "historical_average"
                baseline = historical_average

        on_track_to_overspend = baseline is not None and projected_total > baseline

        forecasts.append(
            {
                "category": row["category_name"] or "uncategorized",
                "category_id": row["category_id"],
                "spent_so_far": spent_so_far,
                "projected_total": projected_total,
                "budget_limit": budget_limit,
                "historical_average": historical_average,
                "comparison_type": comparison_type,
                "on_track_to_overspend": on_track_to_overspend,
            }
        )

    summary_model = None
    if not forecasts:
        summary = "No spending recorded yet this month."
    else:
        try:
            summary = await _summarize(forecasts)
            summary_model = MODEL
        except (httpx.HTTPError, RuntimeError):
            # The numbers above are already fully computed - don't let a
            # network error or rate limit on the summary call take the
            # whole forecast down with it. summary_model stays None here:
            # the fallback sentence is deterministic Python, not something
            # any model actually produced.
            summary = _fallback_summary(forecasts)

    result = {"forecasts": forecasts, "summary": summary, "summary_model": summary_model}

    await save_trace(
        owner_id,
        "Generate forecast",
        "forecasting",
        [{"agent": "forecasting_agent", "action": "generate_forecast", "result": result}],
    )

    return result
