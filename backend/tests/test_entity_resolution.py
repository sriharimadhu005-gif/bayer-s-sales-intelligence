"""
Tests for Intelligent Entity Resolution & Clarification Pipeline.
"""

import pytest
import asyncio
from app.entity_resolution import (
    extract_candidate_mentions,
    match_customer,
    match_sku,
    evaluate_resolution,
    resolve_clarification_reply,
    ResolutionStatus,
)
from app import chat as chat_module
from app import memory as mem


def test_extract_candidate_mentions():
    # 1. Customer mention extraction
    ext1 = extract_candidate_mentions("what did guru vaibhav buy on 6-4")
    assert ext1.get("customer_mention") == "guru vaibhav"

    # 2. Customer mention with preposition
    ext2 = extract_candidate_mentions("STD price for Shanthi Sagar")
    assert ext2.get("customer_mention") == "Shanthi Sagar"

    # 3. Route mention
    ext3 = extract_candidate_mentions("which coffee sold most in route 3")
    assert ext3.get("route_mention") == 3

    # 4. Location mention
    ext4 = extract_candidate_mentions("who bought coffee in Vijayanagar")
    assert ext4.get("location_mention") == "vijayanagar"

    # 5. SKU alias mention
    ext5 = extract_candidate_mentions("what is standard price of bs")
    assert ext5.get("sku_alias") == "bs"


def test_ambiguous_customer_matching():
    """Test that generic name matching multiple branches returns AMBIGUOUS status."""
    ext = extract_candidate_mentions("STD price for Shanthi Sagar")
    res = evaluate_resolution("STD price for Shanthi Sagar", ext)
    assert res.status == ResolutionStatus.AMBIGUOUS
    assert len(res.candidates) >= 2
    assert "Which one did you mean?" in res.clarification_text
    assert res.clarification_state is not None
    assert res.clarification_state["mention"] == "Shanthi Sagar"


def test_clarification_reply_resolution():
    """Test resolving user answers to clarification questions."""
    ext = extract_candidate_mentions("STD price for Shanthi Sagar")
    res = evaluate_resolution("STD price for Shanthi Sagar", ext)
    assert res.clarification_state is not None

    # Test numeric reply "1"
    cand1 = resolve_clarification_reply("1", res.clarification_state)
    assert cand1 is not None
    assert cand1["customer_id"] == res.candidates[0]["customer_id"]

    # Test location keyword reply "RPC Layout"
    cand_rpc = resolve_clarification_reply("RPC Layout", res.clarification_state)
    assert cand_rpc is not None
    assert cand_rpc["customer_id"] == "A319"
    assert "rpc layout" in cand_rpc["name"].lower() or "rpc layout" in cand_rpc["address"].lower()


def test_single_high_confidence_customer():
    """Test that a unique customer name resolves directly without asking clarification."""
    ext = extract_candidate_mentions("what did guru vaibhav buy on 6-4")
    res = evaluate_resolution("what did guru vaibhav buy on 6-4", ext)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.resolved_customer is not None
    assert res.resolved_customer["customer_id"] == "B1098"
    assert res.resolved_customer["name"].lower() == "guru vaibhav"


def test_fuzzy_name_matching():
    """Test fuzzy matching handles missing words (e.g. 'Restaurant') and punctuation."""
    ext = extract_candidate_mentions("std rate for chalukya samrat llp- sheshadripuram for badam powder")
    res = evaluate_resolution("std rate for chalukya samrat llp- sheshadripuram for badam powder", ext)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.resolved_customer is not None
    assert res.resolved_customer["customer_id"] == "H703"
    assert "sheshadripuram" in res.resolved_customer["name"].lower()


def test_sku_alias_resolution():
    """Test SKU aliases like 'bc' and 'bs' map to canonical names and standard rates."""
    # Test 'bc' (Brownie Special) with pack size 200
    bc_matches = match_sku(mention=None, alias="bc", pack_size="200")
    assert len(bc_matches) == 1
    assert bc_matches[0]["sku_name"] == "Coffee-Brownie Special-200"
    assert bc_matches[0]["std_rate"] == 700.0

    # Test 'bs' (Cafe Supreme) with pack size 200 (both regular and SPL variants)
    bs_matches_200 = match_sku(mention=None, alias="bs", pack_size="200")
    assert len(bs_matches_200) == 2
    assert bs_matches_200[0]["sku_name"] == "Coffee-Cafe Supreme-200"
    assert bs_matches_200[0]["std_rate"] == 730.0

    # Test 'bs' without pack size returns all 4 variants
    bs_all = match_sku(mention=None, alias="bs")
    assert len(bs_all) == 4


def test_ambiguous_sku_clarification_flow():
    """Test that pricing inquiry for ambiguous SKU like 'bs' prompts clarification without guessing."""
    ext = extract_candidate_mentions("what is standard price of bs")
    res = evaluate_resolution("what is standard price of bs", ext)
    assert res.status == ResolutionStatus.AMBIGUOUS
    assert "Which one do you mean" in res.clarification_text or "Which one did you mean" in res.clarification_text
    assert res.clarification_state is not None
    assert res.clarification_state["alias"] == "bs"

    # Test resolving by option index "1"
    cand1 = resolve_clarification_reply("1", res.clarification_state)
    assert cand1 is not None
    assert cand1["sku_name"] == "Coffee-Cafe Supreme-200"
    assert cand1["std_rate"] == 730.0

    # Test resolving by pack size "500g"
    cand500 = resolve_clarification_reply("500g", res.clarification_state)
    assert cand500 is not None
    assert cand500["sku_name"] == "Coffee-Cafe Supreme-500"
    assert cand500["std_rate"] == 740.0


def test_low_confidence_handling():
    """Test that unknown customer yields low confidence guidance rather than error or hallucination."""
    ext = extract_candidate_mentions("sales for UnknownNonExistentCompanyX999")
    res = evaluate_resolution("sales for UnknownNonExistentCompanyX999", ext)
    assert res.status == ResolutionStatus.LOW_CONFIDENCE
    assert "I couldn't confidently identify" in res.clarification_text
    assert "UnknownNonExistentCompanyX999" in res.clarification_text


@pytest.mark.asyncio
async def test_multi_turn_chat_disambiguation_flow():
    """Test full conversational disambiguation in chat(): Turn 1 clarifies, Turn 2 resolves and executes."""
    conv_id = "test-disambiguation-conv"
    mem.delete_conversation(conv_id)

    # Turn 1: Ambiguous prompt
    turn1_res = await chat_module.chat("STD price for Shanthi Sagar", conv_id)
    assert "Which one did you mean?" in turn1_res["answer_text"]
    assert mem.get_pending_clarification(conv_id) is not None

    # Turn 2: User clarifies "RPC Layout"
    turn2_res = await chat_module.chat("RPC Layout", conv_id)
    assert mem.get_pending_clarification(conv_id) is None
    # Verify response contains relevant pricing or answer for RPC Layout
    ans = turn2_res["answer_text"].lower()
    assert (
        "shanthi sagar" in ans 
        or "rpc layout" in ans 
        or "price" in ans 
        or "rate" in ans 
        or turn2_res.get("table") is not None
    )
