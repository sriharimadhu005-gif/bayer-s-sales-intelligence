import pytest
import asyncio
from app import db
from app import chat
from app import entity_resolution
from app.chat import auto_heal_text_matching

def test_auto_heal_text_matching_transforms_eq_to_ilike():
    assert "sku_name ILIKE 'bc'" in auto_heal_text_matching("SELECT * FROM daily_sales WHERE sku_name = 'bc';")
    assert "sku_name ILIKE 'BC'" in auto_heal_text_matching("SELECT * FROM daily_sales WHERE sku_name = 'BC';")
    assert "customer_name ILIKE 'Shanthi Sagar'" in auto_heal_text_matching("SELECT * FROM customers WHERE customer_name = 'Shanthi Sagar';")
    assert "customer_id ILIKE 'A292'" in auto_heal_text_matching("SELECT * FROM customers WHERE customer_id = 'A292';")
    assert "product_code ILIKE 'bc'" in auto_heal_text_matching("SELECT * FROM sku_family_master WHERE product_code = 'bc';")

def test_auto_heal_preserves_numeric_and_dates():
    sql = "SELECT * FROM daily_sales WHERE qty_kg = 50.0 AND sale_date = '2026-04-10' AND route_number = 3;"
    assert auto_heal_text_matching(sql) == sql

def test_auto_heal_handles_lower_upper():
    assert "name ILIKE 'Shanthi Sagar'" in auto_heal_text_matching("SELECT * FROM customers WHERE LOWER(name) = LOWER('Shanthi Sagar');")
    assert "customer_name ILIKE '%shanthi sagar%'" in auto_heal_text_matching("SELECT * FROM customers WHERE LOWER(customer_name) LIKE LOWER('%shanthi sagar%');")

def test_case_insensitive_bc_in_database():
    # Database has 'bc' in daily_sales and 'BC' in sku_family_master
    res_lower = db.query(auto_heal_text_matching("SELECT SUM(qty_kg) AS total_kg FROM daily_sales WHERE sku_name = 'bc';"))
    assert res_lower and res_lower[0]["total_kg"] is not None

    res_upper = db.query(auto_heal_text_matching("SELECT SUM(qty_kg) AS total_kg FROM daily_sales WHERE sku_name = 'BC';"))
    assert res_upper and res_upper[0]["total_kg"] is not None
    assert res_lower[0]["total_kg"] == res_upper[0]["total_kg"]

    # In sku_family_master, stored as 'BC'
    res_fam_lower = db.query(auto_heal_text_matching("SELECT product_name FROM sku_family_master WHERE product_code = 'bc';"))
    assert res_fam_lower and res_fam_lower[0]["product_name"] == "coffee-brownie special-200"

    res_fam_upper = db.query(auto_heal_text_matching("SELECT product_name FROM sku_family_master WHERE product_code = 'BC';"))
    assert res_fam_upper and res_fam_upper[0]["product_name"] == "coffee-brownie special-200"

def test_input_normalization():
    # Accidental whitespace and repeated spaces
    messy_name = "  Shanthi   Sagar  "
    clean_name = "Shanthi Sagar"
    cands_messy = entity_resolution.match_customer(messy_name)
    cands_clean = entity_resolution.match_customer(clean_name)
    assert len(cands_messy) == len(cands_clean)
    assert [c["customer_id"] for c in cands_messy] == [c["customer_id"] for c in cands_clean]

def test_candidate_disambiguation_for_ambiguous_customer():
    # Shanthi Sagar has multiple branches across routes
    extracted = entity_resolution.extract_candidate_mentions("Give me sales for Shanthi Sagar")
    res = entity_resolution.evaluate_resolution("Give me sales for Shanthi Sagar", extracted)
    assert res.status == entity_resolution.ResolutionStatus.AMBIGUOUS
    assert "Which one did you mean?" in res.clarification_text
    assert len(res.candidates) > 1

def test_empty_result_candidate_recovery():
    # Test recovery when exact query returns empty
    fake_sql = "SELECT * FROM customers WHERE customer_name ILIKE 'Shanthi Sagar';"
    recovered_rows, clarif_resp, final_sql = chat._recover_or_clarify_empty_query(fake_sql, "sales for Shanthi Sagar", "test-rec-conv")
    # Should catch multiple candidates and present clarification rather than saying it doesn't exist
    assert clarif_resp is not None
    assert "Which one did you mean?" in clarif_resp["answer_text"]
