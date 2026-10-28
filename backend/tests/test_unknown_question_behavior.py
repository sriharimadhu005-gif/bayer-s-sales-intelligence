"""
Automated tests for Chatbot unknown-question, ambiguous request, and fallback safety behavior.

Covers:
1. Unsupported question -> "I don’t have enough information..." and no report
2. Ambiguous SKU -> Clarification question, no report
3. Ambiguous customer -> Clarification question, no report
4. Missing date range where required -> Clarification question ("Which date range should I use?")
5. Unclear metric -> Clarification question ("Do you mean sales volume, revenue, quantity ordered, or outstanding balance?")
6. Valid route-volume request -> Relevant route-volume report (Route 3, table, chart, report_eligible=True)
7. Database / query failure -> Safe retrieval-failure message, no generic report
"""

import asyncio
import os
import sys
import pytest
from unittest.mock import patch

# Ensure backend app is on sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app import chat as chat_module
from app import db


@pytest.mark.asyncio
async def test_unsupported_question():
    """Unsupported / out-of-domain question must return 'I don't have enough information...' and NO report."""
    unsupported_queries = [
        "What is the weather in Bangalore today?",
        "Who won the cricket world cup?",
        "What is the stock price of Apple?",
    ]
    for q in unsupported_queries:
        res = await chat_module.chat(q, None)
        answer = res.get("answer_text", "")

        # Must assert "I don’t have enough information" / "I don't have enough information"
        assert (
            "don’t have enough information to answer that from the available data" in answer
            or "don't have enough information to answer that from the available data" in answer
        ), f"Expected insufficient info refusal for '{q}', got: {answer}"

        # Must NOT return table, chart, or report
        assert res.get("table") is None, f"Table must be None for unsupported question '{q}'"
        assert res.get("chart") is None, f"Chart must be None for unsupported question '{q}'"
        assert res.get("report_eligible") is False, f"report_eligible must be False for '{q}'"
        assert res.get("report_prefill") is None, f"report_prefill must be None for '{q}'"

        # Must NEVER return Route 3 sales volume report
        assert "Route 3" not in answer, f"Route 3 report must NOT be returned for '{q}'"
        assert "8522.6" not in answer, f"Sales volume 8522.6 must NOT be returned for '{q}'"


@pytest.mark.asyncio
async def test_ambiguous_sku():
    """Ambiguous SKU query without pack size must ask for clarification and return NO report."""
    res = await chat_module.chat("What is the price of Classic?", None)
    answer = res.get("answer_text", "")

    # Must ask clarification for matching SKUs
    assert "I found multiple SKUs matching" in answer, f"Expected SKU ambiguity clarification, got: {answer}"
    assert "Which one do you mean" in answer, f"Expected options choice question, got: {answer}"

    # Must NOT generate a report
    assert res.get("table") is None, "Table must be None for ambiguous SKU"
    assert res.get("chart") is None, "Chart must be None for ambiguous SKU"
    assert res.get("report_eligible") is False, "report_eligible must be False for ambiguous SKU"

    # Must NOT return Route 3
    assert "Route 3" not in answer


@pytest.mark.asyncio
async def test_ambiguous_customer():
    """Ambiguous customer query matching multiple branches must ask for clarification and return NO report."""
    res = await chat_module.chat("Show sales for Sri Vishnu Park", None)
    answer = res.get("answer_text", "")

    # Must ask clarification listing distinct branches
    assert "I found multiple customers matching" in answer, f"Expected customer ambiguity clarification, got: {answer}"
    assert "Which one did you mean" in answer or "Which one do you mean" in answer

    # Must NOT generate a report
    assert res.get("table") is None, "Table must be None for ambiguous customer"
    assert res.get("chart") is None, "Chart must be None for ambiguous customer"
    assert res.get("report_eligible") is False, "report_eligible must be False for ambiguous customer"

    # Must NOT return Route 3
    assert "Route 3 had the highest" not in answer


@pytest.mark.asyncio
async def test_missing_date_range_where_required():
    """Report requests lacking date range must ask 'Which date range should I use?'."""
    res = await chat_module.chat("Generate sales report", None)
    answer = res.get("answer_text", "")

    assert "Which date range should I use?" in answer, f"Expected date range clarification, got: {answer}"
    assert res.get("table") is None, "Table must be None when date range is missing"
    assert res.get("chart") is None, "Chart must be None when date range is missing"
    assert res.get("report_eligible") is False, "report_eligible must be False when date range is missing"


@pytest.mark.asyncio
async def test_unclear_metric():
    """General performance inquiry without metric must clarify metric."""
    res = await chat_module.chat("How is Route 3 doing?", None)
    answer = res.get("answer_text", "")

    assert "Do you mean sales volume, revenue, quantity ordered, or outstanding balance?" in answer, (
        f"Expected metric clarification, got: {answer}"
    )
    assert res.get("table") is None
    assert res.get("chart") is None
    assert res.get("report_eligible") is False


@pytest.mark.asyncio
async def test_valid_route_volume_request():
    """Valid route volume request must return the Route 3 volume report with table, chart, and report_eligible=True."""
    res = await chat_module.chat("Which route had the highest sales volume?", None)
    answer = res.get("answer_text", "")

    # Must answer about route sales volume
    assert "Route 3" in answer, f"Expected Route 3 in answer, got: {answer}"
    assert "8522.6" in answer or "8,522.6" in answer, f"Expected total volume in answer, got: {answer}"

    # Table must be present with Route and Volume
    table = res.get("table")
    assert table is not None, "Table must be present for valid route-volume request"
    assert any("route" in col.lower() for col in table.get("columns", [])), f"Expected route column in table: {table.get('columns')}"
    assert any("volume" in col.lower() or "sales" in col.lower() for col in table.get("columns", [])), f"Expected volume/sales column in table: {table.get('columns')}"

    # Chart must be present
    chart = res.get("chart")
    assert chart is not None, "Chart must be present for valid route-volume request"
    assert chart.get("type") in ("bar", "pie")

    # report_eligible must be True
    assert res.get("report_eligible") is True


@pytest.mark.asyncio
async def test_database_query_failure_safety():
    """When a database query fails during execution, must return safe explanation and NO generic Route 3 report."""
    with patch("app.db.query", side_effect=Exception("Simulated PostgreSQL connection failure or syntax error")):
        res = await chat_module.chat("What was the sales volume for customer C100?", None)
        answer = res.get("answer_text", "")

        # Must give safe retrieval failure message
        assert "unable to retrieve the data for your request from the database" in answer, (
            f"Expected safe retrieval failure message, got: {answer}"
        )

        # Must NOT expose raw database internals or stack trace
        assert "Simulated PostgreSQL connection failure" not in answer

        # Must NOT return table, chart, or report
        assert res.get("table") is None, "Table must be None on database query failure"
        assert res.get("chart") is None, "Chart must be None on database query failure"
        assert res.get("report_eligible") is False, "report_eligible must be False on failure"

        # Crucial: Must NEVER return the default Route 3 report!
        assert "Route 3 had the highest" not in answer
        assert "8522.6" not in answer
