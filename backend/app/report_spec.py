"""
Horeca Sales Intelligence — AI Report Specification Generator.

Calls Qwen3 32B via OpenRouter to interpret the natural language instruction
from the Description/Notes field and produce a structured ReportSpec JSON
that drives the spec-driven Excel builder in reports.py.
"""
import json
import os
import re
import traceback
from datetime import date, datetime
from decimal import Decimal

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-32b")


# ─────────────── helpers ───────────────

def _json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def _extract_json(text: str) -> dict:
    """Extract JSON object from LLM response, stripping think-tags and code fences."""
    if not text or not isinstance(text, str):
        raise ValueError("Empty LLM response")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    raise ValueError(f"No JSON object found in response: {text[:300]}")


# ─────────────── system prompt ───────────────

SPEC_SYSTEM_PROMPT = """\
You are an expert Excel report designer for a Horeca (Hotel/Restaurant/Cafe) coffee and tea
distribution company. Your task is to design an Excel workbook specification from a natural
language instruction and available data context.

## AVAILABLE DATA COLUMNS (sales rows)
  sale_date          - ISO date string
  route_number       - int (1-7)
  customer_id        - string  e.g. "A132"
  customer_name      - string
  sku_name           - string (product name)
  qty_kg             - float  (quantity in kilograms)
  category           - string e.g. "Coffee", "Tea"
  approved_inclusive - float  (rate per KG incl. GST)
  estimated_revenue  - float  (qty_kg x rate)

## AVAILABLE DATA COLUMNS (financial rows)
  summary_date      - ISO date string
  route_number      - int
  customer_id       - string
  customer_name     - string
  cash              - float
  credit            - float
  closing_balance   - float

## AVAILABLE SHEET TYPES
  "tabular"   - Flat table. Use for most instructions.
  "pivot"     - Cross-tab. Use when user says pivot, rows vs columns, SKU in columns, etc.
  "summary"   - KPI metrics panel. Useful as a first sheet.
  "financial" - Renders financial rows (cash, credit, balances).
  "audit"     - Auto-generated filters/audit sheet. Always add this as the LAST sheet.

## JSON SPEC FORMAT
Return ONLY a valid JSON object (no markdown, no explanation, no code fences):

{
  "worksheets": [
    {
      "name": "<max 31 chars, unique>",
      "type": "tabular",
      "columns": ["sale_date","route_number","customer_id","customer_name",
                  "sku_name","qty_kg","category","approved_inclusive","estimated_revenue"],
      "filter_route": null,
      "sort_by": "estimated_revenue",
      "sort_order": "desc",
      "top_n": null,
      "highlight_top_n": null,
      "show_totals_row": true,
      "freeze_header": true,
      "auto_size_columns": true,
      "conditional_formats": [],
      "charts": []
    }
  ]
}

Pivot sheet example:
{
  "name": "Pivot",
  "type": "pivot",
  "pivot_rows": ["customer_id","customer_name"],
  "pivot_columns": "sku_name",
  "pivot_values": "qty_kg",
  "pivot_aggfunc": "sum",
  "sort_by": "row_total",
  "sort_order": "desc",
  "highlight_top_n": null,
  "show_row_totals": true,
  "show_col_totals": true,
  "freeze_header": true,
  "auto_size_columns": true,
  "conditional_formats": [],
  "charts": []
}

Summary sheet example:
{
  "name": "Executive Summary",
  "type": "summary",
  "metrics": [
    {"label":"Total Volume (KG)","value_key":"total_qty"},
    {"label":"Estimated Revenue","value_key":"total_rev"},
    {"label":"Active Customers","value_key":"unique_customers"},
    {"label":"Unique SKUs","value_key":"unique_skus"},
    {"label":"Routes Covered","value_key":"routes_covered"},
    {"label":"Total Cash","value_key":"total_cash"},
    {"label":"Total Credit","value_key":"total_credit"},
    {"label":"Total Transactions","value_key":"total_transactions"}
  ],
  "freeze_header": false,
  "auto_size_columns": true
}

Chart object (inside "charts" array of any tabular/pivot sheet):
{
  "type": "bar",
  "title": "Revenue by Route",
  "x_column": "route_number",
  "y_column": "estimated_revenue",
  "position": "right_of_table"
}
Chart type: "bar" (horizontal) | "column" (vertical) | "line" | "pie"
Position:   "right_of_table"   | "below_table"

Conditional format object (inside "conditional_formats" array):
{
  "column": "estimated_revenue",
  "rule": "top_n",
  "n": 10,
  "fill_color": "FFFF00"
}
Rule: "top_n" | "above_avg"

## DESIGN RULES
1. Sheet names must be <= 31 chars and unique across the workbook.
2. "One sheet per route" means 7 tabular sheets, filter_route = 1 through 7.
3. "Pivot / SKU in columns" means type = "pivot" with appropriate fields.
4. "Highlight top N" means use highlight_top_n or conditional_formats.
5. columns[] must only contain valid field names listed in the sales rows section above.
6. Financial data (cash, credit, balance) requires type = "financial".
7. Always include freeze_header: true and auto_size_columns: true unless told otherwise.
8. Always append {"name":"Filters & Audit","type":"audit","freeze_header":false,"auto_size_columns":true} as the LAST worksheet.
9. DO NOT include the user instruction text anywhere in the spec.
10. Output ONLY the JSON object. Nothing else.
"""


# ─────────────── default spec ───────────────

def _default_spec() -> dict:
    """
    Return the standard 4-tab report spec used when no instruction is given
    or when the LLM call fails.
    """
    return {
        "worksheets": [
            {
                "name": "Executive Summary",
                "type": "summary",
                "metrics": [
                    {"label": "Total Volume (KG)",     "value_key": "total_qty"},
                    {"label": "Estimated Revenue (Rs)", "value_key": "total_rev"},
                    {"label": "Active Customers",       "value_key": "unique_customers"},
                    {"label": "Unique SKUs",             "value_key": "unique_skus"},
                    {"label": "Routes Covered",          "value_key": "routes_covered"},
                    {"label": "Total Cash (Rs)",          "value_key": "total_cash"},
                    {"label": "Total Credit (Rs)",        "value_key": "total_credit"},
                    {"label": "Total Transactions",      "value_key": "total_transactions"},
                ],
                "freeze_header": False,
                "auto_size_columns": True,
            },
            {
                "name": "Sales Breakdown",
                "type": "tabular",
                "columns": [
                    "sale_date", "route_number", "customer_id", "customer_name",
                    "sku_name", "qty_kg", "category", "approved_inclusive", "estimated_revenue",
                ],
                "filter_route": None,
                "sort_by": "sale_date",
                "sort_order": "asc",
                "top_n": None,
                "highlight_top_n": None,
                "show_totals_row": False,
                "freeze_header": True,
                "auto_size_columns": True,
                "conditional_formats": [],
                "charts": [],
            },
            {
                "name": "Financial Summary",
                "type": "financial",
                "freeze_header": True,
                "auto_size_columns": True,
            },
            {
                "name": "Filters & Audit",
                "type": "audit",
                "freeze_header": False,
                "auto_size_columns": True,
            },
        ]
    }


# ─────────────── OpenRouter call ───────────────

async def _call_openrouter(messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Horeca Sales Intelligence",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ─────────────── public API ───────────────

async def build_spec(rows: list[dict], fin_rows: list[dict], req) -> dict:
    """
    Call the LLM to interpret req.notes and return a validated ReportSpec dict.

    Parameters
    ----------
    rows     : Sales data rows already fetched from the database.
    fin_rows : Financial data rows already fetched from the database.
    req      : The ReportRequest Pydantic model instance.

    Returns
    -------
    dict -- a validated ReportSpec, or _default_spec() on any failure.
    """
    if not OPENROUTER_API_KEY:
        print("[report_spec] No OPENROUTER_API_KEY set -- using default spec.")
        return _default_spec()

    try:
        # ── Summary statistics ──
        total_qty = sum(float(r.get("qty_kg") or 0) for r in rows)
        total_rev = sum(float(r.get("estimated_revenue") or 0) for r in rows)
        unique_customers = len(set(r["customer_id"] for r in rows if r.get("customer_id")))
        unique_skus = len(set(r["sku_name"] for r in rows if r.get("sku_name")))
        unique_routes = sorted(set(r["route_number"] for r in rows if r.get("route_number")))
        all_sku_names = sorted(set(r.get("sku_name", "") for r in rows if r.get("sku_name")))

        route_desc = ", ".join(
            f"Route {r}" for r in (req.route_ids or range(1, 8))
        )
        branch_desc = ", ".join(req.branches) if req.branches else "All"
        customer_desc = (
            f"{len(req.customer_ids)} specific customers"
            if req.customer_ids else "All customers"
        )

        filters_section = (
            f"- Date range: {req.date_from} to {req.date_to}\n"
            f"- Routes: {route_desc}\n"
            f"- Branches: {branch_desc}\n"
            f"- Customers: {customer_desc}"
        )
        stats_section = (
            f"- Total rows: {len(rows)}\n"
            f"- Total volume (KG): {total_qty:,.1f}\n"
            f"- Estimated revenue: {total_rev:,.2f}\n"
            f"- Unique customers: {unique_customers}\n"
            f"- Unique SKUs: {unique_skus}\n"
            f"- SKU names: {', '.join(all_sku_names[:20])}\n"
            f"- Routes present in data: {', '.join(f'Route {r}' for r in unique_routes)}"
        )

        sample_rows = json.dumps(rows[:15], default=_json_serial, indent=2)

        user_content = (
            f"APPLIED FILTERS:\n{filters_section}\n\n"
            f"DATA SUMMARY:\n{stats_section}\n\n"
            f"SAMPLE DATA (first 15 of {len(rows)} total rows):\n{sample_rows}\n\n"
            f"USER INSTRUCTION:\n{req.notes}\n\n"
            "Design the Excel workbook spec now. Return ONLY the JSON object."
        )

        messages = [
            {"role": "system", "content": SPEC_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        raw = await _call_openrouter(messages)
        spec = _extract_json(raw)

        # ── Validate basic structure ──
        if not isinstance(spec, dict) or "worksheets" not in spec:
            raise ValueError("LLM spec missing 'worksheets' key")
        if not isinstance(spec["worksheets"], list) or not spec["worksheets"]:
            raise ValueError("LLM spec has empty 'worksheets' list")

        # ── Ensure audit sheet is always the last sheet ──
        types_present = [ws.get("type") for ws in spec["worksheets"]]
        if "audit" not in types_present:
            spec["worksheets"].append({
                "name": "Filters & Audit",
                "type": "audit",
                "freeze_header": False,
                "auto_size_columns": True,
            })

        print(f"[report_spec] Spec generated: {len(spec['worksheets'])} worksheets "
              f"({[ws.get('name','?') for ws in spec['worksheets']]})")
        return spec

    except Exception:
        traceback.print_exc()
        print("[report_spec] LLM spec generation failed -- falling back to default spec.")
        return _default_spec()
