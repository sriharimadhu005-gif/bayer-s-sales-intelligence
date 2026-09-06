# External Systems & Integrations

## 1. Database Integration: PostgreSQL (`horeca_sales_db`)

The system integrates directly with a local or hosted PostgreSQL instance containing real-world Horeca distribution transactional data.

### Schema Architecture
- **`customers` (2,871 records):** Master customer records partitioned across Routes 1 to 7 with credit limits and current balances.
- **`daily_sales` (7,730 records):** Transactional dispatch records across Routes 1 to 7 spanning 2026-03-31 to 2026-04-15 with SKU shorthand names and quantities (KG).
- **`rate_cards` (4,050 records):** Customer-specific approved pricing tiers, GST tax brackets, and standard list prices across Coffee, Tea, Pure Coffee, and Allied products.
- **`daily_route_summary` (5,761 records):** Day-end cash collections, credit disbursements, and closing ledger balances per route per customer.
- **`daily_route_sku_details` (8,250 records):** Detailed line-item SKU dispatches by route and account.
- **`customer_equipment` (37 records):** Brewing machines, grinders, and brass filters issued to customer accounts.
- **`sku_alias_map`:** Normalization map bridging abbreviated route shorthand (e.g., `bs`, `bc`, `spt`, `kt royal`) to canonical catalog product codes.

### Pre-Compiled Analytical Views
- `vw_customer_sales_analytics`
- `vw_daily_financial_summary`
- `vw_route_sku_breakdown`
- `vw_customer_equipment_ledger`

### Security Boundary
- Application accesses data via `psycopg2.pool.SimpleConnectionPool`.
- Enforces read-only transactions at the database connection level (`default_transaction_read_only=on`).
- Supported by a dedicated restricted database role script (`setup_readonly_user.sql`) that grants only `SELECT` privileges and revokes table/schema creation privileges.

---

## 2. LLM Provider Integration: OpenRouter

The intelligence layer delegates natural language query decomposition and report layout synthesis to open weights models via OpenRouter.

### Configuration
- **Base URL:** `https://openrouter.ai/api/v1` (configurable via `OPENROUTER_BASE_URL`).
- **Default Model:** `qwen/qwen3-32b` (configured via `OPENROUTER_MODEL`).
- **Authentication:** Bearer token passed via HTTP header `Authorization: Bearer <OPENROUTER_API_KEY>`.
- **Client Implementation:** Asynchronous non-blocking HTTP requests via `httpx.AsyncClient` with custom timeouts (60.0s).

### Subsystems Utilizing OpenRouter
1. **Natural Language Data Assistant (`backend/app/chat.py`):**
   - Step 1: LLM translates natural language questions into safe PostgreSQL analytical queries based on injected database schemas and business rules.
   - Step 2: Backend executes the validated query and feeds row data back to the LLM.
   - Step 3: LLM synthesizes natural language text explanations, data tables, and inline chart configurations (`bar`, `line`, `pie`).
2. **AI Report Spec Builder (`backend/app/report_spec.py`):**
   - Translates freeform user instructions in the report notes field (e.g., *"Create a pivot table with Customer in rows and SKU in columns and highlight top 10"*) into a structured JSON `ReportSpec` schema defining sheets, columns, sorting, filtering, pivot cross-tabs, and conditional highlighting.

---

## 3. Client-to-Backend REST API Interface

Communication between the React SPA and the FastAPI server occurs over standard HTTP JSON endpoints and binary streaming channels:

| Endpoint | Method | Payload / Params | Return Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| `/api/health` | `GET` | None | JSON | Verifies API liveliness and checks active database connection |
| `/api/meta/routes` | `GET` | None | JSON | Returns list of the 7 canonical route definitions |
| `/api/meta/skus` | `GET` | `branch` (coffee, tea, others) | JSON | Returns catalog SKUs mapped into distinct beverage branches |
| `/api/meta/customers` | `GET` | `route_ids` (comma-delimited) | JSON | Returns customer accounts mapped to chosen sales routes |
| `/api/chat` | `POST` | `{ message, conversation_id }` | JSON | Submits conversational queries to the data assistant |
| `/api/chat/{id}` | `DELETE`| Path parameter | JSON | Resets conversation session and wipes ephemeral memory |
| `/api/chat/{id}/download-report/{rid}` | `GET` | Path parameters | Binary (.xlsx) | Streams an in-memory generated workbook produced during chat |
| `/api/reports` | `POST` | `ReportRequest` JSON | Binary (.xlsx / .pdf) | Generates customized or canonical Excel/PDF workbooks |
| `/api/reports/bde` | `GET` | `as_of_date` (optional query) | Binary (.xlsx) | Directly compiles and downloads the canonical BDE Performance Report |

### Binary Streaming & Header Standards
- Excel files stream as `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- PDF files stream as `application/pdf`.
- Content disposition headers conform to RFC 5987 using both standard `filename="name"` and UTF-8 encoded `filename*=UTF-8''name` to preserve unicode characters.
- Frontend API client in `frontend/src/api/client.ts` decodes `Content-Disposition` headers using regex matchers and triggers non-intrusive blob downloads via `URL.createObjectURL`.

---

## 4. Static Hosting Integration

The FastAPI backend includes a static directory mount for unified deployment:
- When `frontend/dist` is compiled, FastAPI mounts the directory at root `/` via `fastapi.staticfiles.StaticFiles(html=True)`.
- This enables unified single-port operation where both the React frontend and API run seamlessly from port 8000 without requiring an external reverse proxy in evaluation setups.
