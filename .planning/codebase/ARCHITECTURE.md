# System Architecture & Design Patterns

## 1. Architectural Overview

The **Bayer Horeca Sales Intelligence System** is an enterprise analytics platform engineered around a **Decoupled SOP Specification & Code-Engine Synthesis** pattern. Rather than coupling database queries, layout formatting, cell formulas, and business thresholds directly inside application code, the architecture separates business definitions into human-and-machine-actionable specifications.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             PRESENTATION LAYER (Vite + React 19)                 │
│  - Natural Language Chat Workspace (ChatView.tsx)                                │
│  - Parameterized & Spec-Driven Report Builder (ReportView.tsx)                   │
│  - Interactive SVG & Canvas Inline Visualizations (InlineChart.tsx)              │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │ HTTP REST / JSON / Binary Streams
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                 FASTAPI CORE (main.py)                           │
│  - Routes & SKUs Metadata Endpoints                                              │
│  - Asynchronous Session & Request Dispatchers                                    │
│  - Unified Static Asset Server                                                   │
└──────┬──────────────────────────────────┬─────────────────────────────────┬──────┘
       │                                  │                                 │
       ▼                                  ▼                                 ▼
┌───────────────────┐        ┌─────────────────────────┐        ┌──────────────────┐
│   CHAT ENGINE     │        │ AI REPORT SPEC BUILDER  │        │  CANONICAL BDE   │
│    (chat.py)      │        │    (report_spec.py)     │        │  SOP (bde_sop.py)│
└─────────┬─────────┘        └────────────┬────────────┘        └─────────┬────────┘
          │                               │                               │
          ▼                               ▼                               │
┌──────────────────────────────────────────────────────┐                  │
│               PROMPT GOVERNANCE & SECURITY           │                  │
│  - Input Screening: Injection & jailbreak detection  │                  │
│  - SQL AST Validator: sqlglot read-only gate         │                  │
│  - Audit Logger: Security event recording            │                  │
└──────────────────────────┬───────────────────────────┘                  │
                           │                                              │
                           ▼                                              │
┌──────────────────────────────────────────────────────┐                  │
│               DATABASE ACCESS LAYER (db.py)          │                  │
│  - psycopg2 SimpleConnectionPool                     │                  │
│  - Enforced Session-Level Read-Only Transactions     │                  │
└──────────────────────────┬───────────────────────────┘                  │
                           │                                              │
                           ▼                                              │
┌──────────────────────────────────────────────────────┐                  │
│               POSTGRESQL (horeca_sales_db)           │                  │
│  - Tables: customers, daily_sales, rate_cards, etc.  │                  │
│  - Views: vw_customer_sales_analytics, etc.          │                  │
└──────────────────────────┬───────────────────────────┘                  │
                           │ Row Data                                     │
                           ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            DOCUMENT COMPILATION ENGINES                          │
│  - OpenPyXL Workbook Builder (reports.py & bde_sop.py)                           │
│    - Tabular, cross-tab pivot, summary KPIs, dynamic formulas (SUM, AVERAGE)     │
│  - ReportLab PDF Engine (reports.py)                                             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Decoupled SOP & 4-Tier Reporting Pipeline

The reporting subsystem implements a four-tier architecture separating business standards from compilation:

### Tier 1: Canonical Specification Layer (`docs/report_standards/`)
- Pure Markdown documents containing business context, target formulas, row coordinates, field mappings, and styling palettes:
  - `BDE_Report.md`: Operational targets, scorecard layouts, and metric definitions.
  - `BusinessRules.md`: Retention thresholds, SLA targets, and calculation logic.
  - `FormulaReference.md`: Exact dynamic Excel formulas (`SUM`, `AVERAGE`) and cell coordinate mappings.
  - `FieldMappings.md`: Canonical database queries and route normalization rules.
  - `FormattingGuide.md`: Hex color palettes, zebra banding standards, and border weights.

### Tier 2: AI Instruction & Intent Layer (`backend/app/bde_sop.py`)
- Reads and caches markdown specifications dynamically at runtime.
- Injects authoritative context into LLM system prompts without hardcoding strings in Python code.
- Evaluates user intent to route requests between standard tabular exports, AI-driven custom layouts, and canonical SOP builds.

### Tier 3: Data & Security Layer (`backend/app/db.py` & `security/`)
- Executes deterministic aggregation SQL or LLM-generated queries across Routes 1 to 7.
- Guards against prompt injections, role escalation, data mutation, and unauthorized database operations.

### Tier 4: Document Generation Layer (`backend/app/reports.py`)
- Emits real, executable Microsoft Excel spreadsheets containing live formulas rather than static values.
- Implements custom XML namespace adjustments for gridlines, auto-sized columns, top-N highlighting, and multi-tab routing.

---

## 3. Conversational AI Assistant Architecture

The chat engine (`backend/app/chat.py`) operates as a closed-loop query-and-synthesis agent:

1. **Pre-LLM Screening:** The user prompt is evaluated by `screen_prompt` for prompt injection, jailbreaking, or role escalation attempts. Malicious prompts trigger an immediate safe refusal.
2. **Context Assembly:** `backend/app/memory.py` retrieves the session history, structured working state (current report, last query, last table), and compresses long histories when approaching token limits (budgeting up to 20,000 tokens).
3. **Query Generation:** The LLM generates a JSON payload containing an analytical SQL query against the documented schema and analytical views.
4. **AST Validation:** The SQL is parsed with `sqlglot` (with regex fallback) in `validate_sql` to guarantee only `SELECT` / `WITH...SELECT` statements are executed.
5. **Database Execution:** The validated SQL executes via `db.query()`.
6. **Synthesis:** The retrieved dataset is returned to the LLM, which produces natural language explanations, formatted data tables, inline charts, and prefill payloads for the report generator.
7. **Ephemeral Storage:** If an Excel workbook is synthesized during the conversation, it is saved in memory under the conversation ID and exposed via a short-lived download token.

---

## 4. Multi-Layer Defense-in-Depth Security

Security is designed with 4 complementary, independent boundaries:

| Layer | Component | Mechanism |
| :--- | :--- | :--- |
| **1. Application Gateway** | `prompt_governance.py` | Regex pattern matching + linguistic token scanning for prompt injections, secret exfiltration, and role-override attacks. |
| **2. Query Inspection** | `sql_validator.py` | AST parsing via `sqlglot` prohibiting DDL/DML, multi-statement queries, dynamic SQL, system tables, and Postgres execution functions (`pg_sleep`, `lo_import`). |
| **3. Connection Boundary** | `db.py` | Connection pool defaults every checked-out connection to `default_transaction_read_only=on`. |
| **4. Database Privileges** | `setup_readonly_user.sql` | Role-based access control (RBAC) granting only `SELECT` on schemas and tables; write privileges are revoked. |
