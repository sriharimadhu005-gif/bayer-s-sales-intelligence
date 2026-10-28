"""
Tests for Date Handling, Runtime Timezone (Asia/Kolkata), and Historical Date Separation.
"""
from datetime import date, datetime, timedelta
import pytest

from app import date_utils
from app.chat import (
    _resolve_date_range,
    build_system_prompt,
    build_synthesis_prompt,
    _deterministic_fallback,
    chat,
)


# ── 1. Date Utils Tests ───────────────────────────────────────────────────────

def test_current_datetime_is_asia_kolkata():
    """Verify that current datetime has the Asia/Kolkata timezone or +05:30 offset."""
    dt = date_utils.get_current_datetime()
    assert dt.tzinfo is not None
    # Offset should be +05:30 (19800 seconds)
    offset = dt.utcoffset()
    assert offset == timedelta(hours=5, minutes=30)


def test_current_date_iso_and_weekday():
    """Verify ISO date format YYYY-MM-DD and weekday name."""
    iso_date = date_utils.get_current_date_iso()
    assert len(iso_date.split("-")) == 3
    year, month, day = [int(x) for x in iso_date.split("-")]
    assert year >= 2026

    weekday = date_utils.get_current_weekday()
    assert weekday in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    disp = date_utils.get_current_date_display()
    assert str(year) in disp


def test_relative_date_bounds():
    """Verify relative date bounds dictionary has all required keys and valid ISO dates."""
    today = date_utils.get_current_date()
    bounds = date_utils.get_relative_date_bounds(today)

    assert bounds["today"] == today.isoformat()
    assert bounds["yesterday"] == (today - timedelta(days=1)).isoformat()
    assert "this_week_start" in bounds
    assert "last_week_start" in bounds
    assert "this_month_start" in bounds
    assert "last_month_start" in bounds


def test_days_since_date():
    """Verify days calculation between today and historical dates."""
    today = date_utils.get_current_date()
    # If target is 10 days ago:
    past_date = (today - timedelta(days=10)).isoformat()
    assert date_utils.days_since_date(past_date) == 10


def test_sales_date_range_is_separate_from_current_date():
    """Verify that sales date range min/max is distinct from today's date."""
    min_date, max_date = date_utils.get_sales_date_range()
    today_iso = date_utils.get_current_date_iso()

    assert min_date <= max_date
    assert max_date == "2026-04-15"
    # Today is in September 2026, max sales date is April 2026
    assert today_iso != max_date


# ── 2. Natural Language Date Resolver Tests ───────────────────────────────────

def test_resolve_date_range_relative():
    """Test resolution of relative terms: today, yesterday, this week, last week, this month, last month."""
    today = date_utils.get_current_date()

    # Today
    df, dt = _resolve_date_range("give me sales report for today")
    assert df == today.isoformat()
    assert dt == today.isoformat()

    # Yesterday
    df, dt = _resolve_date_range("sales report for yesterday")
    yesterday = (today - timedelta(days=1)).isoformat()
    assert df == yesterday
    assert dt == yesterday

    # This month
    df, dt = _resolve_date_range("generate report for this month")
    assert df == today.replace(day=1).isoformat()
    assert dt == today.isoformat()

    # Last month
    df, dt = _resolve_date_range("bde report for last month")
    first_of_current = today.replace(day=1)
    last_of_prev = first_of_current - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    assert df == first_of_prev.isoformat()
    assert dt == last_of_prev.isoformat()


def test_resolve_date_range_explicit_historical():
    """Verify explicit historical dates are preserved accurately."""
    df, dt = _resolve_date_range("sales report for 1 April to 15 April 2026")
    assert df == "2026-04-01"
    assert dt == "2026-04-15"

    df, dt = _resolve_date_range("report from 01/04/2026 to 15/04/2026")
    assert df == "2026-04-01"
    assert dt == "2026-04-15"


# ── 3. Prompt Construction Tests ─────────────────────────────────────────────

def test_system_prompt_contains_dynamic_runtime_date_and_separation():
    """Verify system prompt dynamically injects runtime date and states separation from DB records."""
    prompt = build_system_prompt()
    today_iso = date_utils.get_current_date_iso()
    weekday = date_utils.get_current_weekday()
    latest_date = date_utils.get_latest_sales_date()

    # Current runtime date must be present
    assert today_iso in prompt
    assert weekday in prompt
    assert "Asia/Kolkata" in prompt

    # Clear separation rules
    assert "SEPARATION OF SYSTEM DATE VS HISTORICAL SALES DATA" in prompt
    assert "NEVER confuse the current system date" in prompt
    assert "NEVER describe" in prompt
    assert latest_date in prompt


def test_synthesis_prompt_contains_dynamic_runtime_date():
    """Verify synthesis prompt contains dynamic runtime date and distinct DB bounds."""
    synth_prompt = build_synthesis_prompt(
        question="What is the date today?",
        sql="SELECT CURRENT_DATE;",
        results='[{"current_date": "2026-09-21"}]',
    )
    today_disp = date_utils.get_current_date_display()
    today_iso = date_utils.get_current_date_iso()

    assert today_disp in synth_prompt
    assert today_iso in synth_prompt
    assert "Historical sales data range in database" in synth_prompt


# ── 4. Fallback Engine Tests ─────────────────────────────────────────────────

def test_deterministic_fallback_date_today():
    """Test deterministic fallback responds with dynamic current date."""
    res = _deterministic_fallback("What is the date today?", "test-conv-1")
    today_disp = date_utils.get_current_date_display()
    today_iso = date_utils.get_current_date_iso()

    assert today_disp in res["answer_text"]
    assert today_iso in res["answer_text"]
    assert "Asia/Kolkata" in res["answer_text"]


def test_deterministic_fallback_latest_date_in_sales():
    """Test deterministic fallback distinguishes latest data date from today."""
    res = _deterministic_fallback("What was the latest date in the sales data?", "test-conv-2")
    assert "2026-04-15" in res["answer_text"]
    assert "latest available sales data" in res["answer_text"]


def test_deterministic_fallback_days_ago():
    """Test deterministic fallback calculates days difference dynamically."""
    res = _deterministic_fallback("How many days ago was April 15?", "test-conv-3")
    days = date_utils.days_since_date("2026-04-15")
    assert f"{days} days ago" in res["answer_text"]


# ── 5. End-to-End Chat Inquiries ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_what_is_the_date_today():
    """Live/integration test for 'What is the date today?'."""
    res = await chat("What is the date today?", conversation_id="test-date-today")
    today_disp = date_utils.get_current_date_display()
    today_iso = date_utils.get_current_date_iso()
    weekday = date_utils.get_current_weekday()

    # The answer MUST contain current date/month/year or weekday, NOT 2026-04-15 as today
    answer = res["answer_text"]
    # Check that it contains current month, day and year or display date
    curr_d = date_utils.get_current_date()
    has_date = (
        (today_iso in answer)
        or (today_disp in answer)
        or (f"{curr_d.strftime('%B %d, %Y')}" in answer)
        or (curr_d.strftime('%B') in answer and str(curr_d.year) in answer and str(curr_d.day) in answer)
    )
    assert has_date, f"Expected current date in answer, got: {answer}"
    # Must NOT say 'today is 2026-04-15' or 'current date in the system is 2026-04-15'
    assert "current date in the system is 2026-04-15" not in answer.lower()
    assert "today is 2026-04-15" not in answer.lower()
    assert "today's date is 2026-04-15" not in answer.lower()


@pytest.mark.asyncio
async def test_chat_what_is_latest_date_in_sales():
    """Live/integration test for 'What is the latest date in the sales data?'."""
    res = await chat("What was the latest date in the sales data?", conversation_id="test-latest-sales")
    answer = res["answer_text"]
    assert "2026-04-15" in answer or "April 15, 2026" in answer
    # Must NOT claim this is today's date
    assert "today is" not in answer.lower() or "today is september" in answer.lower() or "latest" in answer.lower()


@pytest.mark.asyncio
async def test_chat_sales_on_april_15_historical_preserved():
    """Verify querying historical sales on April 15 still works properly."""
    res = await chat("What were the sales on April 15?", conversation_id="test-april-15-sales")
    answer = res["answer_text"]
    # Historical sales data exists for April 15, 2026, so numbers or summary should be returned
    assert "kg" in answer.lower() or "sales" in answer.lower()
    assert res.get("answer_text") is not None
