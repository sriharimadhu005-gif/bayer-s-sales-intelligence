"""
Horeca Sales Intelligence — Deterministic Report Engine.

Generates multi-tab Excel workbooks or PDF reports from PostgreSQL data
based on structured filter parameters from the frontend.
"""
import io
import re
from datetime import datetime, date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from . import db

# Day-of-week mapping: Python's weekday() -> 0=Mon..6=Sun
DOW_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _parse_date(d: str) -> str:
    """Convert DD/MM/YYYY to YYYY-MM-DD for SQL."""
    parts = d.strip().split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return d  # already ISO


def _build_report_query(
    date_from: str,
    date_to: str,
    days: list[str] | None,
    route_ids: list[int] | None,
    branches: list[str] | None,
    sku_ids: list[int] | None,
    customer_ids: list[str] | None,
) -> tuple[str, list]:
    """Build parameterised SQL for the report from the sales analytics view."""
    conditions = []
    params = []
    idx = 1

    # Date range
    iso_from = _parse_date(date_from)
    iso_to = _parse_date(date_to)
    conditions.append(f"ds.sale_date >= ${idx}::date")
    params.append(iso_from)
    idx += 1
    conditions.append(f"ds.sale_date <= ${idx}::date")
    params.append(iso_to)
    idx += 1

    # Day-of-week filter
    if days and len(days) < 7:
        dow_nums = [DOW_MAP[d] for d in days if d in DOW_MAP]
        if dow_nums:
            placeholders = ", ".join(f"${idx + i}" for i in range(len(dow_nums)))
            conditions.append(f"EXTRACT(DOW FROM ds.sale_date)::int IN ({placeholders})")
            # PostgreSQL DOW: 0=Sun, 1=Mon..6=Sat  → convert from Python convention
            pg_dow = [(d + 1) % 7 for d in dow_nums]
            params.extend(pg_dow)
            idx += len(dow_nums)

    # Route filter
    if route_ids:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(route_ids)))
        conditions.append(f"ds.route_number IN ({placeholders})")
        params.extend(route_ids)
        idx += len(route_ids)

    # Branch / category filter
    if branches:
        branch_conditions = []
        for b in branches:
            if b == "coffee":
                branch_conditions.append(f"LOWER(rc.category) LIKE ${idx}")
                params.append("%coffee%")
                idx += 1
            elif b == "tea":
                branch_conditions.append(f"LOWER(rc.category) LIKE ${idx}")
                params.append("%tea%")
                idx += 1
            elif b == "others":
                branch_conditions.append(
                    f"(LOWER(rc.category) NOT LIKE ${idx} AND LOWER(rc.category) NOT LIKE ${idx + 1} AND rc.category IS NOT NULL)"
                )
                params.extend(["%coffee%", "%tea%"])
                idx += 2
        if branch_conditions:
            conditions.append(f"({' OR '.join(branch_conditions)})")

    # SKU filter.  The client submits rate_cards IDs returned by /api/meta/skus.
    # Resolve those IDs to normalized names first: a rate card is customer-specific,
    # while a selected SKU must match that product across every customer's sales.
    if sku_ids:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(sku_ids)))
        conditions.append(
            "LOWER(TRIM(ds.sku_name)) IN ("
            "SELECT LOWER(TRIM(selected_rc.sku_name)) "
            "FROM rate_cards selected_rc "
            f"WHERE selected_rc.id IN ({placeholders})"
            ")"
        )
        params.extend(sku_ids)
        idx += len(sku_ids)

    # Customer filter
    if customer_ids:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(customer_ids)))
        conditions.append(f"ds.customer_id IN ({placeholders})")
        params.extend(customer_ids)
        idx += len(customer_ids)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = f"""
    SELECT
        ds.sale_date,
        ds.route_number,
        ds.customer_id,
        c.name AS customer_name,
        ds.sku_name,
        ds.qty_kg,
        rc.category,
        rc.approved_inclusive,
        ROUND(ds.qty_kg * COALESCE(rc.approved_inclusive, rc.std_rate, 0), 2) AS estimated_revenue
    FROM daily_sales ds
    LEFT JOIN customers c ON ds.customer_id = c.customer_id
    LEFT JOIN rate_cards rc ON ds.customer_id = rc.customer_id
                            AND LOWER(TRIM(ds.sku_name)) = LOWER(TRIM(rc.sku_name))
    WHERE {where_clause}
    ORDER BY ds.sale_date, ds.route_number, c.name, ds.sku_name
    """
    return sql, params


def _build_financial_query(
    date_from: str,
    date_to: str,
    route_ids: list[int] | None,
    customer_ids: list[str] | None,
) -> tuple[str, list]:
    """Build query for financial summary data."""
    conditions = []
    params = []
    idx = 1

    iso_from = _parse_date(date_from)
    iso_to = _parse_date(date_to)
    conditions.append(f"summary_date >= ${idx}::date")
    params.append(iso_from)
    idx += 1
    conditions.append(f"summary_date <= ${idx}::date")
    params.append(iso_to)
    idx += 1

    if route_ids:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(route_ids)))
        conditions.append(f"route_number IN ({placeholders})")
        params.extend(route_ids)
        idx += len(route_ids)

    if customer_ids:
        placeholders = ", ".join(f"${idx + i}" for i in range(len(customer_ids)))
        conditions.append(f"customer_id IN ({placeholders})")
        params.extend(customer_ids)
        idx += len(customer_ids)

    where_clause = " AND ".join(conditions)

    sql = f"""
    SELECT summary_date, route_number, customer_id, customer_name,
           cash, credit, closing_balance
    FROM vw_daily_financial_summary
    WHERE {where_clause}
    ORDER BY summary_date, route_number, customer_name
    """
    return sql, params


# ─────────────── Excel Generator ───────────────

HEADER_FILL = PatternFill(start_color="1B3A5C", end_color="1B3A5C", fill_type="solid")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
DATA_FONT = Font(name="Calibri", size=10)
BORDER = Border(
    left=Side(style="thin", color="D0D0D0"),
    right=Side(style="thin", color="D0D0D0"),
    top=Side(style="thin", color="D0D0D0"),
    bottom=Side(style="thin", color="D0D0D0"),
)


def _style_header(ws, col_count: int):
    for col in range(1, col_count + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER


def _auto_width(ws, col_count: int):
    for col in range(1, col_count + 1):
        max_len = 0
        letter = get_column_letter(col)
        for row in ws.iter_rows(min_col=col, max_col=col, values_only=False):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max_len + 4, 35)


def generate_excel(
    date_from: str,
    date_to: str,
    days: list[str] | None,
    route_ids: list[int] | None,
    branches: list[str] | None,
    sku_ids: list[int] | None,
    customer_ids: list[str] | None,
    notes: str | None,
) -> tuple[bytes | None, str | None]:
    """Generate an Excel report. Returns (bytes, None) or (None, error_message)."""

    sql, params = _build_report_query(date_from, date_to, days, route_ids, branches, sku_ids, customer_ids)

    # psycopg2 uses %s placeholders — convert $N to %s
    converted_sql = re.sub(r"\$\d+", "%s", sql)
    rows = db.query(converted_sql, params)

    if not rows:
        return None, "No data found for the selected filters."

    # Financial data
    fin_sql, fin_params = _build_financial_query(date_from, date_to, route_ids, customer_ids)
    converted_fin_sql = re.sub(r"\$\d+", "%s", fin_sql)
    fin_rows = db.query(converted_fin_sql, fin_params)

    wb = Workbook()

    # ── Tab 1: Executive Summary ──
    ws1 = wb.active
    ws1.title = "Executive Summary"

    total_qty = sum(float(r.get("qty_kg") or 0) for r in rows)
    total_rev = sum(float(r.get("estimated_revenue") or 0) for r in rows)
    unique_customers = len(set(r["customer_id"] for r in rows if r.get("customer_id")))
    unique_skus = len(set(r["sku_name"] for r in rows if r.get("sku_name")))
    unique_routes = sorted(set(r["route_number"] for r in rows if r.get("route_number")))
    total_cash = sum(float(r.get("cash") or 0) for r in fin_rows)
    total_credit = sum(float(r.get("credit") or 0) for r in fin_rows)

    summary_data = [
        ["Metric", "Value"],
        ["Report Period", f"{date_from} to {date_to}"],
        ["Total Sales Volume (KG)", f"{total_qty:,.1f}"],
        ["Estimated Revenue (₹)", f"{total_rev:,.2f}"],
        ["Active Customers", unique_customers],
        ["Unique SKUs Sold", unique_skus],
        ["Routes Covered", ", ".join(f"R{r}" for r in unique_routes)],
        ["Total Cash Collected (₹)", f"{total_cash:,.2f}"],
        ["Total Credit (₹)", f"{total_credit:,.2f}"],
        ["Total Transactions", len(rows)],
    ]
    for row_data in summary_data:
        ws1.append(row_data)

    _style_header(ws1, 2)
    _auto_width(ws1, 2)

    # ── Tab 2: Sales Breakdown ──
    ws2 = wb.create_sheet("Sales Breakdown")
    headers = ["Date", "Route", "Customer ID", "Customer Name", "SKU", "Qty (KG)", "Category", "Rate (₹)", "Revenue (₹)"]
    ws2.append(headers)

    for r in rows:
        ws2.append([
            r.get("sale_date").isoformat() if isinstance(r.get("sale_date"), (date, datetime)) else str(r.get("sale_date", "")),
            r.get("route_number"),
            r.get("customer_id"),
            r.get("customer_name"),
            r.get("sku_name"),
            float(r.get("qty_kg") or 0),
            r.get("category"),
            float(r.get("approved_inclusive") or 0),
            float(r.get("estimated_revenue") or 0),
        ])

    _style_header(ws2, len(headers))
    _auto_width(ws2, len(headers))

    # ── Tab 3: Financial Summary ──
    if fin_rows:
        ws3 = wb.create_sheet("Financial Summary")
        fin_headers = ["Date", "Route", "Customer ID", "Customer Name", "Cash (₹)", "Credit (₹)", "Closing Balance (₹)"]
        ws3.append(fin_headers)
        for r in fin_rows:
            ws3.append([
                r.get("summary_date").isoformat() if isinstance(r.get("summary_date"), (date, datetime)) else str(r.get("summary_date", "")),
                r.get("route_number"),
                r.get("customer_id"),
                r.get("customer_name"),
                float(r.get("cash") or 0),
                float(r.get("credit") or 0),
                float(r.get("closing_balance") or 0),
            ])
        _style_header(ws3, len(fin_headers))
        _auto_width(ws3, len(fin_headers))

    # ── Tab 4: Filters & Audit ──
    ws4 = wb.create_sheet("Filters & Audit")
    audit_data = [
        ["Parameter", "Value"],
        ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Date Range", f"{date_from} — {date_to}"],
        ["Days of Week", ", ".join(days) if days else "All days"],
        ["Routes", ", ".join(f"R{r}" for r in route_ids) if route_ids else "All routes"],
        ["Branches", ", ".join(branches) if branches else "All branches"],
        ["Customer Filter", ", ".join(customer_ids) if customer_ids else "All customers"],
    ]
    for row_data in audit_data:
        ws4.append(row_data)
    _style_header(ws4, 2)
    _auto_width(ws4, 2)

    # Write to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), None


# ─────────────── PDF Generator ───────────────

def generate_pdf(
    date_from: str,
    date_to: str,
    days: list[str] | None,
    route_ids: list[int] | None,
    branches: list[str] | None,
    sku_ids: list[int] | None,
    customer_ids: list[str] | None,
    notes: str | None,
) -> tuple[bytes | None, str | None]:
    """Generate a PDF report. Returns (bytes, None) or (None, error_message)."""

    sql, params = _build_report_query(date_from, date_to, days, route_ids, branches, sku_ids, customer_ids)
    converted_sql = re.sub(r"\$\d+", "%s", sql)
    rows = db.query(converted_sql, params)

    if not rows:
        return None, "No data found for the selected filters."

    total_qty = sum(float(r.get("qty_kg") or 0) for r in rows)
    total_rev = sum(float(r.get("estimated_revenue") or 0) for r in rows)
    unique_customers = len(set(r["customer_id"] for r in rows if r.get("customer_id")))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_style = ParagraphStyle("ReportTitle", parent=styles["Heading1"], fontSize=18, spaceAfter=6 * mm, textColor=colors.HexColor("#1B3A5C"))
    elements.append(Paragraph("Horeca Sales Intelligence Report", title_style))
    elements.append(Paragraph(f"Period: {date_from} — {date_to}", styles["Normal"]))
    elements.append(Spacer(1, 6 * mm))

    # KPI summary
    kpi_data = [
        ["Total Volume (KG)", "Estimated Revenue (₹)", "Active Customers", "Transactions"],
        [f"{total_qty:,.1f}", f"{total_rev:,.2f}", str(unique_customers), str(len(rows))],
    ]
    kpi_table = Table(kpi_data, colWidths=[60 * mm] * 4)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A5C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 8 * mm))

    # Detail table (top 100 rows)
    detail_headers = ["Date", "Route", "Customer", "SKU", "Qty (KG)", "Revenue (₹)"]
    detail_data = [detail_headers]
    for r in rows[:100]:
        d = r.get("sale_date")
        detail_data.append([
            d.isoformat() if isinstance(d, (date, datetime)) else str(d or ""),
            str(r.get("route_number", "")),
            str(r.get("customer_name", ""))[:30],
            str(r.get("sku_name", ""))[:25],
            f"{float(r.get('qty_kg') or 0):.1f}",
            f"{float(r.get('estimated_revenue') or 0):.2f}",
        ])

    detail_table = Table(detail_data, colWidths=[28 * mm, 18 * mm, 55 * mm, 50 * mm, 28 * mm, 30 * mm])
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(detail_table)

    if len(rows) > 100:
        elements.append(Spacer(1, 4 * mm))
        elements.append(Paragraph(f"Showing 100 of {len(rows)} records. Use Excel format for full data.", styles["Italic"]))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue(), None


# ═══════════════════════════════════════════════════════════════════
#  Spec-Driven Excel Builder
#  Builds workbooks from a ReportSpec JSON produced by report_spec.py
# ═══════════════════════════════════════════════════════════════════

# ── column label mapping ──────────────────────────────────────────
COLUMN_LABELS: dict[str, str] = {
    "sale_date":          "Date",
    "route_number":       "Route",
    "customer_id":        "Customer ID",
    "customer_name":      "Customer Name",
    "sku_name":           "SKU",
    "qty_kg":             "Qty (KG)",
    "category":           "Category",
    "approved_inclusive": "Rate (Rs)",
    "estimated_revenue":  "Revenue (Rs)",
    "summary_date":       "Date",
    "cash":               "Cash (Rs)",
    "credit":             "Credit (Rs)",
    "closing_balance":    "Closing Balance (Rs)",
}

_VALID_SALES_COLS = set(COLUMN_LABELS.keys())

DEFAULT_TABULAR_COLS = [
    "sale_date", "route_number", "customer_id", "customer_name",
    "sku_name", "qty_kg", "category", "approved_inclusive", "estimated_revenue",
]

# ── sort-key lambdas per field ────────────────────────────────────
SORT_KEYS: dict[str, object] = {
    "sale_date":          lambda r: str(r.get("sale_date", "")),
    "route_number":       lambda r: int(r.get("route_number") or 0),
    "customer_id":        lambda r: str(r.get("customer_id", "")),
    "customer_name":      lambda r: str(r.get("customer_name", "")),
    "sku_name":           lambda r: str(r.get("sku_name", "")),
    "qty_kg":             lambda r: float(r.get("qty_kg") or 0),
    "estimated_revenue":  lambda r: float(r.get("estimated_revenue") or 0),
    "category":           lambda r: str(r.get("category", "")),
    "approved_inclusive": lambda r: float(r.get("approved_inclusive") or 0),
}

# ── fills ─────────────────────────────────────────────────────────
ALT_FILL       = PatternFill(start_color="F5F7FA", end_color="F5F7FA", fill_type="solid")
HIGHLIGHT_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
TOTAL_FILL     = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
TOTAL_FONT     = Font(name="Calibri", bold=True, size=10, color="1B3A5C")


# ── value extractor ───────────────────────────────────────────────

def _row_val(row: dict, field: str):
    """Extract and normalise a single cell value from a data row dict."""
    val = row.get(field)
    if isinstance(val, (date, datetime)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


# ── public helpers (used by main.py) ─────────────────────────────

def fetch_report_rows(
    date_from: str,
    date_to: str,
    days: list[str] | None,
    route_ids: list[int] | None,
    branches: list[str] | None,
    sku_ids: list[int] | None,
    customer_ids: list[str] | None,
) -> list[dict]:
    """Fetch and return sales rows using the existing query builder."""
    sql, params = _build_report_query(
        date_from, date_to, days, route_ids, branches, sku_ids, customer_ids
    )
    converted = re.sub(r"\$\d+", "%s", sql)
    return db.query(converted, params)


def fetch_financial_rows(
    date_from: str,
    date_to: str,
    route_ids: list[int] | None,
    customer_ids: list[str] | None,
) -> list[dict]:
    """Fetch and return financial rows using the existing query builder."""
    fin_sql, fin_params = _build_financial_query(
        date_from, date_to, route_ids, customer_ids
    )
    converted = re.sub(r"\$\d+", "%s", fin_sql)
    return db.query(converted, fin_params)


# ── chart helper ──────────────────────────────────────────────────

def _add_chart_to_ws(ws, chart_spec: dict, columns: list[str], data: list[dict]) -> None:
    """Embed an openpyxl chart into a worksheet based on chart_spec."""
    try:
        chart_type = chart_spec.get("type", "bar")
        title      = chart_spec.get("title", "Chart")
        x_col      = chart_spec.get("x_column")
        y_col      = chart_spec.get("y_column")
        position   = chart_spec.get("position", "right_of_table")

        if not y_col or y_col not in columns:
            return

        # Aggregate data by x_col (max 20 categories to keep chart readable)
        if x_col and x_col in columns:
            agg: dict = {}
            order: list = []
            for r in data:
                key = str(_row_val(r, x_col) or "")
                val = float(r.get(y_col) or 0)
                if key not in agg:
                    agg[key] = 0.0
                    order.append(key)
                agg[key] += val
            chart_pairs = [(k, agg[k]) for k in order][:20]
        else:
            chart_pairs = [(str(i + 1), float(r.get(y_col) or 0)) for i, r in enumerate(data[:20])]

        if not chart_pairs:
            return

        # Write a small hidden data block below the main table for the chart
        data_start_row = ws.max_row + 2
        ws.cell(row=data_start_row, column=1).value = "Category"
        ws.cell(row=data_start_row, column=2).value = y_col
        for i, (label, val) in enumerate(chart_pairs):
            ws.cell(row=data_start_row + 1 + i, column=1).value = label
            ws.cell(row=data_start_row + 1 + i, column=2).value = val

        data_end_row = data_start_row + len(chart_pairs)
        data_ref = Reference(ws, min_col=2, min_row=data_start_row, max_row=data_end_row)
        cats_ref = Reference(ws, min_col=1, min_row=data_start_row + 1, max_row=data_end_row)

        if chart_type == "line":
            chart = LineChart()
        elif chart_type == "pie":
            chart = PieChart()
        else:
            chart = BarChart()
            # "bar" = horizontal, "column" = vertical (openpyxl default is col)
            if chart_type == "bar":
                chart.type = "bar"
            # else leave as default "col"

        chart.title = title
        chart.add_data(data_ref, titles_from_data=True)
        if not isinstance(chart, PieChart):
            chart.set_categories(cats_ref)
        chart.width  = 20
        chart.height = 12

        # Anchor position
        if position == "below_table":
            anchor = f"A{data_end_row + 2}"
        else:
            anchor = f"{get_column_letter(len(columns) + 2)}2"

        ws.add_chart(chart, anchor)

    except Exception:
        # Chart failure is non-fatal — continue without it
        import traceback as _tb
        _tb.print_exc()


# ── conditional formatting helper ────────────────────────────────

def _apply_cf(ws, cf_spec: dict, columns: list[str], data: list[dict]) -> None:
    """Apply conditional formatting (top-N highlight or above-average highlight)."""
    column     = cf_spec.get("column")
    rule       = cf_spec.get("rule", "top_n")
    n          = int(cf_spec.get("n", 10))
    fill_color = str(cf_spec.get("fill_color", "FFFF00"))

    if not column or column not in columns:
        return

    col_idx = columns.index(column) + 1
    values_with_rows = [
        (float(r.get(column) or 0), row_idx)
        for row_idx, r in enumerate(data, start=2)
    ]

    if rule == "top_n":
        target_rows = {
            row_idx for _, row_idx
            in sorted(values_with_rows, reverse=True)[:n]
        }
    elif rule == "above_avg":
        avg = (
            sum(v for v, _ in values_with_rows) / len(values_with_rows)
            if values_with_rows else 0
        )
        target_rows = {row_idx for v, row_idx in values_with_rows if v > avg}
    else:
        return

    fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
    for row_idx in target_rows:
        for c in range(1, len(columns) + 1):
            ws.cell(row=row_idx, column=c).fill = fill


# ── sheet builders ────────────────────────────────────────────────

def _build_tabular_sheet(wb: Workbook, ws_spec: dict, rows: list[dict]) -> None:
    """Build a flat-tabular worksheet."""
    name         = ws_spec.get("name", "Sheet")[:31]
    raw_cols     = ws_spec.get("columns") or DEFAULT_TABULAR_COLS
    # Sanitise: keep only valid sales field names
    columns      = [c for c in raw_cols if c in _VALID_SALES_COLS]
    if not columns:
        columns = DEFAULT_TABULAR_COLS[:]

    filter_route  = ws_spec.get("filter_route")
    sort_by       = ws_spec.get("sort_by")
    sort_order    = ws_spec.get("sort_order", "asc")
    top_n         = ws_spec.get("top_n")
    highlight_top = ws_spec.get("highlight_top_n")
    show_totals   = ws_spec.get("show_totals_row", False)
    freeze        = ws_spec.get("freeze_header", True)
    auto_size     = ws_spec.get("auto_size_columns", True)

    # Filter
    data = rows
    if filter_route is not None:
        data = [r for r in data if r.get("route_number") == int(filter_route)]

    # Sort
    if sort_by and sort_by in SORT_KEYS:
        data = sorted(data, key=SORT_KEYS[sort_by], reverse=(sort_order == "desc"))

    # Top-N slice
    if top_n:
        data = data[: int(top_n)]

    ws = wb.create_sheet(name)

    # Header row
    ws.append([COLUMN_LABELS.get(c, c) for c in columns])
    _style_header(ws, len(columns))

    # Data rows
    for i, r in enumerate(data, start=2):
        ws.append([_row_val(r, c) for c in columns])
        if i % 2 == 0:
            for ci in range(1, len(columns) + 1):
                ws.cell(row=i, column=ci).fill = ALT_FILL

    # Highlight top-N rows by estimated_revenue (if field present)
    if highlight_top and data:
        sort_col = "estimated_revenue" if "estimated_revenue" in columns else columns[-1]
        top_rows = sorted(
            range(2, len(data) + 2),
            key=lambda ri: float(ws.cell(row=ri, column=columns.index(sort_col) + 1).value or 0),
            reverse=True,
        )[: int(highlight_top)]
        for ri in top_rows:
            for ci in range(1, len(columns) + 1):
                ws.cell(row=ri, column=ci).fill = HIGHLIGHT_FILL

    # Totals row
    if show_totals and data:
        _NUMERIC = {"qty_kg", "estimated_revenue", "approved_inclusive"}
        totals = []
        for idx, c in enumerate(columns):
            if c in _NUMERIC:
                totals.append(sum(float(r.get(c) or 0) for r in data))
            elif idx == 0:
                totals.append("TOTAL")
            else:
                totals.append("")
        ws.append(totals)
        last = len(data) + 2
        for ci in range(1, len(columns) + 1):
            ws.cell(row=last, column=ci).font = TOTAL_FONT
            ws.cell(row=last, column=ci).fill = TOTAL_FILL

    # Freeze / auto-size
    if freeze:
        ws.freeze_panes = "A2"
    if auto_size:
        _auto_width(ws, len(columns))

    # Conditional formats
    for cf in ws_spec.get("conditional_formats") or []:
        _apply_cf(ws, cf, columns, data)

    # Charts
    for chart_spec in ws_spec.get("charts") or []:
        _add_chart_to_ws(ws, chart_spec, columns, data)


def _build_pivot_sheet(wb: Workbook, ws_spec: dict, rows: list[dict]) -> None:
    """Build a pivot (cross-tab) worksheet."""
    name              = ws_spec.get("name", "Pivot")[:31]
    pivot_row_fields  = ws_spec.get("pivot_rows") or ["customer_id", "customer_name"]
    pivot_col_field   = ws_spec.get("pivot_columns") or "sku_name"
    pivot_val_field   = ws_spec.get("pivot_values") or "qty_kg"
    aggfunc           = ws_spec.get("pivot_aggfunc", "sum")
    sort_by           = ws_spec.get("sort_by", "row_total")
    sort_order        = ws_spec.get("sort_order", "desc")
    highlight_top     = ws_spec.get("highlight_top_n")
    show_row_totals   = ws_spec.get("show_row_totals", True)
    show_col_totals   = ws_spec.get("show_col_totals", True)
    freeze            = ws_spec.get("freeze_header", True)
    auto_size         = ws_spec.get("auto_size_columns", True)

    # Sanitise field references
    pivot_row_fields = [f for f in pivot_row_fields if f in _VALID_SALES_COLS]
    if not pivot_row_fields:
        pivot_row_fields = ["customer_id", "customer_name"]

    # ── Collect unique column values (max 50 to keep workbook sane) ──
    all_col_vals = sorted({
        str(r.get(pivot_col_field, "") or "")
        for r in rows
        if r.get(pivot_col_field)
    })[:50]

    # ── Build pivot data structure ──
    # pivot_data[row_key] = {col_val: [values…]}
    pivot_data: dict[tuple, dict[str, list]] = {}
    row_labels: dict[tuple, list] = {}

    for r in rows:
        row_key = tuple(str(r.get(f, "") or "") for f in pivot_row_fields)
        col_val = str(r.get(pivot_col_field, "") or "")
        val     = float(r.get(pivot_val_field) or 0)

        if row_key not in pivot_data:
            pivot_data[row_key] = {}
            row_labels[row_key] = [_row_val(r, f) for f in pivot_row_fields]

        pivot_data[row_key].setdefault(col_val, []).append(val)

    # ── Aggregate ──
    def _agg(vals: list[float]) -> float:
        if aggfunc == "count": return float(len(vals))
        if aggfunc == "avg":   return sum(vals) / len(vals) if vals else 0.0
        return sum(vals)  # default: sum

    aggregated = {
        rk: {cv: _agg(vals) for cv, vals in col_dict.items()}
        for rk, col_dict in pivot_data.items()
    }
    row_totals = {rk: sum(aggregated[rk].values()) for rk in aggregated}
    col_totals = {
        cv: sum(aggregated[rk].get(cv, 0.0) for rk in aggregated)
        for cv in all_col_vals
    }

    # ── Sort rows ──
    if sort_by == "row_total":
        sorted_keys = sorted(aggregated, key=lambda rk: row_totals[rk], reverse=(sort_order == "desc"))
    else:
        sorted_keys = sorted(aggregated)

    ws = wb.create_sheet(name)

    # ── Header row ──
    row_label_headers = [COLUMN_LABELS.get(f, f) for f in pivot_row_fields]
    col_headers = list(all_col_vals) + (["Total"] if show_row_totals else [])
    ws.append(row_label_headers + col_headers)
    _style_header(ws, len(row_label_headers) + len(col_headers))

    # ── Data rows ──
    for i, rk in enumerate(sorted_keys, start=2):
        labels = row_labels[rk]
        vals   = [aggregated[rk].get(cv, 0.0) for cv in all_col_vals]
        if show_row_totals:
            vals.append(row_totals[rk])
        ws.append(labels + vals)
        if i % 2 == 0:
            for ci in range(1, len(row_label_headers) + len(col_headers) + 1):
                ws.cell(row=i, column=ci).fill = ALT_FILL

    # ── Column totals row ──
    if show_col_totals:
        total_label = [""] * (len(pivot_row_fields) - 1) + ["Total"]
        col_total_vals = [col_totals.get(cv, 0.0) for cv in all_col_vals]
        if show_row_totals:
            col_total_vals.append(sum(col_total_vals))
        ws.append(total_label + col_total_vals)
        last = len(sorted_keys) + 2
        total_width = len(row_label_headers) + len(col_headers)
        for ci in range(1, total_width + 1):
            ws.cell(row=last, column=ci).font = TOTAL_FONT
            ws.cell(row=last, column=ci).fill = TOTAL_FILL

    # ── Highlight top-N by row total ──
    if highlight_top and show_row_totals and sorted_keys:
        total_col_idx = len(row_label_headers) + len(col_headers)
        top_rows = sorted(
            range(2, len(sorted_keys) + 2),
            key=lambda ri: float(ws.cell(row=ri, column=total_col_idx).value or 0),
            reverse=True,
        )[: int(highlight_top)]
        for ri in top_rows:
            for ci in range(1, len(row_label_headers) + len(col_headers) + 1):
                ws.cell(row=ri, column=ci).fill = HIGHLIGHT_FILL

    # ── Freeze: lock row-label columns + header row ──
    if freeze and pivot_row_fields:
        freeze_col = get_column_letter(len(pivot_row_fields) + 1)
        ws.freeze_panes = f"{freeze_col}2"

    if auto_size:
        _auto_width(ws, len(row_label_headers) + len(col_headers))


def _build_summary_sheet(wb: Workbook, ws_spec: dict, stats: dict) -> None:
    """Build a KPI summary worksheet."""
    name      = ws_spec.get("name", "Summary")[:31]
    freeze    = ws_spec.get("freeze_header", False)
    auto_size = ws_spec.get("auto_size_columns", True)

    ws = wb.create_sheet(name)
    ws.append(["Metric", "Value"])
    _style_header(ws, 2)

    for metric in ws_spec.get("metrics") or []:
        label = metric.get("label", "")
        key   = metric.get("value_key", "")
        value = stats.get(key, "—")
        ws.append([label, value])

    if freeze:
        ws.freeze_panes = "A2"
    if auto_size:
        _auto_width(ws, 2)


def _build_financial_sheet(wb: Workbook, ws_spec: dict, fin_rows: list[dict]) -> None:
    """Build a financial data worksheet."""
    if not fin_rows:
        return
    name      = ws_spec.get("name", "Financial Summary")[:31]
    freeze    = ws_spec.get("freeze_header", True)
    auto_size = ws_spec.get("auto_size_columns", True)

    ws = wb.create_sheet(name)
    fin_headers = [
        "Date", "Route", "Customer ID", "Customer Name",
        "Cash (Rs)", "Credit (Rs)", "Closing Balance (Rs)",
    ]
    ws.append(fin_headers)
    _style_header(ws, len(fin_headers))

    for i, r in enumerate(fin_rows, start=2):
        ws.append([
            r.get("summary_date").isoformat()
            if isinstance(r.get("summary_date"), (date, datetime))
            else str(r.get("summary_date", "")),
            r.get("route_number"),
            r.get("customer_id"),
            r.get("customer_name"),
            float(r.get("cash") or 0),
            float(r.get("credit") or 0),
            float(r.get("closing_balance") or 0),
        ])
        if i % 2 == 0:
            for ci in range(1, len(fin_headers) + 1):
                ws.cell(row=i, column=ci).fill = ALT_FILL

    if freeze:
        ws.freeze_panes = "A2"
    if auto_size:
        _auto_width(ws, len(fin_headers))


def _build_audit_sheet(
    wb: Workbook,
    ws_spec: dict,
    date_from: str,
    date_to: str,
    filters_info: dict,
) -> None:
    """Build a filters / audit trail worksheet. Never includes the instruction text."""
    name      = ws_spec.get("name", "Filters & Audit")[:31]
    auto_size = ws_spec.get("auto_size_columns", True)

    ws = wb.create_sheet(name)
    audit_rows = [
        ["Parameter", "Value"],
        ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Date Range", f"{date_from} \u2014 {date_to}"],
        ["Routes",    filters_info.get("routes", "All routes")],
        ["Branches",  filters_info.get("branches", "All branches")],
        ["Customers", filters_info.get("customers", "All customers")],
    ]
    for row_data in audit_rows:
        ws.append(row_data)
    _style_header(ws, 2)
    if auto_size:
        _auto_width(ws, 2)


# ── main spec-driven entry point ─────────────────────────────────

def generate_excel_from_spec(
    rows: list[dict],
    fin_rows: list[dict],
    spec: dict,
    date_from: str,
    date_to: str,
    req=None,
) -> tuple[bytes | None, str | None]:
    """
    Build an Excel workbook from a ReportSpec dict.

    Returns (bytes, None) on success or (None, error_message) on failure.
    """
    if not rows:
        return None, "No data found for the selected filters."

    # ── Pre-compute stats for summary sheets ──
    total_qty = sum(float(r.get("qty_kg") or 0) for r in rows)
    total_rev = sum(float(r.get("estimated_revenue") or 0) for r in rows)
    unique_customers = len(set(r["customer_id"] for r in rows if r.get("customer_id")))
    unique_skus      = len(set(r["sku_name"]     for r in rows if r.get("sku_name")))
    unique_routes    = sorted(set(r["route_number"] for r in rows if r.get("route_number")))
    total_cash       = sum(float(r.get("cash") or 0)   for r in fin_rows)
    total_credit     = sum(float(r.get("credit") or 0) for r in fin_rows)

    stats = {
        "total_qty":         f"{total_qty:,.1f}",
        "total_rev":         f"{total_rev:,.2f}",
        "unique_customers":  unique_customers,
        "unique_skus":       unique_skus,
        "routes_covered":    ", ".join(f"R{r}" for r in unique_routes),
        "total_cash":        f"{total_cash:,.2f}",
        "total_credit":      f"{total_credit:,.2f}",
        "total_transactions": len(rows),
        "report_period":     f"{date_from} to {date_to}",
    }

    # ── Filters info for audit sheet (never includes instruction text) ──
    filters_info: dict[str, str] = {}
    if req:
        filters_info = {
            "routes":    ", ".join(f"R{r}" for r in req.route_ids) if req.route_ids else "All routes",
            "branches":  ", ".join(req.branches) if req.branches else "All branches",
            "customers": f"{len(req.customer_ids)} selected" if req.customer_ids else "All customers",
        }

    wb = Workbook()
    wb.remove(wb.active)  # discard the auto-created blank sheet

    used_names: set[str] = set()

    for ws_spec in spec.get("worksheets") or []:
        sheet_type = ws_spec.get("type", "tabular")

        # ── Ensure unique sheet name ──
        raw_name = (ws_spec.get("name") or "Sheet")[:31]
        unique_name = raw_name
        suffix = 2
        while unique_name in used_names:
            unique_name = f"{raw_name[:27]}_{suffix}"
            suffix += 1
        ws_spec = dict(ws_spec)   # shallow copy to avoid mutating the original spec
        ws_spec["name"] = unique_name
        used_names.add(unique_name)

        if sheet_type == "tabular":
            _build_tabular_sheet(wb, ws_spec, rows)
        elif sheet_type == "pivot":
            _build_pivot_sheet(wb, ws_spec, rows)
        elif sheet_type == "summary":
            _build_summary_sheet(wb, ws_spec, stats)
        elif sheet_type == "financial":
            _build_financial_sheet(wb, ws_spec, fin_rows)
        elif sheet_type == "audit":
            _build_audit_sheet(wb, ws_spec, date_from, date_to, filters_info)
        # Unknown types are silently skipped

    # ── Guard: ensure at least one sheet exists ──
    if not wb.worksheets:
        ws = wb.create_sheet("Report")
        ws.append(["No data available for the selected filters."])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), None


# ═══════════════════════════════════════════════════════════════════
#  Conversation Excel Export (Single Source of Truth)
#  Converts conversational datasets into standard multi-tab workbooks
# ═══════════════════════════════════════════════════════════════════

def export_conversation_report(
    rows: list[dict],
    columns: list[str] | None = None,
    title: str = "Sales Report",
    filters: dict | None = None,
) -> tuple[bytes, str]:
    """
    Generate a canonical multi-sheet Excel report from conversational memory.
    Uses the project's standard styling, auto-column sizing, and typography.

    Returns:
        tuple[bytes, str]: (xlsx_file_bytes, meaningful_filename)
    """
    if not rows:
        raise ValueError("Cannot generate an Excel report with empty rows.")

    wb = Workbook()

    # Determine columns
    if not columns:
        columns = list(rows[0].keys())

    # ── Generate Meaningful Filename ──
    clean_title = re.sub(r"[^\w\s-]", "", title).strip()
    words = clean_title.split()[:4]
    base_name = "_".join(words) if words else "Sales_Report"
    
    date_suffix = ""
    if filters and filters.get("date_from") and filters.get("date_to"):
        d_from = str(filters["date_from"]).replace("/", "-")
        d_to = str(filters["date_to"]).replace("/", "-")
        date_suffix = f"_{d_from}_to_{d_to}"
    elif any("date" in c.lower() for c in columns):
        # Scan for date bounds in data
        date_vals = [str(r[c]) for r in rows for c in columns if "date" in c.lower() and r.get(c)]
        if date_vals:
            min_d = min(date_vals)[:10].replace("/", "-")
            max_d = max(date_vals)[:10].replace("/", "-")
            date_suffix = f"_{min_d}_to_{max_d}"
    else:
        date_suffix = f"_{datetime.now().strftime('%Y%m%d')}"

    filename = f"{base_name}{date_suffix}.xlsx"

    # ── Tab 1: Executive Summary ──
    ws1 = wb.active
    ws1.title = "Executive Summary"

    # Compute key aggregate metrics
    metrics = [
        ["Report Title", title],
        ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Total Rows Exported", len(rows)],
    ]

    # Look for common numeric columns to summarize
    for col in columns:
        col_lower = col.lower()
        if any(k in col_lower for k in ["qty", "volume", "kg", "revenue", "amount", "total", "cash", "credit"]):
            try:
                numeric_vals = [float(r[col]) for r in rows if r.get(col) is not None]
                if numeric_vals:
                    col_sum = sum(numeric_vals)
                    col_avg = col_sum / len(numeric_vals)
                    label = col.replace("_", " ").title()
                    if "revenue" in col_lower or "amount" in col_lower or "cash" in col_lower or "credit" in col_lower:
                        metrics.append([f"Total {label} (₹)", f"{col_sum:,.2f}"])
                        metrics.append([f"Average {label} (₹)", f"{col_avg:,.2f}"])
                    else:
                        metrics.append([f"Total {label}", f"{col_sum:,.1f}"])
            except (ValueError, TypeError):
                pass

    # Look for categorical entity counts
    for col in columns:
        col_lower = col.lower()
        if any(k in col_lower for k in ["customer", "client", "sku", "product", "route", "branch", "zone"]):
            unique_items = len(set(str(r[col]) for r in rows if r.get(col) is not None))
            label = col.replace("_", " ").title()
            metrics.append([f"Unique {label}s", unique_items])

    ws1.append(["Metric", "Value"])
    for m in metrics:
        ws1.append(m)

    _style_header(ws1, 2)
    _auto_width(ws1, 2)

    # ── Tab 2: Detailed Data ──
    sheet2_name = (title[:25] if title else "Data Results").strip()
    ws2 = wb.create_sheet(sheet2_name)

    # Header labels
    header_labels = [c.replace("_", " ").title() for c in columns]
    ws2.append(header_labels)

    numeric_cols = set()
    currency_cols = set()
    percent_cols = set()
    date_cols = set()

    for col_idx, col in enumerate(columns, start=1):
        col_lower = col.lower()
        if any(k in col_lower for k in ["rev", "rate", "price", "amount", "cash", "credit", "balance", "cost", "₹"]):
            currency_cols.add(col_idx)
        elif any(k in col_lower for k in ["pct", "percent", "share", "%"]):
            percent_cols.add(col_idx)
        elif any(k in col_lower for k in ["qty", "volume", "kg", "count", "nos"]):
            numeric_cols.add(col_idx)
        elif any(k in col_lower for k in ["date", "time", "day"]):
            date_cols.add(col_idx)

    # Populate rows
    for r_idx, r in enumerate(rows, start=2):
        row_vals = []
        for col in columns:
            val = r.get(col)
            if isinstance(val, (date, datetime)):
                row_vals.append(val.isoformat())
            elif isinstance(val, Decimal):
                row_vals.append(float(val))
            elif isinstance(val, (int, float)):
                row_vals.append(val)
            elif val is None:
                row_vals.append("")
            else:
                # Try float conversion if string represents number
                str_v = str(val).replace(",", "").strip()
                if str_v.endswith("%"):
                    try:
                        row_vals.append(float(str_v[:-1]) / 100.0)
                        continue
                    except ValueError:
                        pass
                try:
                    num_v = float(str_v)
                    row_vals.append(int(num_v) if num_v.is_integer() else num_v)
                except ValueError:
                    row_vals.append(str(val))

        ws2.append(row_vals)

        # Alternating zebra stripe
        if r_idx % 2 == 0:
            for c_idx in range(1, len(columns) + 1):
                ws2.cell(row=r_idx, column=c_idx).fill = ALT_FILL

    # Number formatting & alignment
    for r_idx in range(2, len(rows) + 2):
        for c_idx in range(1, len(columns) + 1):
            cell = ws2.cell(row=r_idx, column=c_idx)
            cell.border = BORDER
            cell.font = DATA_FONT

            if c_idx in currency_cols:
                cell.number_format = '₹ #,##0.00'
                cell.alignment = Alignment(horizontal="right")
            elif c_idx in percent_cols:
                cell.number_format = '0.0%'
                cell.alignment = Alignment(horizontal="right")
            elif c_idx in numeric_cols:
                cell.number_format = '#,##0.0' if isinstance(cell.value, float) else '#,##0'
                cell.alignment = Alignment(horizontal="right")
            elif c_idx in date_cols:
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="left")

    # Optional Totals row
    summable_cols = currency_cols | numeric_cols
    if summable_cols and len(rows) > 1:
        total_row_idx = len(rows) + 2
        total_row = ["TOTAL"] + ["" for _ in range(len(columns) - 1)]
        ws2.append(total_row)
        for c_idx in range(1, len(columns) + 1):
            cell = ws2.cell(row=total_row_idx, column=c_idx)
            cell.fill = TOTAL_FILL
            cell.font = TOTAL_FONT
            cell.border = BORDER
            if c_idx in summable_cols:
                col_letter = get_column_letter(c_idx)
                cell.value = f"=SUM({col_letter}2:{col_letter}{total_row_idx - 1})"
                if c_idx in currency_cols:
                    cell.number_format = '₹ #,##0.00'
                else:
                    cell.number_format = '#,##0.0'
                cell.alignment = Alignment(horizontal="right")

    _style_header(ws2, len(columns))
    _auto_width(ws2, len(columns))
    ws2.views.sheetView[0].showGridLines = True

    # ── Tab 3: Filters & Audit ──
    ws3 = wb.create_sheet("Filters & Audit")
    audit_data = [
        ["Parameter", "Value"],
        ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Report Focus", title],
        ["Total Data Points", len(rows)],
        ["Source", "Conversational AI Analysis Memory"],
    ]
    if filters:
        for k, v in filters.items():
            if v is not None:
                audit_data.append([k.replace("_", " ").title(), str(v)])

    for row_data in audit_data:
        ws3.append(row_data)

    _style_header(ws3, 2)
    _auto_width(ws3, 2)
    ws3.views.sheetView[0].showGridLines = True

    # Write output buffer
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), filename

