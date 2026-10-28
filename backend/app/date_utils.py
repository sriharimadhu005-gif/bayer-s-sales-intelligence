"""
Horeca Sales Intelligence — Authoritative Runtime Date & Time Utilities.

Provides a single authoritative runtime clock for the application grounded in
India Standard Time (Asia/Kolkata, UTC+5:30).

Strictly separates:
1. CURRENT SYSTEM DATE & TIME — Actual runtime date/time in Asia/Kolkata.
2. HISTORICAL SALES DATA RANGE — Min/max sale_date in the PostgreSQL database.
3. LATEST AVAILABLE DATA DATE — The maximum sale_date present in the sales table.
"""
from datetime import date, datetime, timedelta, timezone
import calendar

# ── 1. Authoritative Timezone Definition ─────────────────────────────────────

try:
    from zoneinfo import ZoneInfo
    # Verify tzdata is present and functional
    _tz_test = ZoneInfo("Asia/Kolkata")
    datetime.now(_tz_test)
    INDIA_TZ = _tz_test
except Exception:
    # Standard library fallback with exact offset (+05:30, no DST in India)
    INDIA_TZ = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


# ── 2. Dynamic Runtime Date & Time Accessors ──────────────────────────────────

def get_current_datetime() -> datetime:
    """Return the current dynamic datetime in Asia/Kolkata."""
    return datetime.now(INDIA_TZ)


def get_current_date() -> date:
    """Return the current dynamic date in Asia/Kolkata."""
    return get_current_datetime().date()


def get_current_date_iso() -> str:
    """Return the current date as an ISO string (YYYY-MM-DD)."""
    return get_current_date().isoformat()


def get_current_date_display() -> str:
    """Return a human-readable date string, e.g. 'September 21, 2026'."""
    d = get_current_date()
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"


def get_current_weekday() -> str:
    """Return the current day of the week, e.g. 'Monday'."""
    return get_current_datetime().strftime("%A")


# ── 3. Relative Date Bounds Calculator ───────────────────────────────────────

def get_relative_date_bounds(ref_date: date | None = None) -> dict[str, str]:
    """
    Calculate ISO date strings (YYYY-MM-DD) for common relative temporal terms
    grounded in Asia/Kolkata.
    """
    today = ref_date or get_current_date()
    yesterday = today - timedelta(days=1)

    # Current week (Monday to today)
    this_week_start = today - timedelta(days=today.weekday())

    # Last week (Monday to Sunday of previous week)
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)

    # Current month (1st of month to today)
    this_month_start = today.replace(day=1)

    # Last month (1st of previous month to last day of previous month)
    first_of_current = this_month_start
    last_of_prev = first_of_current - timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)

    return {
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "this_week_start": this_week_start.isoformat(),
        "this_week_end": today.isoformat(),
        "last_week_start": last_week_start.isoformat(),
        "last_week_end": last_week_end.isoformat(),
        "this_month_start": this_month_start.isoformat(),
        "this_month_end": today.isoformat(),
        "last_month_start": first_of_prev.isoformat(),
        "last_month_end": last_of_prev.isoformat(),
    }


def days_since_date(iso_date: str) -> int:
    """Calculate the number of days from an ISO date to today."""
    target = datetime.strptime(iso_date, "%Y-%m-%d").date()
    today = get_current_date()
    return (today - target).days


# ── 4. Sales Data Date Range Accessors ───────────────────────────────────────

_cached_range: tuple[str, str] | None = None
_last_range_check: datetime | None = None


def get_sales_date_range() -> tuple[str, str]:
    """
    Query the database for the min/max sale_date in daily_sales.
    Caches for 60 seconds to avoid unnecessary DB queries on every prompt build.
    Falls back to known baseline range if database is unreachable.
    """
    global _cached_range, _last_range_check
    now = get_current_datetime()
    if _cached_range and _last_range_check and (now - _last_range_check).total_seconds() < 60:
        return _cached_range

    try:
        from . import db
        rows = db.query(
            "SELECT MIN(sale_date)::text AS min_date, "
            "MAX(sale_date)::text AS max_date FROM daily_sales"
        )
        if rows and rows[0].get("min_date") and rows[0].get("max_date"):
            _cached_range = (rows[0]["min_date"], rows[0]["max_date"])
            _last_range_check = now
            return _cached_range
    except Exception:
        pass

    # Baseline fallback if DB query fails
    return ("2026-04-01", "2026-04-15")


def get_latest_sales_date() -> str:
    """Return the latest available sales record date in the database."""
    _, max_date = get_sales_date_range()
    return max_date


def format_date_for_display(iso_date: str | None) -> str:
    """Format an ISO date string (YYYY-MM-DD) into a human readable string like '15 April 2026'."""
    if not iso_date:
        return ""
    try:
        parts = iso_date.split("-")
        if len(parts) == 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            month_name = calendar.month_name[m]
            return f"{d} {month_name} {y}"
    except Exception:
        pass
    return str(iso_date)


def format_display_period(iso_from: str, iso_to: str) -> str:
    """Format a date range into a readable period like '31 March 2026 to 15 April 2026'."""
    d1 = format_date_for_display(iso_from)
    d2 = format_date_for_display(iso_to)
    if d1 and d2:
        return f"{d1} to {d2}"
    return d1 or d2 or "all available sales records"

