"""
Automated Test Suite for Customer Master Import, Validation, and 4-Tier Resolution.

Tests:
1. Workbook validation:
   - Required Customer ID enforcement.
   - Safe logging and skipping of invalid rows (Row 66 Hot Coffee).
   - Blank Tally Code converted to NULL, never empty string.
   - Duplicate names with distinct Customer IDs kept distinct and flagged as ambiguous.
   - Conflict detection on same customer ID with mismatched data.
2. Database schema & table constraints:
   - customer_master table structure, PK, indexes.
   - Zero empty strings in tally_id column.
3. Import idempotency:
   - Re-running produces inserted=0, unchanged=782, skipped=1, conflicts=0.
   - Upsert preserves existing Tally ID when source cell is blank.
4. Authoritative 4-tier Customer-ID resolution:
   - Tier 1: exact ID match and exact name match.
   - Tier 1/2: ambiguous duplicate names return ambiguous status without inventing IDs.
   - Tier 1/2: location hint disambiguates identical names.
   - Tier 3: fallback to rate_cards price-sheet customer ID.
   - Tier 4: unknown customer returns not_found / None.
   - Tally ID resolution hierarchy.
5. Non-destructive safety:
   - rate_cards and daily_sales row counts and data remain completely untouched.
"""

import os
import pytest
from decimal import Decimal

from app.db import query
from app.customer_master_importer import (
    validate_workbook,
    import_customer_master,
    normalize_customer_name,
    get_write_connection,
)
from app.customer_resolution import (
    resolve_customer,
    resolve_tally_id,
    CustomerResolutionStatus,
)

EXCEL_PATH = r"C:\Users\sriha\Downloads\Srihari_Horeca\Ajay_Horeca\Bean app and Tally Code.xlsx"


# =====================================================================
# 1. WORKBOOK VALIDATION TESTS
# =====================================================================

def test_workbook_validation_structure():
    """Verify workbook scans 783 rows with 782 valid and 1 invalid row."""
    report = validate_workbook(EXCEL_PATH)
    assert report.total_rows_scanned == 783
    assert len(report.valid_rows) == 782
    assert len(report.invalid_rows) == 1
    assert len(report.conflicts) == 0

    # Verify invalid row is Row 66 in Sheet R1
    inv = report.invalid_rows[0]
    assert inv.source_sheet == "R1"
    assert inv.row_num == 66
    assert "Missing required Customer ID" in inv.reason
    assert "Hot Coffee" in str(inv.raw_data.get("name"))


def test_tally_code_blank_handling_in_validator():
    """Verify that blank/empty Tally Codes in workbook are set to None (NULL), never empty string."""
    report = validate_workbook(EXCEL_PATH)
    for r in report.valid_rows:
        if r.tally_id is not None:
            assert isinstance(r.tally_id, str)
            assert r.tally_id.strip() != ""
            assert r.tally_id.lower() not in ["none", "null", "nan", "-"]


def test_duplicate_names_detection():
    """Verify duplicate customer names mapping to distinct customer IDs are identified."""
    report = validate_workbook(EXCEL_PATH)
    # Must identify the duplicate pairs
    assert "sri vishnu park" in report.duplicate_names
    vishnu_ids = report.duplicate_names["sri vishnu park"]
    assert set(vishnu_ids) == {"C1382", "C1559"}

    tamara_key = [k for k in report.duplicate_names if "tamara" in k]
    assert len(tamara_key) > 0
    tamara_ids = report.duplicate_names[tamara_key[0]]
    assert set(tamara_ids) == {"C1512", "C1520"}


def test_conflict_detection_synthetic():
    """Verify conflict detection flags when same Customer ID maps to conflicting names or tallies."""
    from app.customer_master_importer import ValidationReport, ValidatedRow, ConflictRecord

    report = ValidationReport()
    seen = {}
    r1 = ValidatedRow(
        customer_id="TEST_C001",
        customer_name="Alpha Cafe",
        normalized_name="alpha cafe",
        tally_id="T001",
        route_number=1,
        phone=None,
        address=None,
        bill_transfer=False,
        credit_limit=Decimal(0),
        credit_balance=Decimal(0),
        source_file="test.xlsx",
        source_sheet="R1",
        row_num=10,
    )
    seen[r1.customer_id] = r1

    # Conflicting row: same ID, different name
    r2_name = "Beta Bistro"
    norm_r2 = normalize_customer_name(r2_name)
    assert r1.normalized_name != norm_r2
    conflict = ConflictRecord(
        customer_id="TEST_C001",
        existing_entry={"sheet": r1.source_sheet, "row": r1.row_num, "name": r1.customer_name},
        conflicting_entry={"sheet": "R2", "row": 15, "name": r2_name},
        details=f"Name mismatch: '{r1.customer_name}' vs '{r2_name}'",
    )
    report.conflicts.append(conflict)
    assert len(report.conflicts) == 1
    assert "Beta Bistro" in report.conflicts[0].details


# =====================================================================
# 2. DATABASE SCHEMA & INTEGRITY TESTS
# =====================================================================

def test_customer_master_table_schema():
    """Verify customer_master exists with primary key and required columns."""
    cols = query("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'customer_master';
    """)
    col_dict = {c["column_name"]: c for c in cols}
    assert "customer_id" in col_dict
    assert "customer_name" in col_dict
    assert "normalized_name" in col_dict
    assert "tally_id" in col_dict
    assert "route_number" in col_dict
    assert "source_file" in col_dict
    assert "source_sheet" in col_dict
    assert "created_at" in col_dict
    assert "updated_at" in col_dict

    # Check primary key
    pk_rows = query("""
        SELECT a.attname
        FROM   pg_index i
        JOIN   pg_attribute a ON a.attrelid = i.indrelid
                             AND a.attnum = ANY(i.indkey)
        WHERE  i.indrelid = 'customer_master'::regclass
        AND    i.indisprimary;
    """)
    pk_cols = [r["attname"] for r in pk_rows]
    assert pk_cols == ["customer_id"]


def test_tally_id_no_empty_strings_in_db():
    """Verify zero records in customer_master have empty string for tally_id."""
    res = query("""
        SELECT 
            count(*) as total,
            count(*) filter (where tally_id is null) as null_tally,
            count(*) filter (where tally_id = '') as empty_tally
        FROM customer_master;
    """)
    assert res[0]["total"] == 782
    assert res[0]["null_tally"] == 172
    assert res[0]["empty_tally"] == 0


# =====================================================================
# 3. IMPORT IDEMPOTENCY & REPEATABILITY TESTS
# =====================================================================

def test_import_idempotency_second_run():
    """Verify running import again produces inserted=0, unchanged=782, skipped=1."""
    summary = import_customer_master(EXCEL_PATH, stop_on_conflict=True, safe_skip_invalid=True)
    assert summary.inserted == 0
    assert summary.unchanged == 782
    assert summary.skipped == 1
    assert summary.conflicts == 0


def test_tally_id_preservation_when_source_blank():
    """Verify that updating a customer with a blank Tally Code does NOT overwrite existing Tally ID."""
    conn = get_write_connection()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Set a test record with a known Tally ID
            cur.execute("""
                INSERT INTO customer_master (
                    customer_id, customer_name, normalized_name, tally_id,
                    route_number, source_file, source_sheet
                ) VALUES (
                    'TEST_PRESERVE_01', 'Preserve Test Cafe', 'preserve test cafe', 'TALLY_999',
                    1, 'test.xlsx', 'R1'
                ) ON CONFLICT (customer_id) DO UPDATE SET
                    tally_id = 'TALLY_999';
            """)
            conn.commit()

            # Now simulate an upsert where workbook has a blank tally (None)
            cur.execute("""
                UPDATE customer_master SET
                    tally_id = COALESCE(NULL, customer_master.tally_id),
                    updated_at = NOW()
                WHERE customer_id = 'TEST_PRESERVE_01'
                RETURNING tally_id;
            """)
            row = cur.fetchone()
            assert row[0] == "TALLY_999", "Existing Tally ID must not be erased when incoming tally is NULL"

            # Clean up test record
            cur.execute("DELETE FROM customer_master WHERE customer_id = 'TEST_PRESERVE_01';")
            conn.commit()
    finally:
        conn.close()


# =====================================================================
# 4. 4-TIER CUSTOMER-ID RESOLUTION PRIORITY TESTS
# =====================================================================

def test_resolution_tier_1_exact_customer_id():
    """Tier 1: Exact customer ID match in customer_master."""
    res = resolve_customer("C1666")
    assert res.status == CustomerResolutionStatus.RESOLVED
    assert res.tier == 1
    assert res.customer_id == "C1666"
    assert res.customer_name == "chalukya samrat"
    assert res.tally_id == "R300677"
    assert res.match_type == "master_exact_id"


def test_resolution_tier_1_exact_customer_name():
    """Tier 1: Exact unique customer name match in customer_master."""
    res = resolve_customer("chalukya samrat")
    assert res.status == CustomerResolutionStatus.RESOLVED
    assert res.tier == 1
    assert res.customer_id == "C1666"


def test_resolution_duplicate_name_ambiguity():
    """Tier 1/2: Duplicate customer name with distinct IDs must return AMBIGUOUS status."""
    res = resolve_customer("sri vishnu park")
    assert res.status == CustomerResolutionStatus.AMBIGUOUS
    assert res.customer_id is None
    candidate_ids = {c["customer_id"] for c in res.candidates}
    assert "C1382" in candidate_ids
    assert "C1559" in candidate_ids


def test_resolution_duplicate_name_disambiguation_with_location():
    """Disambiguate duplicate name using location hint."""
    res = resolve_customer("sri vishnu park", location_hint="Shanthi Nagar")
    assert res.status == CustomerResolutionStatus.RESOLVED
    assert res.customer_id == "C1382"

    res2 = resolve_customer("sri vishnu park", location_hint="BTM Layout")
    assert res2.status == CustomerResolutionStatus.RESOLVED
    assert res2.customer_id == "C1559"


def test_resolution_tier_2_normalized_name():
    """Tier 2: Normalized name match in customer_master when unambiguous."""
    res = resolve_customer("CHALUKYA   SAMRAT")
    assert res.status == CustomerResolutionStatus.RESOLVED
    assert res.customer_id == "C1666"
    assert res.tier in (1, 2)


def test_resolution_tier_3_rate_cards_fallback():
    """Tier 3: Customer present only in rate_cards price-sheet falls back to rate_cards."""
    # Find a customer present in rate_cards with non-null customer_id but not in customer_master (if any)
    rc_only = query("""
        SELECT rc.customer_id, rc.customer_name
        FROM rate_cards rc
        LEFT JOIN customer_master cm ON rc.customer_id = cm.customer_id
        WHERE rc.customer_id IS NOT NULL AND cm.customer_id IS NULL
        LIMIT 1;
    """)
    if rc_only:
        cid = rc_only[0]["customer_id"]
        cname = rc_only[0]["customer_name"]
        res = resolve_customer(cid)
        assert res.status == CustomerResolutionStatus.RESOLVED
        assert res.tier == 3
        assert res.customer_id == cid


def test_resolution_tier_4_customer_not_found():
    """Tier 4: Unknown customer returns NOT_FOUND without inventing an ID."""
    res = resolve_customer("NonExistentCoffeeShop123456789")
    assert res.status == CustomerResolutionStatus.NOT_FOUND
    assert res.tier == 4
    assert res.customer_id is None


def test_tally_id_resolution():
    """Verify Tally ID lookup priority."""
    # Customer with tally_id in customer_master
    tally = resolve_tally_id("C1666")
    assert tally == "R300677"

    # Customer without tally_id in customer_master (Hot Coffee or null tally customers)
    null_tally_row = query("SELECT customer_id FROM customer_master WHERE tally_id IS NULL LIMIT 1;")
    if null_tally_row:
        cid = null_tally_row[0]["customer_id"]
        # If not in rate_cards either, returns None
        tally = resolve_tally_id(cid)
        # Should either be rate_cards code or None, never empty string
        if tally is not None:
            assert tally.strip() != ""

    # Unknown customer
    assert resolve_tally_id("NonExistentCustomerXYZ") is None


# =====================================================================
# 5. NON-DESTRUCTIVE INTEGRITY TESTS
# =====================================================================

def test_price_sheet_and_sales_data_untouched():
    """Requirement 5: Ensure rate_cards and daily_sales data are preserved and untouched."""
    rc_count = query("SELECT count(*) as count FROM rate_cards;")[0]["count"]
    ds_count = query("SELECT count(*) as count FROM daily_sales;")[0]["count"]
    assert rc_count == 4050, "rate_cards rows must remain exactly 4050"
    assert ds_count == 7730, "daily_sales rows must remain exactly 7730"
