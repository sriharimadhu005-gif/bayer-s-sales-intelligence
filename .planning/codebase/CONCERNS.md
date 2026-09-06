# Technical Concerns, Debt & Risk Analysis

## 1. Data Normalization & Schema Gaps

### Unmatched SKU Abbreviations in `daily_sales`
- **Issue:** The `daily_sales` table records product dispatches using informal, abbreviated SKU names (such as `bs`, `bc`, `spt`, `kt royal`, `pure`) entered by route delivery operators.
- **Impact:** While `sku_alias_map` maps known aliases to canonical catalog products in `rate_cards`, certain sales records fail to join against `rate_cards`. In these instances, `tally_code` is `NULL` and `estimated_revenue` defaults to `0.00`.
- **Risk:** Analytical queries that join `daily_sales` to `rate_cards` to calculate monetary sales may underreport total revenue unless fallback logic or primary volume metrics (`qty_kg`) are prioritized.
- **Mitigation:** Continue expanding `sku_alias_map` and implement an automated normalization pipeline during ETL or ingestion.

---

## 2. In-Memory Session State & Scalability

### Ephemeral Process Memory in `memory.py`
- **Issue:** All chat histories, compressed context summaries, structured conversation state, and temporary generated Excel binary files are stored in global Python dictionary structures (`_conversations`, `_conversation_reports`) in RAM.
- **Impact:**
  - **Process Restart:** Any deployment or server restart wipes all active user conversation histories and invalidates outstanding report download tokens.
  - **Multi-Worker Clustering:** If FastAPI is launched with multiple worker processes (`uvicorn --workers 4`), requests for the same conversation ID routed to different workers will result in fragmented context or HTTP 404 errors during report downloads.
  - **Memory Footprint:** Accumulation of large generated workbook byte buffers in RAM could create memory leaks under continuous high usage without aggressive TTL pruning.
- **Mitigation:** Transition conversation histories and temporary report blobs to an external cache (e.g., Redis) or persistent database tables for production enterprise deployment.

---

## 3. External AI Service Dependency

### Single LLM Provider (OpenRouter)
- **Issue:** Both the natural language data assistant (`chat.py`) and the AI report specification generator (`report_spec.py`) rely exclusively on OpenRouter routing to `qwen/qwen3-32b`.
- **Impact:** If OpenRouter encounters downtime, rate limiting, or increased latency, conversational data exploration and natural-language report configuration will fail or time out.
- **Mitigation:** Implement provider fallbacks (e.g., direct OpenAI, Anthropic, or on-premises Ollama/vLLM endpoints) with automatic retry and degradation handling.

---

## 4. Frontend Testing & Quality Gaps

### Absence of Component & End-to-End Test Automation
- **Issue:** While the backend has a 131-test security suite and the frontend benefits from TypeScript compile-time checks (`tsc -b`), there are no automated frontend unit tests (Vitest/Jest) or browser-level integration tests (Playwright/Cypress).
- **Impact:** UI state transitions (e.g., passing prefilled report parameters from Chat to Report Generator, filter reset logic, chart rendering edge cases) require manual browser verification.
- **Mitigation:** Introduce Vitest + React Testing Library for component unit tests and Playwright for critical workflow verification (Chat-to-Report flow, file download triggers).

---

## 5. Performance & Resource Constraints

### In-Memory OpenPyXL Workbook Generation
- **Issue:** `openpyxl` builds the spreadsheet document model entirely in memory. While well-suited for typical sales reports (thousands of rows), processing massive unfiltered historical datasets (>50,000 rows) could increase memory utilization and CPU execution time.
- **Mitigation:** Enforce date range and row limits on export queries, or adopt `openpyxl.workbook.Workbook(write_only=True)` for raw tabular dumps exceeding standard analytical thresholds.

### Connection Pool Sizing
- **Issue:** `backend/app/db.py` uses `SimpleConnectionPool(minconn=2, maxconn=10)`.
- **Impact:** In high-concurrency environments, requests may experience connection starvation if pool capacity is exhausted.
- **Mitigation:** Upgrade to `ThreadedConnectionPool` or connect through an enterprise connection pooler such as PgBouncer.

---

## 6. Access Control & Authentication

### Unauthenticated Internal API Surface
- **Issue:** FastAPI endpoints currently lack token authentication (JWT, OAuth2, or session cookies) and CORS allows all origins (`allow_origins=["*"]`).
- **Context:** The system is presently structured for evaluation and internal network deployment.
- **Mitigation:** Integrate corporate identity provider (Azure AD / Okta / SAML) before exposing the dashboard outside secure intranet environments.
