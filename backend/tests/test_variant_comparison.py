"""
Automated regression tests for Intent-Aware Entity Resolution & Product Variant Comparisons.

Covers:
1. Exact Bug: "Which BC did best sales?" -> Compares all BC variants, no clarification question!
2. "Which BC variant sold the most units?" -> Focuses on units sold leader.
3. "Which BC variant generated the highest revenue?" -> Focuses on sales revenue leader.
4. "Compare BC-200 and BC-500." -> Explicit side-by-side comparison of specific variants.
5. "How much did BC sell last month?" -> Period-aware performance evaluation without asking user to pick a variant.
6. A product alias that resolves to 3 or more variants (e.g. 'BS' with 4 variants).
7. Two variants with identical performance (tie handling).
8. A variant with no sales transactions (0 sales handling).
9. Missing or invalid SKU mappings (safe handling without crash).
10. A genuine ambiguous single-product lookup that should request clarification ("What is standard price of bs", "Show me BC price").
11. A comparison with insufficient data (explains data limitation rather than asking to pick a variant).
12. A product comparison that must not accidentally aggregate unrelated SKUs.
13. Different winners for units sold vs sales revenue.
"""

from decimal import Decimal
import pytest

from app import chat as chat_module
from app import entity_resolution
from app import intent_planner
from app.intent_planner import (
    ComparisonResult,
    MetricType,
    VariantSalesStats,
    execute_variant_comparison,
    format_comparison_response,
    is_comparison_intent,
    resolve_product_variants,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. EXACT BUG: "Which BC did best sales?"
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_exact_bug_which_bc_did_best_sales():
    """
    User query: 'which bc did best sales'
    Expected: Retrieve sales data for BOTH BC variants (Coffee-Brownie Special-200
    and Coffee-Brownie Special-500), compare performance, and declare leader.
    MUST NOT ask clarification asking user to pick one variant!
    """
    conv_id = "test-bc-best-sales"
    res = await chat_module.chat("which bc did best sales", conv_id)

    # 1. No clarification payload
    assert res.get("clarification") is None, (
        f"Expected NO clarification for 'which bc did best sales', got: {res.get('clarification')}"
    )

    answer = res.get("answer_text", "")

    # 2. Must not ask 'Which one did you mean?' or 'Which variant did you mean?'
    assert "Which variant" not in answer and "Which one did you mean" not in answer, (
        f"Chatbot must NOT ask which variant the user means! Got: {answer}"
    )

    # 3. Must mention both variants
    assert "Coffee-Brownie Special-200" in answer, "Must include 200g variant in answer"
    assert "Coffee-Brownie Special-500" in answer, "Must include 500g variant in answer"

    # 4. Must declare Coffee-Brownie Special-200 as best performer
    assert "Coffee-Brownie Special-200" in answer and "performed best" in answer.lower()

    # 5. Must disclose period used
    assert "2026" in answer

    # 6. Structured Table & Chart
    table = res.get("table")
    assert table is not None, "Table must be present"
    assert len(table["rows"]) == 2, "Table must contain both BC variants"
    assert table["columns"] == ["Product Variant", "Pack Size", "Volume (kg)", "Units Sold (Packs)", "Revenue (Rs.)", "Transactions"]

    chart = res.get("chart")
    assert chart is not None, "Chart must be present"
    assert len(chart["data"]["labels"]) == 2

    # 7. Report eligible
    assert res.get("report_eligible") is True


# ═══════════════════════════════════════════════════════════════════════
# 2. "Which BC variant sold the most units?"
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_which_bc_variant_sold_most_units():
    """Evaluate units sold across BC variants."""
    res = await chat_module.chat("Which BC variant sold the most units?", None)

    assert res.get("clarification") is None
    answer = res.get("answer_text", "")

    assert "Coffee-Brownie Special-200" in answer
    assert "Coffee-Brownie Special-500" in answer
    assert "Top Units Sold" in answer or "packs" in answer
    assert "15,515" in answer or "15515" in answer


# ═══════════════════════════════════════════════════════════════════════
# 3. "Which BC variant generated the highest revenue?"
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_which_bc_variant_generated_highest_revenue():
    """Evaluate sales revenue across BC variants."""
    res = await chat_module.chat("Which BC variant generated the highest revenue?", None)

    assert res.get("clarification") is None
    answer = res.get("answer_text", "")

    assert "Coffee-Brownie Special-200" in answer
    assert "Highest Revenue" in answer or "revenue" in answer.lower()
    assert "2,140,659" in answer or "2140659" in answer


# ═══════════════════════════════════════════════════════════════════════
# 4. "Compare BC-200 and BC-500."
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_compare_bc200_and_bc500():
    """Explicit comparison between two named variants."""
    res = await chat_module.chat("Compare BC-200 and BC-500", None)

    assert res.get("clarification") is None
    answer = res.get("answer_text", "")

    assert "Coffee-Brownie Special-200" in answer
    assert "Coffee-Brownie Special-500" in answer
    assert res.get("table") is not None
    assert len(res["table"]["rows"]) == 2


# ═══════════════════════════════════════════════════════════════════════
# 5. "How much did BC sell last month?"
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_how_much_did_bc_sell_last_month():
    """
    Performance inquiry for BC with time period.
    Must evaluate BC variants without asking the user to choose one.
    """
    res = await chat_module.chat("How much did BC sell last month?", None)

    # Must NOT ask which variant the user meant
    assert res.get("clarification") is None
    answer = res.get("answer_text", "")
    assert "Which variant" not in answer

    # Explains either data or period availability for BC variants
    assert "BC" in answer or "Brownie Special" in answer


# ═══════════════════════════════════════════════════════════════════════
# 6. Product alias that resolves to 3 or more variants (e.g. BS)
# ═══════════════════════════════════════════════════════════════════════

def test_alias_resolving_to_three_or_more_variants():
    """'BS' (Cafe Supreme) resolves to 4 distinct variants in the catalog."""
    variants = resolve_product_variants("bs")
    assert len(variants) >= 3, f"Expected at least 3 variants for BS, got {len(variants)}"

    sku_names = [v["sku_name"] for v in variants]
    assert "Coffee-Cafe Supreme-200" in sku_names
    assert "Coffee-Cafe Supreme-500" in sku_names
    assert any("SPL" in s for s in sku_names)

    # Execute comparison across all 4 variants
    comp = execute_variant_comparison(variants, alias="bs")
    assert len(comp.variants_stats) >= 3
    assert comp.has_sales_data is True

    # Coffee-Cafe Supreme-200 is the leader
    assert comp.units_leaders[0].sku_name == "Coffee-Cafe Supreme-200"
    assert comp.revenue_leaders[0].sku_name == "Coffee-Cafe Supreme-200"


# ═══════════════════════════════════════════════════════════════════════
# 7. Two variants with identical performance (tie handling)
# ═══════════════════════════════════════════════════════════════════════

def test_two_variants_with_identical_performance_tie():
    """Verify tie handling when two variants achieve identical units and revenue."""
    stat1 = VariantSalesStats(
        sku_name="Coffee-Alpha-200",
        pack_size_g=200,
        pack_size_kg=Decimal("0.2"),
        std_rate=500.0,
        category="Coffee",
        total_kg=Decimal("100.00"),
        total_units=500,
        total_revenue=Decimal("50000.00"),
        transaction_count=10,
        customer_count=5,
    )
    stat2 = VariantSalesStats(
        sku_name="Coffee-Beta-200",
        pack_size_g=200,
        pack_size_kg=Decimal("0.2"),
        std_rate=500.0,
        category="Coffee",
        total_kg=Decimal("100.00"),
        total_units=500,
        total_revenue=Decimal("50000.00"),
        transaction_count=10,
        customer_count=5,
    )

    comp = ComparisonResult(
        variants_stats=[stat1, stat2],
        date_from="2026-04-01",
        date_to="2026-04-15",
        period_label="1 April 2026 to 15 April 2026",
        metric_requested=MetricType.BOTH,
        units_leaders=[stat1, stat2],  # Tie
        revenue_leaders=[stat1, stat2],  # Tie
        volume_leaders=[stat1, stat2],
        has_sales_data=True,
        alias_name="TEST",
    )

    resp = format_comparison_response(comp, "tie-conv", "compare alpha and beta")
    answer = resp["answer_text"]

    assert "Top Units Sold (Tie)" in answer
    assert "Highest Revenue (Tie)" in answer
    assert "Coffee-Alpha-200" in answer
    assert "Coffee-Beta-200" in answer
    assert "tied with" in answer


# ═══════════════════════════════════════════════════════════════════════
# 8. Variant with no sales transactions (0 sales handling)
# ═══════════════════════════════════════════════════════════════════════

def test_variant_with_no_sales_transactions():
    """Verify variant with 0 transactions is included with 0 units and does not crash."""
    stat_active = VariantSalesStats(
        sku_name="Coffee-Active-200",
        pack_size_g=200,
        pack_size_kg=Decimal("0.2"),
        std_rate=600.0,
        category="Coffee",
        total_kg=Decimal("50.00"),
        total_units=250,
        total_revenue=Decimal("30000.00"),
        transaction_count=5,
        customer_count=3,
    )
    stat_zero = VariantSalesStats(
        sku_name="Coffee-Inactive-500",
        pack_size_g=500,
        pack_size_kg=Decimal("0.5"),
        std_rate=600.0,
        category="Coffee",
        total_kg=Decimal("0.00"),
        total_units=0,
        total_revenue=Decimal("0.00"),
        transaction_count=0,
        customer_count=0,
    )

    comp = ComparisonResult(
        variants_stats=[stat_active, stat_zero],
        date_from="2026-04-01",
        date_to="2026-04-15",
        period_label="1 April 2026 to 15 April 2026",
        metric_requested=MetricType.BOTH,
        units_leaders=[stat_active],
        revenue_leaders=[stat_active],
        volume_leaders=[stat_active],
        has_sales_data=True,
        alias_name="ACTIVE_TEST",
    )

    resp = format_comparison_response(comp, "zero-conv", "compare active and inactive")
    assert resp["table"] is not None
    assert len(resp["table"]["rows"]) == 2

    # Inactive variant row has 0 values
    zero_row = next(r for r in resp["table"]["rows"] if r[0] == "Coffee-Inactive-500")
    assert zero_row[2] == 0.0  # kg
    assert zero_row[3] == 0    # units
    assert zero_row[5] == 0    # txns

    # Active variant is winner
    assert "Coffee-Active-200" in resp["answer_text"]


# ═══════════════════════════════════════════════════════════════════════
# 9. Missing or invalid SKU mappings (safe handling)
# ═══════════════════════════════════════════════════════════════════════

def test_missing_or_invalid_sku_mappings():
    """Non-existent alias returns empty variant list without error."""
    variants = resolve_product_variants("nonexistent_unknown_sku_xyz_123")
    assert variants == []

    # plan_and_execute_comparison returns None safely
    res = intent_planner.plan_and_execute_comparison("Which nonexistent_unknown_sku_xyz_123 did best sales?", "test-none")
    assert res is None


# ═══════════════════════════════════════════════════════════════════════
# 10. Genuine ambiguous single-product lookup MUST request clarification
# ═══════════════════════════════════════════════════════════════════════

def test_genuine_ambiguous_single_product_lookup_clarification():
    """
    Pricing inquiry without pack size for an SKU with multiple variants
    MUST still prompt for clarification (e.g. 'what is standard price of bs').
    Distinguishes genuine single-attribute ambiguity from comparison intent.
    """
    ext = entity_resolution.extract_candidate_mentions("what is standard price of bs")
    res = entity_resolution.evaluate_resolution("what is standard price of bs", ext)

    # Must be AMBIGUOUS because BS has variants with different prices (730 vs 740)
    assert res.status == entity_resolution.ResolutionStatus.AMBIGUOUS
    assert res.clarification_state is not None
    assert "Which one do you mean" in res.clarification_text or "Which one did you mean" in res.clarification_text


# ═══════════════════════════════════════════════════════════════════════
# 11. Comparison with insufficient data (explains data limitation)
# ═══════════════════════════════════════════════════════════════════════

def test_comparison_with_insufficient_data():
    """
    When variants exist in catalog but have zero sales in the period,
    must explain the data limitation rather than asking user to pick a variant.
    """
    stat1 = VariantSalesStats(
        sku_name="Item-A-200", pack_size_g=200, pack_size_kg=Decimal("0.2"), std_rate=100.0,
        category="Food", total_kg=Decimal(0), total_units=0, total_revenue=Decimal(0),
        transaction_count=0, customer_count=0
    )
    stat2 = VariantSalesStats(
        sku_name="Item-A-500", pack_size_g=500, pack_size_kg=Decimal("0.5"), std_rate=100.0,
        category="Food", total_kg=Decimal(0), total_units=0, total_revenue=Decimal(0),
        transaction_count=0, customer_count=0
    )

    comp = ComparisonResult(
        variants_stats=[stat1, stat2],
        date_from="2026-04-01",
        date_to="2026-04-15",
        period_label="1 April 2026 to 15 April 2026",
        metric_requested=MetricType.BOTH,
        units_leaders=[],
        revenue_leaders=[],
        volume_leaders=[],
        has_sales_data=False,
        alias_name="ITEM_A",
    )

    resp = format_comparison_response(comp, "conv-nodata", "which item a did best sales")

    assert resp["clarification"] is None
    answer = resp["answer_text"]
    assert "no sales transactions" in answer.lower()
    assert resp["table"] is None


# ═══════════════════════════════════════════════════════════════════════
# 12. Comparison must NOT accidentally aggregate unrelated SKUs
# ═══════════════════════════════════════════════════════════════════════

def test_comparison_does_not_aggregate_unrelated_skus():
    """
    Comparing 'BC' variants must only include Brownie Special variants,
    never Cafe Supreme ('BS'), Mocha Special, or other SKUs.
    """
    bc_variants = resolve_product_variants("bc")
    sku_names = [v["sku_name"] for v in bc_variants]

    assert all("Brownie Special" in s for s in sku_names)
    assert not any("Cafe Supreme" in s for s in sku_names)
    assert not any("Mocha" in s for s in sku_names)


# ═══════════════════════════════════════════════════════════════════════
# 13. Units sold and Revenue have DIFFERENT winners
# ═══════════════════════════════════════════════════════════════════════

def test_different_winners_for_units_and_revenue():
    """
    Verify that when one variant leads on units sold and another variant
    leads on revenue, the system reports BOTH accurately without conflating them.
    """
    # Variant A: Small pack (100g) sold in high unit volume but lower revenue
    variant_a = VariantSalesStats(
        sku_name="Coffee-Micro-100",
        pack_size_g=100,
        pack_size_kg=Decimal("0.1"),
        std_rate=200.0,
        category="Coffee",
        total_kg=Decimal("100.00"),
        total_units=1000,           # WINS ON UNITS: 1,000 packs
        total_revenue=Decimal("20000.00"),  # Lower revenue: Rs. 20,000
        transaction_count=20,
        customer_count=15,
    )
    # Variant B: Large pack (1000g) sold in lower unit volume but much higher revenue
    variant_b = VariantSalesStats(
        sku_name="Coffee-Macro-1000",
        pack_size_g=1000,
        pack_size_kg=Decimal("1.0"),
        std_rate=500.0,
        category="Coffee",
        total_kg=Decimal("300.00"),
        total_units=300,            # Lower units: 300 packs
        total_revenue=Decimal("150000.00"), # WINS ON REVENUE: Rs. 150,000
        transaction_count=15,
        customer_count=10,
    )

    comp = ComparisonResult(
        variants_stats=[variant_a, variant_b],
        date_from="2026-04-01",
        date_to="2026-04-15",
        period_label="1 April 2026 to 15 April 2026",
        metric_requested=MetricType.BOTH,
        units_leaders=[variant_a],
        revenue_leaders=[variant_b],
        volume_leaders=[variant_b],
        has_sales_data=True,
        alias_name="SPLIT_TEST",
    )

    resp = format_comparison_response(comp, "split-conv", "which split test did best sales")
    answer = resp["answer_text"]

    # Top Units Sold must declare Variant A
    assert "Coffee-Micro-100" in answer
    assert "1,000 packs" in answer

    # Highest Revenue must declare Variant B
    assert "Coffee-Macro-1000" in answer
    assert "150,000.00" in answer

    # Explicit disclosure of both winners
    assert "achieved the highest unit volume" in answer
    assert "generated the highest sales revenue" in answer
