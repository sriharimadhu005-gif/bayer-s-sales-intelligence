"""
Horeca Sales Intelligence — Chat engine powered by Qwen3 32B via OpenRouter.

Workflow:
1. User sends natural language question.
2. System prompt provides full database schema + business rules.
3. Qwen3 32B returns a JSON plan containing SQL + response metadata.
4. Backend executes the SQL read-only and feeds results back to Qwen3 32B.
5. Qwen3 32B synthesises: answer_text, table, chart, report_prefill.
"""
import json
import os
import re
import uuid
import traceback
from datetime import date, datetime
from decimal import Decimal

import httpx
from dotenv import load_dotenv

from . import db

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-32b")

# ---------- helpers ----------

def _json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def _rows_to_table(rows: list[dict]) -> dict | None:
    """Convert list[dict] to { columns: [...], rows: [[...], ...] }."""
    if not rows:
        return None
    columns = list(rows[0].keys())
    table_rows = []
    for r in rows:
        table_rows.append([
            r[c].isoformat() if isinstance(r[c], (date, datetime))
            else float(r[c]) if isinstance(r[c], Decimal)
            else r[c]
            for c in columns
        ])
    return {"columns": columns, "rows": table_rows}


# ---------- system prompt ----------

SYSTEM_PROMPT = """You are the Horeca Sales Intelligence Assistant for a coffee/tea distribution company.
You answer questions about sales data stored in a PostgreSQL database.

## DATABASE SCHEMA

### Tables
1. **customers** (customer_id VARCHAR PK, name, phone, address, bill_transfer BOOL, credit_limit NUMERIC, credit_balance NUMERIC, route_number INT)
   - 2,871 customers across routes 1-7.

2. **daily_sales** (id BIGSERIAL PK, sale_date DATE, route_number INT, customer_id VARCHAR FK, customer_name, sku_name, qty_kg NUMERIC)
   - 7,730 rows. Date range: 2026-03-31 to 2026-04-15. Quantities in KG.
   - SKU names may be abbreviations like 'bs', 'bc', 'spt', 'kt royal', 'pure', etc.

3. **rate_cards** (id BIGSERIAL PK, code, zone, sub_group, customer_name, customer_id FK, category, sku_name, uom, approved_rate, gst_percent, approved_inclusive, std_rate, diff)
   - 4,050 rows. Categories: Coffee, Tea, Pure Coffee, Badam Powder, INSTANT, Filter, Accessories, Decoction, Puliogare, Rava Idli, Cups, etc.

4. **daily_route_summary** (id, summary_date DATE, route_number, customer_id FK, customer_name, cash NUMERIC, credit NUMERIC, closing_balance NUMERIC)
   - 5,761 rows. Cash/Credit collections per customer per day.

5. **daily_route_sku_details** (id, summary_date DATE, route_number, customer_id FK, customer_name, sku_name, qty_kg NUMERIC)
   - 8,250 rows. Per-customer per-SKU breakdown from route sheets.

6. **customer_equipment** (id, log_date DATE, route_number, customer_id FK, customer_name, item_name, qty NUMERIC)
   - 37 rows. Equipment issued to customers (coffee machines, brass filters, etc.).

7. **sku_alias_map** (id, sales_sku_name, rate_card_sku_name, notes)
   - Maps abbreviated sales names to canonical rate card names.

### Analytical Views
- **vw_customer_sales_analytics**: Joins daily_sales + customers + rate_cards. Columns: sale_date, route_number, customer_id, customer_name, phone, address, credit_limit, credit_balance, sku_name, qty_kg, tally_code, category, approved_rate, gst_percent, approved_inclusive, std_rate, estimated_revenue.
- **vw_daily_financial_summary**: Joins daily_route_summary + customers. Columns: summary_date, route_number, customer_id, customer_name, phone, credit_limit, credit_balance, cash, credit, closing_balance.
- **vw_route_sku_breakdown**: Joins daily_route_sku_details + customers + rate_cards. Columns: summary_date, route_number, customer_id, customer_name, sku_name, qty_kg, category, approved_inclusive, estimated_revenue.
- **vw_customer_equipment_ledger**: Joins customer_equipment + customers.

### Route Info
Routes 1 through 7, each serving different areas. Customer count per route: R1=364, R2=411, R3=561, R4=475, R5=302, R6=519, R7=239.

### Business Rules
- Revenue = qty_kg * approved_inclusive (or std_rate as fallback). Many SKU abbreviations in daily_sales do NOT join to rate_cards (tally_code=null, estimated_revenue=0.00). Use daily_sales.qty_kg as the primary metric.
- For financial queries (cash, credit, balances), use daily_route_summary or vw_daily_financial_summary.
- Customer IDs are alphanumeric strings like 'A132', 'C1666', 'B428'.

## YOUR TASK

When the user asks a question:
1. Think about what data is needed.
2. Write a PostgreSQL query to answer it. Use ONLY SELECT statements. Never modify data.
3. Return your response as a JSON object with this EXACT structure (no markdown, no code fences):

{
  "thinking": "Brief explanation of your approach",
  "sql": "SELECT ... (the SQL query to execute)",
  "answer_template": "A template for the answer using {result} placeholder where the query results will be inserted",
  "chart_type": null or "bar" or "line" or "pie",
  "report_eligible": true or false,
  "report_prefill": null or { "date_from": "DD/MM/YYYY", "date_to": "DD/MM/YYYY", "route_ids": [...], "branches": [...], "days": null }
}

IMPORTANT RULES:
- Always use LOWER() for text comparisons.
- Limit results to 50 rows max unless the user wants everything.
- Use the analytical views when they provide what's needed; use base tables for simpler queries.
- For "top" or "best" questions, ORDER BY DESC and LIMIT appropriately.
- Dates in the database are between 2026-03-31 and 2026-04-15. Use these as defaults if the user doesn't specify dates.
- For report_prefill dates, use DD/MM/YYYY format.
- Output ONLY the JSON object. No text before or after.
"""

SYNTHESIS_PROMPT = """You are the Horeca Sales Intelligence Assistant. The user asked a question and the database returned results.

ORIGINAL QUESTION: {question}

SQL EXECUTED: {sql}

QUERY RESULTS (as JSON):
{results}

Based on these EXACT results, write a clear, concise answer. Include specific numbers from the results.
If the results are empty, say you found no data matching the query.

Return your response as a JSON object with this EXACT structure (no markdown, no code fences):
{{
  "answer_text": "Your natural language answer with specific numbers",
  "table": {{"columns": ["col1", "col2"], "rows": [["val1", "val2"]]}} or null if not useful to show as table,
  "chart": {{"type": "bar|line|pie", "data": {{"labels": [...], "values": [...]}}}} or null if not chart-worthy,
  "report_eligible": true or false,
  "report_prefill": null or {{"date_from": "DD/MM/YYYY", "date_to": "DD/MM/YYYY", "route_ids": [...], "branches": [...], "days": null}}
}}

RULES:
- answer_text must cite actual numbers from the results. Never invent numbers.
- Include a table if the results have 2+ meaningful rows.
- Include a chart if comparing quantities/values across categories (top customers, route comparison, etc.).
- Set report_eligible to true if the question maps cleanly to date range + route + product filters.
- For report_prefill, use the date range 31/03/2026 to 15/04/2026 as default.
- Output ONLY the JSON object. No text before or after.
"""


# ---------- OpenRouter API call ----------

async def _call_openrouter(messages: list[dict], temperature: float = 0.2) -> str:
    """Call OpenRouter chat completion API and return the assistant message content."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Horeca Sales Intelligence",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences and thinking tags."""
    if not text or not isinstance(text, str):
        raise ValueError(f"No valid text received from LLM response: {type(text)}")
    # Remove <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Try to find JSON in code fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))
    # Try to find raw JSON object
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))
    raise ValueError(f"No JSON found in LLM response: {text[:200]}")


# ---------- conversation store (in-memory for eval) ----------

_conversations: dict[str, list[dict]] = {}


# ---------- deterministic fallback engine ----------

def _deterministic_fallback(message: str, conv_id: str) -> dict:
    """
    Deterministic query engine when OpenRouter is unavailable or API key is missing.
    Analyzes intent via pattern matching and executes direct SQL on PostgreSQL.
    """
    msg = message.lower()

    try:
        # 1. Customer queries
        if any(k in msg for k in ["customer", "client", "buyer", "account"]):
            rows = db.query("""
                SELECT customer_name, route_number, ROUND(SUM(qty_kg)::numeric, 1) as total_kg
                FROM daily_sales
                GROUP BY customer_name, route_number
                ORDER BY total_kg DESC
                LIMIT 10;
            """)
            if rows:
                top = rows[0]
                table = {
                    "columns": ["Customer", "Route", "Total Volume (kg)"],
                    "rows": [[r["customer_name"], f"Route {r['route_number']}", float(r["total_kg"])] for r in rows]
                }
                chart = {
                    "type": "bar",
                    "data": {
                        "labels": [r["customer_name"][:20] for r in rows[:5]],
                        "values": [float(r["total_kg"]) for r in rows[:5]]
                    }
                }
                answer = f"The top customer by sales volume is **{top['customer_name']}** (Route {top['route_number']}) with **{top['total_kg']} kg** sold. Here are the top 10 customers across all routes."
                return {
                    "conversation_id": conv_id,
                    "answer_text": answer,
                    "table": table,
                    "chart": chart,
                    "report_eligible": True,
                    "report_prefill": {
                        "date_from": "31/03/2026",
                        "date_to": "15/04/2026",
                        "route_ids": [top["route_number"]],
                        "branches": None,
                        "days": None
                    }
                }

        # 2. Coffee / Tea / Branch queries
        if any(k in msg for k in ["tea", "coffee", "branch", "category", "product"]):
            rows = db.query("""
                SELECT
                    CASE
                        WHEN LOWER(sku_name) LIKE '%tea%' OR LOWER(sku_name) LIKE '%chai%' THEN 'Tea'
                        WHEN LOWER(sku_name) LIKE '%coffee%' OR LOWER(sku_name) IN ('bs', 'bc', 'spt', 'pure') THEN 'Coffee'
                        ELSE 'Others'
                    END as branch,
                    ROUND(SUM(qty_kg)::numeric, 1) as total_kg
                FROM daily_sales
                GROUP BY 1
                ORDER BY total_kg DESC;
            """)
            if rows:
                table = {
                    "columns": ["Branch", "Total Volume (kg)"],
                    "rows": [[r["branch"], float(r["total_kg"])] for r in rows]
                }
                chart = {
                    "type": "pie",
                    "data": {
                        "labels": [r["branch"] for r in rows],
                        "values": [float(r["total_kg"]) for r in rows]
                    }
                }
                breakdown = ", ".join([f"**{r['branch']}** ({r['total_kg']} kg)" for r in rows])
                answer = f"Sales breakdown by product category: {breakdown}."
                return {
                    "conversation_id": conv_id,
                    "answer_text": answer,
                    "table": table,
                    "chart": chart,
                    "report_eligible": True,
                    "report_prefill": {
                        "date_from": "31/03/2026",
                        "date_to": "15/04/2026",
                        "route_ids": [1, 2, 3, 4, 5, 6, 7],
                        "branches": ["coffee", "tea"],
                        "days": None
                    }
                }

        # 3. Route queries (default or explicit route questions)
        rows = db.query("""
            SELECT route_number, ROUND(SUM(qty_kg)::numeric, 1) as total_kg
            FROM daily_sales
            GROUP BY route_number
            ORDER BY total_kg DESC;
        """)
        if rows:
            top = rows[0]
            total_all = sum(float(r["total_kg"]) for r in rows)
            table = {
                "columns": ["Route", "Total Volume (kg)", "Share"],
                "rows": [[f"Route {r['route_number']}", float(r['total_kg']), f"{(float(r['total_kg'])/total_all*100):.1f}%"] for r in rows]
            }
            chart = {
                "type": "bar",
                "data": {
                    "labels": [f"Route {r['route_number']}" for r in rows],
                    "values": [float(r["total_kg"]) for r in rows]
                }
            }
            answer = f"**Route {top['route_number']}** had the highest total sales volume with **{top['total_kg']} kg** (representing {(float(top['total_kg'])/total_all*100):.1f}% of all sales). Total sales across all routes: **{total_all:.1f} kg**."
            return {
                "conversation_id": conv_id,
                "answer_text": answer,
                "table": table,
                "chart": chart,
                "report_eligible": True,
                "report_prefill": {
                    "date_from": "31/03/2026",
                    "date_to": "15/04/2026",
                    "route_ids": [top["route_number"]],
                    "branches": None,
                    "days": None
                }
            }

    except Exception as db_err:
        traceback.print_exc()

    return {
        "conversation_id": conv_id,
        "answer_text": "I could not process this request right now. You can ask about top routes, coffee sales, or top customers.",
        "table": None,
        "chart": None,
        "report_eligible": False,
        "report_prefill": None,
    }


# ---------- main chat function ----------

async def chat(message: str, conversation_id: str | None) -> dict:
    """
    Process a chat message:
    1. If OPENROUTER_API_KEY is missing, use deterministic SQL fallback.
    2. Otherwise send to Qwen3 32B to generate SQL.
    3. Execute SQL against PostgreSQL database.
    4. Send results back to Qwen3 32B for synthesis.
    5. Fallback to deterministic engine if OpenRouter fails.
    """
    conv_id = conversation_id or str(uuid.uuid4())

    # Initialise conversation history if new
    if conv_id not in _conversations:
        _conversations[conv_id] = []

    # If no OpenRouter key is set, use deterministic fallback
    if not OPENROUTER_API_KEY:
        return _deterministic_fallback(message, conv_id)

    try:
        # STEP 1: Generate SQL
        step1_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *_conversations[conv_id][-6:],  # last 3 exchanges for context
            {"role": "user", "content": message},
        ]

        raw_plan = await _call_openrouter(step1_messages, temperature=0.1)
        plan = _extract_json(raw_plan)

        sql = plan.get("sql", "")
        if not sql:
            return {
                "conversation_id": conv_id,
                "answer_text": plan.get("answer_template", "I couldn't understand that question. Could you rephrase it?"),
                "table": None,
                "chart": None,
                "report_eligible": False,
                "report_prefill": None,
            }

        # Validate: only SELECT allowed
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
            return {
                "conversation_id": conv_id,
                "answer_text": "I can only run read-only queries on the sales database. Could you rephrase your question?",
                "table": None,
                "chart": None,
                "report_eligible": False,
                "report_prefill": None,
            }

        # STEP 2: Execute SQL
        try:
            rows = db.query(sql)
        except Exception as e:
            # SQL error — try deterministic fallback
            fallback_res = _deterministic_fallback(message, conv_id)
            if fallback_res.get("table") or fallback_res.get("chart"):
                return fallback_res
            return {
                "conversation_id": conv_id,
                "answer_text": f"I generated a query but it encountered an error: {str(e)[:200]}. Could you try rephrasing your question?",
                "table": None,
                "chart": None,
                "report_eligible": False,
                "report_prefill": None,
            }

        # STEP 3: Synthesise answer
        results_json = json.dumps(rows[:50], default=_json_serial, indent=2)

        step2_messages = [
            {"role": "system", "content": SYNTHESIS_PROMPT.format(
                question=message,
                sql=sql,
                results=results_json,
            )},
            {"role": "user", "content": "Generate the response JSON."},
        ]

        raw_synthesis = await _call_openrouter(step2_messages, temperature=0.1)
        synthesis = _extract_json(raw_synthesis)

        # Store in conversation history
        _conversations[conv_id].append({"role": "user", "content": message})
        _conversations[conv_id].append({"role": "assistant", "content": synthesis.get("answer_text", "")})

        return {
            "conversation_id": conv_id,
            "answer_text": synthesis.get("answer_text", "I found data but couldn't summarise it properly."),
            "table": synthesis.get("table"),
            "chart": synthesis.get("chart"),
            "report_eligible": synthesis.get("report_eligible", False),
            "report_prefill": synthesis.get("report_prefill"),
        }

    except httpx.HTTPStatusError as e:
        # On HTTP error from OpenRouter (quota, rate limit, outage), use deterministic fallback
        return _deterministic_fallback(message, conv_id)
    except Exception as e:
        traceback.print_exc()
        return _deterministic_fallback(message, conv_id)
