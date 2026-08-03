import calendar
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from ..mcp_server import get_budget, get_monthly_summary
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"


def _forecast_line(forecast: dict) -> str:
    line = (
        f"- {forecast['category']}: spent ${forecast['spent_so_far']:.2f} so far, "
        f"projected to reach ${forecast['projected_total']:.2f} by month end"
    )
    if forecast["budget_limit"] is not None:
        line += f" (budget: ${forecast['budget_limit']:.2f})"
    if forecast["on_track_to_overspend"]:
        over_by = forecast["projected_total"] - forecast["budget_limit"]
        line += f" - ON TRACK TO OVERSPEND by ${over_by:.2f}"
    return line


async def _summarize(forecasts: list[dict]) -> str:
    """Ask claude-haiku-4-5 to phrase the pre-computed forecast as prose.

    The model only summarizes numbers that have already been calculated in
    Python; it does no math of its own.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    prompt = (
        "Here is a pre-computed monthly spending forecast, one line per "
        "category. Write a short, human-readable summary (2-4 sentences) "
        "of this forecast for the user. Only phrase and summarize the "
        "numbers given below - do not recalculate, estimate, or introduce "
        "any number that isn't already present.\n\n"
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
    month (linear extrapolation, computed in Python), compares each
    projection against that category's budget via the MCP get_budget tool,
    and asks claude-haiku-4-5 to phrase the results as a short summary -
    the model never does the math itself.
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
        if row["category_id"] is not None:
            budget = await get_budget(owner_id=owner_id, category_id=row["category_id"])
            if budget is not None:
                budget_limit = budget["monthly_limit"]

        on_track_to_overspend = budget_limit is not None and projected_total > budget_limit

        forecasts.append(
            {
                "category": row["category_name"] or "uncategorized",
                "spent_so_far": spent_so_far,
                "projected_total": projected_total,
                "budget_limit": budget_limit,
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
