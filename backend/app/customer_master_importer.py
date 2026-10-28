"""
Authoritative Customer Master Importer & Validator.

Imports customer master workbook (e.g., 'Bean app and Tally Code.xlsx')
into the dedicated `customer_master` table.

Guarantees:
- Validates expected fields: 'Name', 'Customer ID', optional 'Tally Code'.
- Treats 'Customer ID' as required; logs and safely handles missing IDs.
- Stores missing/blank 'Tally Code' as NULL, never as an empty string.
- Preserves customer names as supplied, while storing a normalized name.
- Stops safely on invalid rows or conflicts where the same customer ID maps to different names/Tally IDs.
- Does NOT silently merge duplicate names with different customer IDs.
- Repeatable and idempotent: re-running does not create duplicates or erase existing Tally IDs.
- Returns comprehensive summary: inserted, updated, unchanged, skipped, conflicts.
"""

from __future__ import annotations

import os
import re
import sys
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import openpyxl
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Ensure console supports UTF-8 characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

logger = logging.getLogger("customer_master_importer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def get_write_connection():
    """Create a write-capable connection for database operations."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "horeca_sales_db"),
    )


def normalize_customer_name(name: str | None) -> str:
    """Normalize customer name for robust, case-insensitive, punctuation-free matching."""
    if not name:
        return ""
    s = str(name).lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class ValidatedRow:
    customer_id: str
    customer_name: str
    normalized_name: str
    tally_id: str | None
    route_number: int | None
    phone: str | None
    address: str | None
    bill_transfer: bool
    credit_limit: Decimal
    credit_balance: Decimal
    source_file: str
    source_sheet: str
    row_num: int


@dataclass
class InvalidRow:
    source_sheet: str
    row_num: int
    raw_data: dict[str, Any]
    reason: str


@dataclass
class ConflictRecord:
    customer_id: str
    existing_entry: dict[str, Any]
    conflicting_entry: dict[str, Any]
    details: str


@dataclass
class ValidationReport:
    total_rows_scanned: int = 0
    valid_rows: list[ValidatedRow] = field(default_factory=list)
    invalid_rows: list[InvalidRow] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    duplicate_names: dict[str, list[str]] = field(default_factory=dict)
    sheet_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return len(self.conflicts) == 0 and len(self.invalid_rows) == 0


@dataclass
class ImportSummary:
    total_rows_scanned: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    conflicts: int = 0
    validation_report: Optional[ValidationReport] = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows_scanned": self.total_rows_scanned,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "duplicate_names_count": len(self.validation_report.duplicate_names) if self.validation_report else 0,
        }


def validate_workbook(file_path: str) -> ValidationReport:
    """
    Validate customer master workbook before database modification.
    
    Checks:
    1. Sheet headers contain 'Customer ID' and 'Name'.
    2. 'Customer ID' is present and non-empty for every row.
    3. Blank Tally Codes are converted to None (NULL).
    4. Detects conflicts where same Customer ID maps to differing names or Tally IDs.
    5. Discovers duplicate names mapped to distinct Customer IDs.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Customer master workbook not found at: {file_path}")

    filename = os.path.basename(file_path)
    wb = openpyxl.load_workbook(file_path, data_only=True)
    report = ValidationReport()

    seen_customer_ids: dict[str, ValidatedRow] = {}
    name_to_ids: dict[str, set[str]] = {}

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        raw_headers = rows[0]
        header_map: dict[str, int] = {}
        for idx, h in enumerate(raw_headers):
            if h is None:
                continue
            h_str = str(h).strip().lower()
            if "customer" in h_str and "id" in h_str:
                header_map["customer_id"] = idx
            elif h_str in ["cust id", "cust_id", "cid"]:
                header_map["customer_id"] = idx
            elif "tally" in h_str:
                header_map["tally_id"] = idx
            elif h_str in ["name", "customer name", "customer_name"]:
                header_map["name"] = idx
            elif "phone" in h_str or "contact" in h_str:
                header_map["phone"] = idx
            elif "address" in h_str:
                header_map["address"] = idx
            elif "bill" in h_str and "transfer" in h_str:
                header_map["bill_transfer"] = idx
            elif "credit" in h_str and "limit" in h_str:
                header_map["credit_limit"] = idx
            elif "credit" in h_str and "balance" in h_str:
                header_map["credit_balance"] = idx
            elif "route" in h_str:
                header_map["route_number"] = idx

        # Validate required columns
        if "customer_id" not in header_map or "name" not in header_map:
            raise ValueError(
                f"Sheet '{sheet_name}' in '{filename}' is missing required columns. "
                f"Found headers: {[str(h) for h in raw_headers if h is not None]}"
            )

        # Default route from sheet name if sheet is e.g. 'R1', 'R2'
        default_route = None
        route_match = re.search(r"R\s*([1-7])", sheet_name, re.IGNORECASE)
        if route_match:
            default_route = int(route_match.group(1))

        sheet_row_count = 0
        for row_idx, row in enumerate(rows[1:], start=2):
            # Check if row is entirely empty
            if not any(cell is not None and str(cell).strip() != "" for cell in row):
                continue

            report.total_rows_scanned += 1
            sheet_row_count += 1

            raw_cid = row[header_map["customer_id"]] if "customer_id" in header_map and header_map["customer_id"] < len(row) else None
            raw_name = row[header_map["name"]] if "name" in header_map and header_map["name"] < len(row) else None
            raw_tally = row[header_map["tally_id"]] if "tally_id" in header_map and header_map["tally_id"] < len(row) else None
            raw_phone = row[header_map["phone"]] if "phone" in header_map and header_map["phone"] < len(row) else None
            raw_addr = row[header_map["address"]] if "address" in header_map and header_map["address"] < len(row) else None
            raw_bt = row[header_map["bill_transfer"]] if "bill_transfer" in header_map and header_map["bill_transfer"] < len(row) else None
            raw_cl = row[header_map["credit_limit"]] if "credit_limit" in header_map and header_map["credit_limit"] < len(row) else None
            raw_cb = row[header_map["credit_balance"]] if "credit_balance" in header_map and header_map["credit_balance"] < len(row) else None
            raw_route = row[header_map["route_number"]] if "route_number" in header_map and header_map["route_number"] < len(row) else None

            # 1. Check required Customer ID
            if raw_cid is None or str(raw_cid).strip() == "":
                report.invalid_rows.append(
                    InvalidRow(
                        source_sheet=sheet_name,
                        row_num=row_idx,
                        raw_data={"name": raw_name, "tally_code": raw_tally, "customer_id": raw_cid},
                        reason="Missing required Customer ID",
                    )
                )
                logger.warning(
                    "Invalid row [%s:Row %d]: Missing required Customer ID (Name='%s', Tally='%s')",
                    sheet_name, row_idx, raw_name, raw_tally
                )
                continue

            # 2. Check Name
            if raw_name is None or str(raw_name).strip() == "":
                report.invalid_rows.append(
                    InvalidRow(
                        source_sheet=sheet_name,
                        row_num=row_idx,
                        raw_data={"name": raw_name, "tally_code": raw_tally, "customer_id": raw_cid},
                        reason="Missing customer Name",
                    )
                )
                logger.warning(
                    "Invalid row [%s:Row %d]: Missing customer Name (Customer ID='%s')",
                    sheet_name, row_idx, raw_cid
                )
                continue

            cid_clean = str(raw_cid).strip()
            name_clean = str(raw_name).strip()
            norm_name = normalize_customer_name(name_clean)

            # 3. Clean Tally Code: store missing/blank as None (NULL), never as empty string
            tally_clean: str | None = None
            if raw_tally is not None:
                t_str = str(raw_tally).strip()
                if t_str and t_str.lower() not in ["none", "null", "nan", "-"]:
                    tally_clean = t_str

            # Parse route
            route_val = default_route
            if raw_route is not None:
                try:
                    route_val = int(raw_route)
                except (ValueError, TypeError):
                    pass

            # Parse phone & address
            phone_clean = str(raw_phone).strip() if raw_phone is not None and str(raw_phone).strip() else None
            addr_clean = str(raw_addr).strip() if raw_addr is not None and str(raw_addr).strip() else None

            # Parse bill transfer
            bill_transfer_val = False
            if raw_bt is not None:
                bt_str = str(raw_bt).strip().lower()
                bill_transfer_val = bt_str in ["true", "1", "yes", "t", "y"]

            # Parse credit limit / balance
            def parse_dec(val: Any) -> Decimal:
                if val is None or str(val).strip() in ["", "-", "nan", "null"]:
                    return Decimal("0.00")
                try:
                    return Decimal(str(val).strip())
                except Exception:
                    return Decimal("0.00")

            v_row = ValidatedRow(
                customer_id=cid_clean,
                customer_name=name_clean,
                normalized_name=norm_name,
                tally_id=tally_clean,
                route_number=route_val,
                phone=phone_clean,
                address=addr_clean,
                bill_transfer=bill_transfer_val,
                credit_limit=parse_dec(raw_cl),
                credit_balance=parse_dec(raw_cb),
                source_file=filename,
                source_sheet=sheet_name,
                row_num=row_idx,
            )

            # 4. Conflict detection: same Customer ID mapping to different names or different non-null Tally IDs
            if cid_clean in seen_customer_ids:
                prev = seen_customer_ids[cid_clean]
                name_conflict = (prev.normalized_name != norm_name)
                tally_conflict = (
                    prev.tally_id is not None
                    and tally_clean is not None
                    and prev.tally_id.lower() != tally_clean.lower()
                )
                if name_conflict or tally_conflict:
                    conflict_desc = []
                    if name_conflict:
                        conflict_desc.append(f"Name mismatch: '{prev.customer_name}' vs '{name_clean}'")
                    if tally_conflict:
                        conflict_desc.append(f"Tally mismatch: '{prev.tally_id}' vs '{tally_clean}'")

                    conflict = ConflictRecord(
                        customer_id=cid_clean,
                        existing_entry={
                            "sheet": prev.source_sheet,
                            "row": prev.row_num,
                            "name": prev.customer_name,
                            "tally_id": prev.tally_id,
                        },
                        conflicting_entry={
                            "sheet": sheet_name,
                            "row": row_idx,
                            "name": name_clean,
                            "tally_id": tally_clean,
                        },
                        details="; ".join(conflict_desc),
                    )
                    report.conflicts.append(conflict)
                    logger.error("Conflict detected for ID '%s': %s", cid_clean, conflict.details)
            else:
                seen_customer_ids[cid_clean] = v_row

            # 5. Track duplicate names across different customer IDs
            name_to_ids.setdefault(norm_name, set()).add(cid_clean)
            report.valid_rows.append(v_row)

        report.sheet_counts[sheet_name] = sheet_row_count

    # Compile duplicate names that map to > 1 distinct Customer ID
    for n_name, ids in name_to_ids.items():
        if len(ids) > 1:
            report.duplicate_names[n_name] = sorted(list(ids))

    return report


def import_customer_master(
    file_path: str,
    stop_on_conflict: bool = True,
    safe_skip_invalid: bool = True,
) -> ImportSummary:
    """
    Import customer master workbook into database.
    
    Guarantees idempotency and non-destructive upserts:
    - Re-running the same workbook creates 0 duplicate master records.
    - Upserts by customer_id.
    - Updates Tally ID only when the workbook provides a non-empty value.
    - Never erases an existing Tally ID if the workbook cell is blank.
    - Produces a detailed ImportSummary (inserted, updated, unchanged, skipped, conflicts).
    """
    report = validate_workbook(file_path)
    summary = ImportSummary(
        total_rows_scanned=report.total_rows_scanned,
        skipped=len(report.invalid_rows),
        conflicts=len(report.conflicts),
        validation_report=report,
    )

    if report.conflicts and stop_on_conflict:
        msg = f"Import stopped safely: {len(report.conflicts)} conflicting Customer ID mapping(s) detected in workbook."
        logger.error(msg)
        summary.errors.append(msg)
        return summary

    if report.invalid_rows and not safe_skip_invalid:
        msg = f"Import stopped: {len(report.invalid_rows)} invalid row(s) detected with safe_skip_invalid=False."
        logger.error(msg)
        summary.errors.append(msg)
        return summary

    conn = get_write_connection()
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Fetch all existing records in customer_master to determine insert vs update vs unchanged
            cur.execute("""
                SELECT 
                    customer_id, customer_name, normalized_name, tally_id,
                    route_number, phone, address, bill_transfer, credit_limit, credit_balance
                FROM customer_master;
            """)
            existing_db_records = {row["customer_id"]: dict(row) for row in cur.fetchall()}

            for row in report.valid_rows:
                cid = row.customer_id
                existing = existing_db_records.get(cid)

                if existing is None:
                    # Brand new record -> INSERT
                    cur.execute("""
                        INSERT INTO customer_master (
                            customer_id, customer_name, normalized_name, tally_id,
                            route_number, phone, address, bill_transfer, credit_limit,
                            credit_balance, source_file, source_sheet, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                        );
                    """, (
                        row.customer_id,
                        row.customer_name,
                        row.normalized_name,
                        row.tally_id,
                        row.route_number,
                        row.phone,
                        row.address,
                        row.bill_transfer,
                        row.credit_limit,
                        row.credit_balance,
                        row.source_file,
                        row.source_sheet,
                    ))
                    # Add to local map so repeated rows in workbook don't double count
                    existing_db_records[cid] = {
                        "customer_id": row.customer_id,
                        "customer_name": row.customer_name,
                        "normalized_name": row.normalized_name,
                        "tally_id": row.tally_id,
                        "route_number": row.route_number,
                        "phone": row.phone,
                        "address": row.address,
                        "bill_transfer": row.bill_transfer,
                        "credit_limit": row.credit_limit,
                        "credit_balance": row.credit_balance,
                    }
                    summary.inserted += 1
                else:
                    # Existing record -> evaluate whether fields change or if Tally ID should be updated
                    # Rule: Update Tally ID only when the workbook provides a value.
                    # Do not erase an existing Tally ID because the source cell is blank.
                    effective_tally_id = row.tally_id if row.tally_id is not None else existing.get("tally_id")
                    effective_route = row.route_number if row.route_number is not None else existing.get("route_number")
                    effective_phone = row.phone if row.phone is not None else existing.get("phone")
                    effective_addr = row.address if row.address is not None else existing.get("address")
                    effective_bt = row.bill_transfer if row.bill_transfer is not None else existing.get("bill_transfer")
                    effective_cl = row.credit_limit if row.credit_limit is not None else existing.get("credit_limit")
                    effective_cb = row.credit_balance if row.credit_balance is not None else existing.get("credit_balance")

                    # Check if anything changed
                    is_changed = (
                        existing.get("customer_name") != row.customer_name
                        or existing.get("normalized_name") != row.normalized_name
                        or existing.get("tally_id") != effective_tally_id
                        or existing.get("route_number") != effective_route
                        or existing.get("phone") != effective_phone
                        or existing.get("address") != effective_addr
                        or existing.get("bill_transfer") != effective_bt
                        or (existing.get("credit_limit") is not None and Decimal(str(existing.get("credit_limit"))) != effective_cl)
                        or (existing.get("credit_balance") is not None and Decimal(str(existing.get("credit_balance"))) != effective_cb)
                    )

                    if is_changed:
                        cur.execute("""
                            UPDATE customer_master SET
                                customer_name = %s,
                                normalized_name = %s,
                                tally_id = %s,
                                route_number = %s,
                                phone = %s,
                                address = %s,
                                bill_transfer = %s,
                                credit_limit = %s,
                                credit_balance = %s,
                                source_file = %s,
                                source_sheet = %s,
                                updated_at = NOW()
                            WHERE customer_id = %s;
                        """, (
                            row.customer_name,
                            row.normalized_name,
                            effective_tally_id,
                            effective_route,
                            effective_phone,
                            effective_addr,
                            effective_bt,
                            effective_cl,
                            effective_cb,
                            row.source_file,
                            row.source_sheet,
                            cid,
                        ))
                        # Update local dict
                        existing_db_records[cid]["customer_name"] = row.customer_name
                        existing_db_records[cid]["normalized_name"] = row.normalized_name
                        existing_db_records[cid]["tally_id"] = effective_tally_id
                        existing_db_records[cid]["route_number"] = effective_route
                        existing_db_records[cid]["phone"] = effective_phone
                        existing_db_records[cid]["address"] = effective_addr
                        existing_db_records[cid]["bill_transfer"] = effective_bt
                        existing_db_records[cid]["credit_limit"] = effective_cl
                        existing_db_records[cid]["credit_balance"] = effective_cb
                        summary.updated += 1
                    else:
                        summary.unchanged += 1

            conn.commit()
            logger.info(
                "Import completed successfully: scanned=%d, inserted=%d, updated=%d, unchanged=%d, skipped=%d, conflicts=%d",
                summary.total_rows_scanned, summary.inserted, summary.updated, summary.unchanged, summary.skipped, summary.conflicts
            )

    except Exception as e:
        conn.rollback()
        logger.error("Import failed with exception: %s", e)
        summary.errors.append(str(e))
        raise
    finally:
        conn.close()

    return summary


def main():
    """CLI runner for customer master import."""
    default_excel = r"C:\Users\sriha\Downloads\Srihari_Horeca\Ajay_Horeca\Bean app and Tally Code.xlsx"
    excel_path = sys.argv[1] if len(sys.argv) > 1 else default_excel

    print("=" * 70)
    print("HORECA SALES INTELLIGENCE: CUSTOMER MASTER IMPORT")
    print("=" * 70)
    print(f"Target workbook: {excel_path}\n")

    print("1. Running validation...")
    try:
        report = validate_workbook(excel_path)
    except Exception as e:
        print(f"Validation failed: {e}")
        sys.exit(1)

    print(f"  - Total non-empty rows scanned: {report.total_rows_scanned}")
    print(f"  - Valid customer rows: {len(report.valid_rows)}")
    print(f"  - Invalid rows detected: {len(report.invalid_rows)}")
    for inv in report.invalid_rows:
        print(f"    * [{inv.source_sheet}:Row {inv.row_num}] {inv.reason} (Data: {inv.raw_data})")
    print(f"  - Conflicting customer ID mappings: {len(report.conflicts)}")
    for c in report.conflicts:
        print(f"    * [Conflict ID {c.customer_id}]: {c.details}")
    print(f"  - Duplicate customer names across distinct IDs: {len(report.duplicate_names)}")
    for d_name, ids in report.duplicate_names.items():
        print(f"    * '{d_name}' -> Customer IDs: {ids}")

    print("\n2. Executing idempotent import into customer_master...")
    summary = import_customer_master(excel_path, stop_on_conflict=True, safe_skip_invalid=True)

    print("\n" + "=" * 70)
    print("IMPORT EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Scanned:   {summary.total_rows_scanned}")
    print(f"Inserted:  {summary.inserted}")
    print(f"Updated:   {summary.updated}")
    print(f"Unchanged: {summary.unchanged}")
    print(f"Skipped:   {summary.skipped}")
    print(f"Conflicts: {summary.conflicts}")
    if summary.errors:
        print(f"Errors:    {summary.errors}")
    print("=" * 70)


if __name__ == "__main__":
    main()
