# Authoritative Customer Master: Setup, Import & Resolution Guide

## 1. Overview

The `customer_master` table serves as the primary, authoritative source of customer records, IDs, and Tally codes for the Horeca Sales Intelligence System. It imports customer records directly from:

`Bean app and Tally Code.xlsx`

All customer lookup and resolution logic across the chatbot, API layer, and report generator follows a strict **4-tier priority**:

1. **Tier 1:** `customer_master` exact customer-ID / customer-name match
2. **Tier 2:** `customer_master` normalized-name match, only if unambiguous
3. **Tier 3:** Existing price-sheet (`rate_cards`) customer ID as fallback
4. **Tier 4:** Return "customer ID not found" without inventing or guessing a value

---

## 2. Database Schema

The `customer_master` table schema:

```sql
CREATE TABLE IF NOT EXISTS customer_master (
    customer_id          VARCHAR(50)  PRIMARY KEY,
    customer_name        VARCHAR(255) NOT NULL,
    normalized_name      VARCHAR(255) NOT NULL,
    tally_id             VARCHAR(50),  -- NULL if blank/missing, never empty string
    route_number         INTEGER,
    phone                VARCHAR(50),
    address              TEXT,
    bill_transfer        BOOLEAN      DEFAULT FALSE,
    credit_limit         NUMERIC(12,2) DEFAULT 0,
    credit_balance       NUMERIC(12,2) DEFAULT 0,
    source_file          VARCHAR(255),
    source_sheet         VARCHAR(50),
    created_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

Indexes:
- `idx_customer_master_norm_name` on `normalized_name`
- `idx_customer_master_name_trgm` GIN trigram index on `LOWER(customer_name)`
- `idx_customer_master_tally_id` on `tally_id`
- `idx_customer_master_route` on `route_number`

---

## 3. Running Migrations

To apply database migrations:

```powershell
# From backend directory
cd backend
.\venv\Scripts\python.exe migrations/run_migrations.py
```

Applied migrations are tracked in `schema_migrations` and are completely idempotent:
- `001_create_customer_master.sql`: Creates `customer_master` table and indexes.
- `002_update_views_with_customer_master.sql`: Updates `vw_customer_sales_analytics`, `vw_daily_financial_summary`, and `vw_route_sku_breakdown` to prioritize `customer_master` for customer names, routes, addresses, and Tally codes.

---

## 4. Running the Customer Master Import

The import script performs workbook validation, conflict detection, duplicate name analysis, and an idempotent upsert:

```powershell
# Default path (uses Bean app and Tally Code.xlsx)
cd backend
.\venv\Scripts\python.exe -m app.customer_master_importer

# Or specify a custom file path:
.\venv\Scripts\python.exe -m app.customer_master_importer "C:\path\to\Bean app and Tally Code.xlsx"
```

### Import Rules & Guarantees:
- **Customer ID Required:** Rows without a customer ID are logged with sheet name, row number, and skipped safely (e.g. Sheet R1 Row 66: *Hot Coffee - Mahalakshmi Layout*).
- **Tally Code Null Handling:** Blank or whitespace Tally Codes are stored as SQL `NULL`, never as empty strings (`""`).
- **Idempotency:** Re-running the import on the same file does not create duplicate rows (`inserted: 0, unchanged: 782`).
- **Tally Code Preservation:** If a record already possesses a Tally ID in the database, re-running with a blank workbook cell does **not** erase the existing Tally ID (`COALESCE(new_tally, existing_tally)`).
- **Duplicate Name Safety:** Duplicate customer names with distinct Customer IDs (e.g., *sri vishnu park* -> `C1382` and `C1559`) are kept distinct and never merged.
- **Price-Sheet Data Preservation:** Existing price sheets (`rate_cards`), standard rates (`standard_rate_cards`), and sales data (`daily_sales`) are strictly preserved and never modified, overwritten, or deleted.

---

## 5. Running Automated Tests

Run the full customer master test suite:

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest tests/test_customer_master.py -v
```

All 17 automated tests cover:
- Workbook parsing and row validation
- Safe skipping and logging of missing customer IDs
- NULL Tally Code handling (zero empty strings)
- Duplicate name discovery and non-merging
- Idempotency and Tally ID preservation
- Strict 4-tier customer resolution and disambiguation
- Non-destructive integrity checks for `rate_cards` and `daily_sales`
