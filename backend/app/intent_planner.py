"""
Horeca Sales Intelligence — Reusable Intent-Aware Query Planning & Comparison Engine

Pipeline Stages:
1. Understand the user's intent (Comparison/Ranking, Single Lookup, Aggregation, Reporting).
2. Resolve product/customer/route references (including multi-variant candidate expansion).
3. Determine relevant metric (units, revenue, volume_kg, or both) and time period.
4. Retrieve and validate data from PostgreSQL (parameterized, read-only SQL).
5. Calculate comparisons, rankings, totals, and winners deterministically.
6. Generate natural-language answer supported by actual results, with structured table & chart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from . import db
from . import date_utils
from . import memory as mem


class IntentType(str, Enum):
    COMPARISON_RANKING = "comparison_ranking"
    LOOKUP_SINGLE = "lookup_single"
    AGGREGATION_TREND = "aggregation_trend"
    REPORT_GENERATION = "report_generation"
    GENERAL_QUERY = "general_query"


class MetricType(str, Enum):
    BOTH = "both"         # Default for "best sales", "performed better", etc.
    UNITS = "units"       # Packs / units sold
    REVENUE = "revenue"   # Sales revenue in INR / Rs.
    VOLUME = "volume_kg"  # Kilograms / volume sold


# ═══════════════════════════════════════════════════════════════════════
# STAGE 1: INTENT UNDERSTANDING
# ═══════════════════════════════════════════════════════════════════════

# Patterns indicating comparison, ranking, superlative, or variant performance inquiry
COMPARISON_PATTERNS = [
    # "which bc did best sales", "which variant did highest sales", "which one sold best"
    r"\bwhich\s+[\w\s\-\(\)\/\&]{1,40}?\s*(?:did|had|has|generated|made|achieved)?\s*(?:the\s+)?(?:best|highest|top|most|better|greater)\s+sales\b",
    # "which bc variant sold the most", "which variant sold the most units", "which product sold most"
    r"\bwhich\s+[\w\s\-\(\)\/\&]{1,40}?\s*(?:variant|sku|product|one|pack)?\s+sold\s+(?:the\s+)?(?:most|more|highest|greatest|least|lowest)\b",
    # "which bc variant generated the highest revenue"
    r"\bwhich\s+[\w\s\-\(\)\/\&]{1,40}?\s*(?:variant|sku|product|one|pack)?\s+(?:generated|produced|earned|had)\s+(?:the\s+)?(?:highest|most|top|best|greatest)\s+(?:revenue|sales|amount|turnover)\b",
    # "which variant performed better", "which product did best", "which one did best"
    r"\bwhich\s+(?:variant|sku|product|item|one|pack)\s+(?:performed|did)\s+(?:better|best|well|worse)\b",
    # "which one sold the most"
    r"\bwhich\s+one\s+sold\s+(?:the\s+)?(?:most|more)\b",
    # "best sales" standalone or phrase: "did best sales", "best sales between"
    r"\b(?:did|had|has|with|for)\s+(?:the\s+)?best\s+sales\b",
    r"\bbest\s+sales\b",
    # "compare X vs Y", "compare X and Y", "X vs Y"
    r"\bcompare\s+[\w\s\-\(\)\/\&]{2,40}\s+(?:vs|versus|and|with)\s+[\w\s\-\(\)\/\&]{2,40}\b",
    r"\b[\w\s\-\(\)\/\&]{2,30}\s+(?:vs|versus)\s+[\w\s\-\(\)\/\&]{2,30}\b",
    # "rank these variants by sales", "rank variants by revenue"
    r"\brank\s+(?:these|the|all)?\s*(?:variants|products|skus)?\s*(?:by\s+[\w\s]+)?\b",
    r"\branking\s+(?:of|for)?\s*(?:variants|products|skus)\b",
    # "top-selling products", "best-selling variants", "top selling sku"
    r"\b(?:top|best)\s*-\s*selling\s+(?:variants?|products?|skus?)\b",
    r"\b(?:top|best)\s+selling\s+(?:variants?|products?|skus?)\b",
    # "which SKU generated the highest revenue"
    r"\bwhich\s+sku\s+generated\s+(?:the\s+)?highest\s+revenue\b",
    # "how much did BC sell last month" (performance analysis across variants over time)
    r"\bhow\s+much\s+did\s+([a-zA-Z0-9\s\-]{2,25})\s+sell\b",
]

# Words that strongly denote single-property lookup rather than performance comparison
LOOKUP_PROPERTY_WORDS = [
    "price", "rate", "std rate", "standard rate", "approved rate", "gst",
    "phone", "address", "route number", "location", "tally id", "tally code",
    "credit limit", "balance", "closing balance", "ledger", "contact"
]


def is_comparison_intent(message: str) -> bool:
    """
    Determine if the user query contains comparison, ranking, superlative,
    or multi-variant performance analysis intent.
    """
    msg = message.lower().strip()
    msg_clean = re.sub(r"[^\w\s\-\/\&]", " ", msg)
    msg_clean = re.sub(r"\s+", " ", msg_clean).strip()

    # If the user is explicitly asking for a single static property like price/phone/address
    # without comparison words (compare, vs, which.*did best, rank), it is a lookup
    has_lookup_word = any(re.search(rf"\b{re.escape(w)}\b", msg_clean) for w in LOOKUP_PROPERTY_WORDS)
    has_explicit_compare = any(w in msg_clean for w in ["compare", " vs ", " versus ", "which", "rank", "better", "best"])

    if has_lookup_word and not has_explicit_compare:
        return False

    for pat in COMPARISON_PATTERNS:
        if re.search(pat, msg_clean):
            return True

    return False


def detect_comparison_metric(message: str) -> MetricType:
    """
    Determine the requested comparison metric:
    - UNITS: explicit units, packs, boxes, quantity requested
    - REVENUE: explicit revenue, rupees, turnover, sales amount requested
    - VOLUME: explicit volume, kg, weight requested
    - BOTH: when user asks "best sales", "sold the most", "compare", or unspecified
    """
    msg = message.lower().strip()

    has_units = bool(re.search(r"\b(?:units?|packs?|boxes|box|pieces?|qty|quantity)\b", msg))
    has_revenue = bool(re.search(r"\b(?:revenue|amount|rupees|rs|inr|turnover|sales\s+value|value)\b", msg))
    has_volume = bool(re.search(r"\b(?:volume|kg|kgs|kilo|kilos|weight)\b", msg))

    # If user specifies only units:
    if has_units and not has_revenue and not has_volume:
        return MetricType.UNITS

    # If user specifies only revenue:
    if has_revenue and not has_units and not has_volume:
        return MetricType.REVENUE

    # If user specifies only volume:
    if has_volume and not has_units and not has_revenue:
        return MetricType.VOLUME

    # If user asks "best sales", "performed better", "sold the most", "compare", or both/neither
    return MetricType.BOTH


def extract_explicit_variants(message: str) -> list[str]:
    """
    Extract explicitly mentioned variant names from phrases like:
    "compare BC-200 and BC-500", "BC-200 vs BC-500", "Coffee-Brownie Special-200 vs Coffee-Brownie Special-500".
    """
    msg = message.strip()
    explicit = []

    # Pattern: Compare X and Y, or X vs Y
    vs_match = re.search(
        r"(?:compare\s+)?([A-Za-z0-9\-\(\)\s]{2,35})\s+(?:vs|versus|and)\s+([A-Za-z0-9\-\(\)\s]{2,35})",
        msg,
        re.IGNORECASE
    )
    if vs_match:
        cand1 = vs_match.group(1).strip()
        cand2 = vs_match.group(2).strip()
        # Clean trailing question marks or punctuation
        cand1 = re.sub(r"[^\w\-\(\)]+$", "", cand1).strip()
        cand2 = re.sub(r"[^\w\-\(\)]+$", "", cand2).strip()
        # Ensure they look like variants (e.g. contain numbers like 200, 500, or product codes)
        if cand1 and cand2:
            explicit.extend([cand1, cand2])

    return explicit


# ═══════════════════════════════════════════════════════════════════════
# STAGE 2: PRODUCT & VARIANT ENTITY RESOLUTION
# ═══════════════════════════════════════════════════════════════════════

def parse_pack_size_grams(sku_name: str) -> int | None:
    """
    Extract pack size in grams from SKU name:
    - 'Coffee-Brownie Special-200' -> 200
    - 'Coffee-Cafe Supreme-500' -> 500
    - 'Tea-KT Royal-5000' -> 5000
    - 'Tea-Bayars Tea Special-250' -> 250
    - 'Pure Coffee-Chalukya Samrat Beans-1000' -> 1000
    - 'Delight - 1000ml' -> 1000
    """
    m = re.search(r"[- ](\d{2,4})(?:g|gm|gms|ml)?(?:\([^\)]*\))?$", sku_name.strip(), re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Also check parenthesized number like '(200)' or '(500)'
    m2 = re.search(r"\((\d{2,4})\)", sku_name.strip())
    if m2:
        return int(m2.group(1))

    return None


def resolve_product_variants(
    alias_or_name: str,
    explicit_variants: list[str] | None = None
) -> list[dict[str, Any]]:
    """
    Resolve all eligible variants for a product alias or name from:
    1. standard_rate_cards
    2. rate_cards
    3. sku_alias_map & sku_family_master

    Returns a list of variant dicts with:
    - sku_name: canonical rate card / standard rate card name
    - pack_size_g: pack size in grams
    - pack_size_kg: Decimal pack size in kg
    - std_rate: standard rate per kg
    - category: product category
    - alias_codes: sales codes (e.g. ['bc'])
    """
    clean_term = alias_or_name.strip()
    if not clean_term:
        return []

    # 1. Check if user specified explicit variants (e.g. BC-200 and BC-500)
    if explicit_variants and len(explicit_variants) >= 2:
        matched_variants = []
        for ev in explicit_variants:
            ev_clean = ev.strip()
            # Extract pack size if present (e.g. "BC-200" -> alias "bc", pack 200)
            sz_match = re.search(r"(\d{2,4})", ev_clean)
            sz = sz_match.group(1) if sz_match else None

            # Try to match in standard_rate_cards or rate_cards
            rows = db.query(
                """
                SELECT sku_name, category, uom, std_rate
                FROM standard_rate_cards
                WHERE sku_name ILIKE %s OR sku_name ILIKE %s
                ORDER BY sku_name
                LIMIT 5
                """,
                [f"%{ev_clean}%", f"%{re.sub(r'[-\d]+$', '', ev_clean).strip()}%{sz if sz else ''}%"]
            )
            if not rows:
                # Also try alias map lookup
                prefix = re.sub(r"[\s\-_]*\d+.*$", "", ev_clean).strip()
                alias_rows = db.query(
                    """
                    SELECT sam.rate_card_sku_name, sfm.product_name
                    FROM sku_alias_map sam
                    LEFT JOIN sku_family_master sfm ON sam.family_id = sfm.id
                    WHERE sam.sales_sku_name ILIKE %s OR sfm.product_code ILIKE %s
                    """,
                    [prefix, prefix]
                )
                if alias_rows:
                    core = alias_rows[0]["rate_card_sku_name"]
                    core_clean = re.sub(r"-\d+$", "", core).split("-")[-1].strip()
                    search_pat = f"%{core_clean}%{sz}%" if sz else f"%{core_clean}%"
                    rows = db.query(
                        """
                        SELECT sku_name, category, uom, std_rate
                        FROM standard_rate_cards
                        WHERE sku_name ILIKE %s
                        ORDER BY sku_name
                        LIMIT 5
                        """,
                        [search_pat]
                    )

            if rows:
                r = rows[0]
                pack_g = parse_pack_size_grams(r["sku_name"]) or (int(sz) if sz else 1000)
                matched_variants.append({
                    "sku_name": r["sku_name"],
                    "pack_size_g": pack_g,
                    "pack_size_kg": Decimal(pack_g) / Decimal(1000),
                    "std_rate": float(r["std_rate"]) if r.get("std_rate") is not None else 700.0,
                    "category": r.get("category") or "Coffee",
                    "alias_codes": [clean_term.lower()],
                })

        if matched_variants:
            # Deduplicate by sku_name
            seen = set()
            unique_matched = []
            for mv in matched_variants:
                if mv["sku_name"] not in seen:
                    seen.add(mv["sku_name"])
                    unique_matched.append(mv)
            if len(unique_matched) >= 2:
                return unique_matched

    # 2. General alias / product family resolution
    # Find matching canonical names in sku_alias_map & sku_family_master
    alias_rows = db.query(
        """
        SELECT sam.sales_sku_name, sam.rate_card_sku_name, sfm.product_name, sfm.product_code
        FROM sku_alias_map sam
        LEFT JOIN sku_family_master sfm ON sam.family_id = sfm.id
        WHERE sam.sales_sku_name ILIKE %s 
           OR sfm.product_code ILIKE %s
           OR sam.rate_card_sku_name ILIKE %s
        """,
        [clean_term, clean_term, f"%{clean_term}%"]
    )

    alias_codes = [clean_term.lower()]
    core_keyword = clean_term

    if alias_rows:
        canonical_name = alias_rows[0]["rate_card_sku_name"]
        sales_code = alias_rows[0].get("sales_sku_name") or clean_term
        if sales_code.lower() not in alias_codes:
            alias_codes.append(sales_code.lower())

        # Extract core name without pack size e.g. "Coffee-Brownie Special-200" -> "Brownie Special"
        core = re.sub(r"-\d+$", "", canonical_name)
        core = re.sub(r"\s*\([^\)]*\)$", "", core)
        core_keyword = core.split("-")[-1].strip()

    # Query standard_rate_cards for all variants of this core keyword
    std_rows = db.query(
        """
        SELECT sku_name, category, uom, std_rate
        FROM standard_rate_cards
        WHERE sku_name ILIKE %s
        ORDER BY sku_name
        """,
        [f"%{core_keyword}%"]
    )

    # Also check rate_cards for any customer-specific variants
    rc_rows = db.query(
        """
        SELECT DISTINCT sku_name, category, std_rate
        FROM rate_cards
        WHERE sku_name ILIKE %s
        ORDER BY sku_name
        """,
        [f"%{core_keyword}%"]
    )

    all_found: dict[str, dict[str, Any]] = {}

    for r in std_rows:
        sname = r["sku_name"]
        pack_g = parse_pack_size_grams(sname) or 1000
        all_found[sname] = {
            "sku_name": sname,
            "pack_size_g": pack_g,
            "pack_size_kg": Decimal(pack_g) / Decimal(1000),
            "std_rate": float(r["std_rate"]) if r.get("std_rate") is not None else 700.0,
            "category": r.get("category") or "Coffee",
            "alias_codes": alias_codes,
        }

    for r in rc_rows:
        sname = r["sku_name"]
        if sname not in all_found:
            pack_g = parse_pack_size_grams(sname) or 1000
            all_found[sname] = {
                "sku_name": sname,
                "pack_size_g": pack_g,
                "pack_size_kg": Decimal(pack_g) / Decimal(1000),
                "std_rate": float(r["std_rate"]) if r.get("std_rate") is not None else 700.0,
                "category": r.get("category") or "Coffee",
                "alias_codes": alias_codes,
            }

    # Sort deterministically by pack size, then sku_name
    variant_list = sorted(list(all_found.values()), key=lambda x: (x["pack_size_g"], x["sku_name"]))
    return variant_list


# ═══════════════════════════════════════════════════════════════════════
# STAGE 3 & 4: DETERMINISTIC DATA RETRIEVAL & VALIDATION
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class VariantSalesStats:
    sku_name: str
    pack_size_g: int
    pack_size_kg: Decimal
    std_rate: float
    category: str
    total_kg: Decimal
    total_units: int
    total_revenue: Decimal
    transaction_count: int
    customer_count: int


@dataclass
class ComparisonResult:
    variants_stats: list[VariantSalesStats]
    date_from: str
    date_to: str
    period_label: str
    metric_requested: MetricType
    units_leaders: list[VariantSalesStats]
    revenue_leaders: list[VariantSalesStats]
    volume_leaders: list[VariantSalesStats]
    has_sales_data: bool
    unattributed_alias_kg: Decimal = Decimal(0)
    unattributed_alias_revenue: Decimal = Decimal(0)
    alias_name: str = ""


def execute_variant_comparison(
    variants: list[dict[str, Any]],
    date_from: str | None = None,
    date_to: str | None = None,
    alias: str | None = None,
    custom_sales_filter: str | None = None,
) -> ComparisonResult:
    """
    Execute deterministic PostgreSQL aggregation comparing all given variants.

    Business Rules:
    - Joins daily_sales with customer rate_cards and standard_rate_cards.
    - Captures both:
      1. Direct SKU name transactions in daily_sales (e.g. ds.sku_name = 'Coffee-Brownie Special-200')
      2. Alias transactions mapped via customer rate cards (e.g. ds.sku_name = 'bc' AND rc.sku_name = 'Coffee-Brownie Special-200')
    - Calculates:
      - Volume in kg
      - Units sold (packs) = kg / pack_size_kg
      - Sales revenue = kg * COALESCE(approved_inclusive, rc.std_rate, src.std_rate)
    - Fully parameterized, read-only SQL.
    - Deterministic ordering and tie handling.
    """
    # Determine date period
    min_db_date, max_db_date = date_utils.get_sales_date_range()
    effective_from = date_from or min_db_date
    effective_to = date_to or max_db_date

    period_label = (
        f"{date_utils.format_date_for_display(effective_from)} to {date_utils.format_date_for_display(effective_to)}"
        if (effective_from and effective_to)
        else "all available sales records"
    )

    base_alias = re.sub(r"[\s\-_]*\d+.*$", "", alias or "").strip().lower()

    stats_list: list[VariantSalesStats] = []
    has_any_data = False

    for v in variants:
        sname = v["sku_name"]
        pack_g = v["pack_size_g"]
        pack_kg = v["pack_size_kg"]
        std_rate = v["std_rate"]
        cat = v.get("category", "Coffee")

        # Collect candidate aliases for daily_sales
        cand_aliases = set()
        for a in v.get("alias_codes", []):
            cand_aliases.add(a.lower())
            b_a = re.sub(r"[\s\-_]*\d+.*$", "", a).strip().lower()
            if b_a:
                cand_aliases.add(b_a)
        if alias:
            cand_aliases.add(alias.lower())
            if base_alias:
                cand_aliases.add(base_alias)
        cand_alias_list = list(cand_aliases)

        # Execute read-only aggregation query for this specific variant
        # Uses parameterized queries
        sql = """
            SELECT 
                COUNT(DISTINCT ds.id) AS txns,
                COUNT(DISTINCT ds.customer_id) AS custs,
                COALESCE(ROUND(SUM(ds.qty_kg)::numeric, 2), 0) AS total_kg,
                COALESCE(ROUND(SUM(ds.qty_kg * COALESCE(rc.approved_inclusive, rc.std_rate, src.std_rate, %s))::numeric, 2), 0) AS total_revenue
            FROM daily_sales ds
            LEFT JOIN customer_master cm ON ds.customer_id = cm.customer_id
            LEFT JOIN rate_cards rc ON ds.customer_id = rc.customer_id AND rc.sku_name ILIKE %s
            LEFT JOIN standard_rate_cards src ON rc.sku_name = src.sku_name
            WHERE (
                (LOWER(ds.sku_name) = ANY(%s) AND rc.sku_name ILIKE %s)
                OR ds.sku_name ILIKE %s
            )
            AND ds.sale_date BETWEEN %s AND %s
        """
        params = [
            std_rate,
            sname,
            cand_alias_list,
            sname,
            sname,
            effective_from,
            effective_to,
        ]

        rows = db.query(sql, params)
        if rows:
            r = rows[0]
            kg = Decimal(str(r["total_kg"] or 0))
            rev = Decimal(str(r["total_revenue"] or 0))
            txns = int(r["txns"] or 0)
            custs = int(r["custs"] or 0)

            # Units sold = kg / pack_size_kg
            units = int(round(kg / pack_kg)) if pack_kg > 0 else int(kg)

            if txns > 0:
                has_any_data = True

            stats_list.append(VariantSalesStats(
                sku_name=sname,
                pack_size_g=pack_g,
                pack_size_kg=pack_kg,
                std_rate=std_rate,
                category=cat,
                total_kg=kg,
                total_units=units,
                total_revenue=rev,
                transaction_count=txns,
                customer_count=custs,
            ))
        else:
            stats_list.append(VariantSalesStats(
                sku_name=sname,
                pack_size_g=pack_g,
                pack_size_kg=pack_kg,
                std_rate=std_rate,
                category=cat,
                total_kg=Decimal(0),
                total_units=0,
                total_revenue=Decimal(0),
                transaction_count=0,
                customer_count=0,
            ))

    # Also compute general/unattributed sales for the alias (customers on standard rates without variant rate card)
    unatt_kg = Decimal(0)
    unatt_rev = Decimal(0)
    if base_alias and has_any_data:
        total_alias_sql = """
            SELECT 
                COALESCE(ROUND(SUM(qty_kg)::numeric, 2), 0) AS total_kg
            FROM daily_sales
            WHERE sku_name ILIKE %s AND sale_date BETWEEN %s AND %s
        """
        t_rows = db.query(total_alias_sql, [base_alias, effective_from, effective_to])
        if t_rows:
            all_alias_kg = Decimal(str(t_rows[0]["total_kg"] or 0))
            variant_total_kg = sum(s.total_kg for s in stats_list)
            if all_alias_kg > variant_total_kg:
                unatt_kg = all_alias_kg - variant_total_kg
                default_rate = Decimal(str(variants[0]["std_rate"])) if variants else Decimal(700)
                unatt_rev = unatt_kg * default_rate

    # ═══════════════════════════════════════════════════════════════════
    # STAGE 5: CALCULATE RANKINGS & TIE HANDLING
    # ═══════════════════════════════════════════════════════════════════
    # Rank by Units Sold
    max_units = max((s.total_units for s in stats_list), default=0)
    units_leaders = [s for s in stats_list if s.total_units == max_units and max_units > 0]

    # Rank by Revenue
    max_revenue = max((s.total_revenue for s in stats_list), default=Decimal(0))
    revenue_leaders = [s for s in stats_list if s.total_revenue == max_revenue and max_revenue > 0]

    # Rank by Volume (kg)
    max_vol = max((s.total_kg for s in stats_list), default=Decimal(0))
    volume_leaders = [s for s in stats_list if s.total_kg == max_vol and max_vol > 0]

    return ComparisonResult(
        variants_stats=stats_list,
        date_from=effective_from,
        date_to=effective_to,
        period_label=period_label,
        metric_requested=MetricType.BOTH,
        units_leaders=units_leaders,
        revenue_leaders=revenue_leaders,
        volume_leaders=volume_leaders,
        has_sales_data=has_any_data,
        unattributed_alias_kg=unatt_kg,
        unattributed_alias_revenue=unatt_rev,
        alias_name=base_alias.upper() if base_alias else "",
    )


# ═══════════════════════════════════════════════════════════════════════
# STAGE 6: RESPONSE GENERATION (NATURAL LANGUAGE + TABLE + CHART)
# ═══════════════════════════════════════════════════════════════════════

def format_comparison_response(
    comp: ComparisonResult,
    conv_id: str,
    original_message: str,
    metric_requested: MetricType = MetricType.BOTH,
) -> dict[str, Any]:
    """
    Generate natural-language answer supported by the actual results,
    along with a structured table and chart for the frontend.
    """
    alias_disp = comp.alias_name or "Product"
    period_str = comp.period_label

    # Case A: No sales data found for any variant in the requested period
    if not comp.has_sales_data:
        variant_names = [v.sku_name for v in comp.variants_stats]
        names_str = ", ".join(f"**{vn}**" for vn in variant_names)
        answer = (
            f"I found {len(variant_names)} catalog variants for **'{alias_disp}'** ({names_str}), "
            f"but **no sales transactions** were recorded in the database for the period **{period_str}**.\n\n"
            f"The database currently contains historical sales records from **{comp.date_from}** to **{comp.date_to}**."
        )
        mem.add_message(conv_id, "user", original_message)
        mem.add_message(conv_id, "assistant", answer)
        return {
            "conversation_id": conv_id,
            "answer_text": answer,
            "table": None,
            "chart": None,
            "report_eligible": False,
            "report_prefill": None,
            "clarification": None,
        }

    # Case B: Sales data found -> Compare metrics
    # Build Table
    table_columns = ["Product Variant", "Pack Size", "Volume (kg)", "Units Sold (Packs)", "Revenue (Rs.)", "Transactions"]
    table_rows = []
    chart_labels = []
    chart_values = []

    for s in comp.variants_stats:
        table_rows.append([
            s.sku_name,
            f"{s.pack_size_g}g",
            float(s.total_kg),
            int(s.total_units),
            f"Rs. {s.total_revenue:,.2f}",
            s.transaction_count,
        ])
        chart_labels.append(s.sku_name)
        # Chart displays revenue by default, or units if units was specifically requested
        if metric_requested == MetricType.UNITS:
            chart_values.append(int(s.total_units))
        else:
            chart_values.append(float(s.total_revenue))

    chart_type = "bar"
    chart_payload = {
        "type": chart_type,
        "data": {
            "labels": chart_labels,
            "values": chart_values,
        }
    }

    table_payload = {
        "columns": table_columns,
        "rows": table_rows,
    }

    # Build Executive Answer Text
    lines = [
        f"Over the sales period (**{period_str}**), here is the performance comparison across all **{alias_disp}** variants:\n",
        "### Evaluated Variants:"
    ]
    for s in comp.variants_stats:
        lines.append(
            f"- **{s.sku_name}** ({s.pack_size_g}g): **{s.total_units:,} packs** sold | **Rs. {s.total_revenue:,.2f}** revenue | **{float(s.total_kg):,.2f} kg** volume ({s.transaction_count} orders)"
        )

    lines.append("\n### Comparative Findings:")
    # Units Leader analysis
    if len(comp.units_leaders) == 1:
        u_top = comp.units_leaders[0]
        runners_up = [s for s in comp.variants_stats if s.sku_name != u_top.sku_name]
        runner_str = f" (outperforming {runners_up[0].sku_name} at {runners_up[0].total_units:,} packs)" if runners_up else ""
        lines.append(f"- **Top Units Sold**: **{u_top.sku_name}** led with **{u_top.total_units:,} packs** ({u_top.pack_size_g}g){runner_str}.")
    elif len(comp.units_leaders) > 1:
        tied_names = " and ".join(f"**{s.sku_name}**" for s in comp.units_leaders)
        lines.append(f"- **Top Units Sold (Tie)**: {tied_names} tied with **{comp.units_leaders[0].total_units:,} packs** each.")

    # Revenue Leader analysis
    if len(comp.revenue_leaders) == 1:
        r_top = comp.revenue_leaders[0]
        runners_up = [s for s in comp.variants_stats if s.sku_name != r_top.sku_name]
        runner_str = f" (compared to Rs. {runners_up[0].total_revenue:,.2f} for {runners_up[0].sku_name})" if runners_up else ""
        lines.append(f"- **Highest Revenue**: **{r_top.sku_name}** generated **Rs. {r_top.total_revenue:,.2f}** ({float(r_top.total_kg):,.2f} kg sold){runner_str}.")
    elif len(comp.revenue_leaders) > 1:
        tied_names = " and ".join(f"**{s.sku_name}**" for s in comp.revenue_leaders)
        lines.append(f"- **Highest Revenue (Tie)**: {tied_names} tied with **Rs. {comp.revenue_leaders[0].total_revenue:,.2f}** each.")

    # Overall Summary
    # Check if a single variant won BOTH metrics
    if (len(comp.units_leaders) == 1 and len(comp.revenue_leaders) == 1 and 
            comp.units_leaders[0].sku_name == comp.revenue_leaders[0].sku_name):
        overall_winner = comp.units_leaders[0]
        lines.append(
            f"\nOverall, **{overall_winner.sku_name}** performed best, leading in both unit sales and total sales revenue."
        )
    elif comp.units_leaders and comp.revenue_leaders:
        u_winner = comp.units_leaders[0].sku_name
        r_winner = comp.revenue_leaders[0].sku_name
        lines.append(
            f"\n**{u_winner}** achieved the highest unit volume, while **{r_winner}** generated the highest sales revenue."
        )

    # Disclose general un-attributed volume if any
    if comp.unattributed_alias_kg > 0:
        lines.append(
            f"\n*(Note: An additional {float(comp.unattributed_alias_kg):,.2f} kg was billed under the general '{comp.alias_name.lower()}' alias by customers on standard pricing without a pack-size specific rate card.)*"
        )

    answer_text = "\n".join(lines)

    prefill = {
        "date_from": date_utils.format_date_for_display(comp.date_from),
        "date_to": date_utils.format_date_for_display(comp.date_to),
        "route_ids": None,
        "branches": ["coffee"],
        "days": None,
        "notes": f"Variant performance comparison for {alias_disp}"
    }

    mem.add_message(conv_id, "user", original_message)
    mem.add_message(conv_id, "assistant", answer_text)

    return {
        "conversation_id": conv_id,
        "answer_text": answer_text,
        "table": table_payload,
        "chart": chart_payload,
        "report_eligible": True,
        "report_prefill": prefill,
        "clarification": None,
    }


# ═══════════════════════════════════════════════════════════════════════
# MAIN INTENT PLANNER PIPELINE ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════

def plan_and_execute_comparison(
    message: str,
    conv_id: str,
    extracted_mentions: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """
    Main entry point for intent-aware comparison and ranking pipeline.
    Returns response dictionary if handled as comparison, or None if not applicable.
    """
    if not is_comparison_intent(message):
        return None

    extracted = extracted_mentions or {}
    metric_type = detect_comparison_metric(message)
    explicit_variants = extract_explicit_variants(message)

    # 1. Resolve product alias / mention
    product_term = extracted.get("sku_alias") or extracted.get("sku_mention")
    if not product_term and explicit_variants:
        product_term = explicit_variants[0]

    # If still not found in extracted, extract from message directly
    if not product_term:
        alias_match = re.search(r"\b(bc|bs|80d|mr|at|spc|spt|pt|smt|gl|kt)\b", message, re.IGNORECASE)
        if alias_match:
            product_term = alias_match.group(1).lower()

    if not product_term:
        # Check known product keywords like 'brownie special', 'cafe supreme', 'classic'
        for kw in ["brownie special", "cafe supreme", "mocha special", "daily roast", "super shakthi", "classic", "atrium"]:
            if kw in message.lower():
                product_term = kw
                break

    if not product_term and not explicit_variants:
        return None

    # 2. Resolve all relevant variants
    variants = resolve_product_variants(product_term or "", explicit_variants=explicit_variants)
    if not variants:
        return None

    # 3. Determine time period
    date_from, date_to = None, None
    try:
        from .chat import _resolve_date_range
        date_from, date_to = _resolve_date_range(message)
    except Exception:
        pass

    # 4. Execute comparison
    comp_result = execute_variant_comparison(
        variants=variants,
        date_from=date_from,
        date_to=date_to,
        alias=product_term,
    )
    comp_result.metric_requested = metric_type

    # 5. Format response
    return format_comparison_response(
        comp=comp_result,
        conv_id=conv_id,
        original_message=message,
        metric_requested=metric_type,
    )
