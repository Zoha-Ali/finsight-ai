from datetime import date as real_date
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents import forecasting_agent


class _FixedDate:
    """Stands in for the `date` name imported into forecasting_agent, so
    `date.today()` returns a fixed value - everything else about the
    projection formula (days_elapsed, days_in_month) derives from that.
    """

    def __init__(self, fixed: real_date):
        self._fixed = fixed

    def today(self):
        return self._fixed


@pytest.fixture(autouse=True)
def no_real_calls(monkeypatch):
    """generate_forecast() writes a Trace row via save_trace() as a side
    effect unrelated to the math being tested here - mock it out so these
    tests never touch a real DB session.
    """
    monkeypatch.setattr(forecasting_agent, "save_trace", AsyncMock(return_value=None))


def _set_today(monkeypatch, year: int, month: int, day: int) -> real_date:
    fixed = real_date(year, month, day)
    monkeypatch.setattr(forecasting_agent, "date", _FixedDate(fixed))
    return fixed


async def test_projection_formula_with_a_budget_baseline(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)  # day 5 of a 31-day month

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 1, "category_name": "food", "total_spent": 20.0}]),
    )
    monkeypatch.setattr(
        forecasting_agent, "get_budget", AsyncMock(return_value={"monthly_limit": 100.0, "category_id": 1})
    )
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    forecast = result["forecasts"][0]
    # (20 / 5) * 31 = 124.0, exactly
    assert forecast["spent_so_far"] == 20.0
    assert forecast["projected_total"] == pytest.approx(124.0)
    assert forecast["comparison_type"] == "budget"
    assert forecast["budget_limit"] == 100.0
    assert forecast["historical_average"] is None
    assert forecast["on_track_to_overspend"] is True  # 124 > 100
    forecasting_agent.get_historical_monthly_average.assert_not_awaited()  # budget short-circuits the fallback


async def test_projection_formula_falls_back_to_historical_average_when_no_budget(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)  # day 5 of a 31-day month

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 2, "category_name": "shopping", "total_spent": 50.0}]),
    )
    monkeypatch.setattr(forecasting_agent, "get_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(
        forecasting_agent,
        "get_historical_monthly_average",
        AsyncMock(return_value={"average_monthly_spend": 150.0, "months_counted": 2}),
    )
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    forecast = result["forecasts"][0]
    # (50 / 5) * 31 = 310.0, exactly
    assert forecast["projected_total"] == pytest.approx(310.0)
    assert forecast["comparison_type"] == "historical_average"
    assert forecast["budget_limit"] is None
    assert forecast["historical_average"] == 150.0
    assert forecast["on_track_to_overspend"] is True  # 310 > 150


async def test_projection_formula_with_no_budget_and_no_history(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 10)  # day 10 of a 31-day month

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 3, "category_name": "transport", "total_spent": 30.0}]),
    )
    monkeypatch.setattr(forecasting_agent, "get_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    forecast = result["forecasts"][0]
    # (30 / 10) * 31 = 93.0, exactly
    assert forecast["projected_total"] == pytest.approx(93.0)
    assert forecast["comparison_type"] == "no_data"
    assert forecast["budget_limit"] is None
    assert forecast["historical_average"] is None
    # no baseline to compare against, so this can never be flagged
    assert forecast["on_track_to_overspend"] is False


async def test_projection_formula_ignores_historical_average_below_min_history_months(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 4, "category_name": "bills", "total_spent": 40.0}]),
    )
    monkeypatch.setattr(forecasting_agent, "get_budget", AsyncMock(return_value=None))
    # months_counted=0 is below MIN_HISTORY_MONTHS(=1) - should be treated
    # the same as "no history at all", not used as a baseline.
    monkeypatch.setattr(
        forecasting_agent,
        "get_historical_monthly_average",
        AsyncMock(return_value={"average_monthly_spend": 999.0, "months_counted": 0}),
    )
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    forecast = result["forecasts"][0]
    assert forecast["comparison_type"] == "no_data"
    assert forecast["historical_average"] is None


async def test_projection_formula_across_multiple_categories_and_a_leap_year_february(monkeypatch):
    _set_today(monkeypatch, 2028, 2, 4)  # day 4 of Feb 2028 - a 29-day leap-year month

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(
            return_value=[
                {"category_id": 1, "category_name": "food", "total_spent": 40.0},
                {"category_id": 2, "category_name": "shopping", "total_spent": 8.0},
            ]
        ),
    )
    # Budgets are now looked up concurrently (asyncio.gather), so a
    # call-order-based side_effect list would be unreliable - key the
    # mock's response off the actual category_id argument instead.
    budgets_by_category = {1: {"monthly_limit": 200.0, "category_id": 1}}

    async def fake_get_budget(owner_id, category_id):
        return budgets_by_category.get(category_id)

    monkeypatch.setattr(forecasting_agent, "get_budget", fake_get_budget)
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    by_category = {f["category"]: f for f in result["forecasts"]}
    # (40 / 4) * 29 = 290.0
    assert by_category["food"]["projected_total"] == pytest.approx(290.0)
    assert by_category["food"]["comparison_type"] == "budget"
    assert by_category["food"]["on_track_to_overspend"] is True  # 290 > 200
    # (8 / 4) * 29 = 58.0
    assert by_category["shopping"]["projected_total"] == pytest.approx(58.0)
    assert by_category["shopping"]["comparison_type"] == "no_data"


async def test_generate_forecast_skips_the_llm_call_when_there_is_no_spending(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)

    monkeypatch.setattr(forecasting_agent, "get_monthly_summary", AsyncMock(return_value=[]))
    summarize_mock = AsyncMock(return_value="should not be called")
    monkeypatch.setattr(forecasting_agent, "_summarize", summarize_mock)

    result = await forecasting_agent.generate_forecast(owner_id=1)

    assert result["forecasts"] == []
    assert result["summary"] == "No spending recorded yet this month."
    summarize_mock.assert_not_awaited()


async def test_uncategorized_spending_is_reported_as_no_data_without_a_budget_lookup(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": None, "category_name": None, "total_spent": 15.0}]),
    )
    get_budget_mock = AsyncMock()
    monkeypatch.setattr(forecasting_agent, "get_budget", get_budget_mock)
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "_summarize", AsyncMock(return_value="mock summary"))

    result = await forecasting_agent.generate_forecast(owner_id=1)

    forecast = result["forecasts"][0]
    assert forecast["category"] == "uncategorized"
    assert forecast["comparison_type"] == "no_data"
    get_budget_mock.assert_not_awaited()  # no category_id to look a budget up for


def test_forecast_line_formats_a_budget_comparison_and_overspend_flag():
    line = forecasting_agent._forecast_line(
        {
            "category": "shopping",
            "spent_so_far": 20.0,
            "projected_total": 124.0,
            "comparison_type": "budget",
            "budget_limit": 100.0,
            "historical_average": None,
            "on_track_to_overspend": True,
        }
    )
    assert "shopping" in line
    assert "Rs. 20.00" in line
    assert "Rs. 124.00" in line
    assert "budget of Rs. 100.00" in line
    assert "OVER BUDGET" in line
    assert "Rs. 24.00" in line  # over by 124 - 100


def test_forecast_line_formats_a_historical_average_comparison_without_overspend():
    line = forecasting_agent._forecast_line(
        {
            "category": "food",
            "spent_so_far": 10.0,
            "projected_total": 62.0,
            "comparison_type": "historical_average",
            "budget_limit": None,
            "historical_average": 150.0,
            "on_track_to_overspend": False,
        }
    )
    assert "historical average of Rs. 150.00" in line
    assert "OVER BUDGET" not in line
    assert "ABOVE YOUR TYPICAL SPENDING" not in line


def test_forecast_line_formats_a_no_data_comparison():
    line = forecasting_agent._forecast_line(
        {
            "category": "transport",
            "spent_so_far": 5.0,
            "projected_total": 31.0,
            "comparison_type": "no_data",
            "budget_limit": None,
            "historical_average": None,
            "on_track_to_overspend": False,
        }
    )
    assert "no budget set and not enough history yet" in line


# --- _summarize API-failure fallback ---------------------------------------
# Deliberately simulates the summary LLM call failing (network error) to
# confirm generate_forecast() still returns the already-computed numbers
# with a generic fallback summary, instead of the whole forecast crashing.


async def test_generate_forecast_falls_back_to_a_generic_summary_when_summarize_raises(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)  # day 5 of a 31-day month

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 1, "category_name": "food", "total_spent": 200.0}]),
    )
    monkeypatch.setattr(
        forecasting_agent, "get_budget", AsyncMock(return_value={"monthly_limit": 100.0, "category_id": 1})
    )
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))

    async def failing_summarize(forecasts):
        raise httpx.ConnectError("network is down")

    monkeypatch.setattr(forecasting_agent, "_summarize", failing_summarize)

    result = await forecasting_agent.generate_forecast(owner_id=1)

    # the pre-computed numbers must survive the summary failure untouched
    forecast = result["forecasts"][0]
    assert forecast["projected_total"] == pytest.approx((200.0 / 5) * 31)
    assert forecast["on_track_to_overspend"] is True

    # the summary falls back to a generic, non-crashing sentence that still
    # names the at-risk category rather than a bare error
    assert "couldn't be generated" in result["summary"]
    assert "food" in result["summary"]


async def test_generate_forecast_fallback_summary_mentions_no_risk_when_everything_is_on_track(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 1, "category_name": "food", "total_spent": 10.0}]),
    )
    monkeypatch.setattr(
        forecasting_agent, "get_budget", AsyncMock(return_value={"monthly_limit": 1000.0, "category_id": 1})
    )
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))

    async def failing_summarize(forecasts):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(forecasting_agent, "_summarize", failing_summarize)

    result = await forecasting_agent.generate_forecast(owner_id=1)

    assert result["forecasts"][0]["on_track_to_overspend"] is False
    assert "on track" in result["summary"]
    assert "couldn't be generated" in result["summary"]


async def test_generate_forecast_fallback_also_triggers_on_missing_api_key(monkeypatch):
    _set_today(monkeypatch, 2026, 3, 5)

    monkeypatch.setattr(
        forecasting_agent,
        "get_monthly_summary",
        AsyncMock(return_value=[{"category_id": 1, "category_name": "food", "total_spent": 10.0}]),
    )
    monkeypatch.setattr(forecasting_agent, "get_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(forecasting_agent, "get_historical_monthly_average", AsyncMock(return_value=None))

    async def failing_summarize(forecasts):
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    monkeypatch.setattr(forecasting_agent, "_summarize", failing_summarize)

    # must not raise - the whole point is that this degrades gracefully
    result = await forecasting_agent.generate_forecast(owner_id=1)
    assert "couldn't be generated" in result["summary"]
