# Report Generation Workflow: BDE Performance Report

## Document Control
- **Document ID:** RGF-BDE-001
- **Associated SOP:** SOP-BDE-001 (`BDE_Report.md`)
- **Pipeline Type:** AI-Orchestrated End-to-End Excel Compilation
- **Application:** Backend API (`/api/reports/bde`, `/api/chat`), LLM Instruction Layer

---

## 1. End-to-End Pipeline Overview

The generation of a BDE Performance Report transitions through nine deterministic phases. At no point does the engine rely on static templates or cached spreadsheets; the entire workbook is synthesized on demand from live transactional database tables:

```
[1. User Request] ──► [2. Intent Detection] ──► [3. SOP Documentation Injection]
                                                             │
[6. Business Logic & SLAs] ◄── [5. Data Validation] ◄── [4. SQL Data Extraction]
        │
        ▼
[7. Dynamic Workbook Assembly] ──► [8. Pixel-Perfect Styler] ──► [9. Binary Delivery & UI Card]
```

---

## 2. Phase-by-Phase Execution Details

### Phase 1: User Request Parsing
- **Inputs:** Natural language prompt via chat (e.g. *"Generate the BDE report for April 15"*, *"Can you give me the route BDE performance scorecard?"*) or direct API invocation with parameters `{ "report_type": "bde", "as_of_date": "2026-04-15" }`.
- **Parameter Resolution:**
  - `report_date`: Defaults to latest transactional date in `daily_sales` if unspecified.
  - `reporting_period`: Computes current month start ($M_0$), previous month start and end ($M_{-1}$).

### Phase 2: Report Type Resolution & Dispatch
- The AI router screens the user intent. If keywords match `["bde", "route performance", "bde report", "retention scorecard"]`, the system classifies the request as `BDE_PERFORMANCE_REPORT`.
- Redirects execution to the dedicated canonical BDE generator pipeline rather than a generic flat table.

### Phase 3: AI Instruction Layer Loading
- The engine loads the canonical specification from `docs/report_standards/`:
  - `BDE_Report.md` (structure)
  - `BusinessRules.md` (93% SLA, deficit/surplus logic)
  - `FormulaReference.md` (exact cell coordinates and formula syntax)
  - `FieldMappings.md` (SQL queries)
- The documentation acts as the runtime system prompt for the model, ensuring absolute adherence to corporate standards.

### Phase 4: SQL Data Extraction
- The backend executes the parameterized extraction query documented in `FieldMappings.md`.
- Gathers for Routes 1 through 7:
  - Previous month active customer counts ($C_i$).
  - Current month retained customer counts ($D_i$).
  - Overdue collections ($I_i$).
  - Coffee achieved volume ($D_i$ in Sec 2).
  - Tea achieved volume ($G_i$ in Sec 2).
  - Regained customer accounts ($D_i$ in Sec 3).
  - New customer accounts ($I_i$ in Sec 3) and New customer volume ($J_i$ in Sec 3).
  - Target quotas for Overdue, Coffee, Tea, Regain, and New Accounts.

### Phase 5: Data Integrity Validation
Before writing to Excel, the validator executes sanity checks:
1. **Completeness Check:** All 7 routes must exist. If any route has null data, initialize with `0`.
2. **Non-Negative Baseline:** Previous month counts must be $\ge 0$. If $C_i = 0$, flag route as "New Territory" to prevent division by zero.
3. **Category Sanity:** Verify that Coffee + Tea accounts for $>90\%$ of core beverage tonnage.

### Phase 6: Application of Business Rules & Formulas
- Set cell `E2` = `0.93`.
- Prepare the exact formula strings for Excel cells:
  - Retention: `=+D{r}/C{r}` and `=ROUNDUP((E{r}-0.93)*C{r},0)`.
  - Overdue Balance: `=+I{r}-H{r}`.
  - Coffee/Tea Balance: `=+D{r}-C{r}`, `=+G{r}-F{r}`.
  - Total Volume & %: `=+C{r}+F{r}`, `=+D{r}+G{r}`, `=+J{r}-I{r}`, `=+J{r}/I{r}`.
  - Customer Acquisition: `=+D{r}-C{r}`, `=+I{r}-G{r}`, `=+J{r}-H{r}`.
  - Summary Totals: `=SUM(...)` and weighted ratios `=+D12/C12`, `=+J24/I24`.

### Phase 7: Workbook Generation (OpenPyXL)
- Create workbook in memory: `wb = openpyxl.Workbook()`.
- Set active sheet title (e.g. `01-09` or `Performance Report`).
- Populate header blocks, static labels, fetched metrics, and dynamic formula strings into their designated coordinates ($B1$ through $L36$).

### Phase 8: Visual Styling & Formatting
- Apply column widths and row heights per `FormattingGuide.md`.
- Merge the 10 canonical cell ranges (`B3:B4`, `C3:F3`, etc.).
- Apply Section 1 soft olive pastel fill (`#E2EFDA`) to `C3:F12` and `H3:J12`.
- Apply thin solid borders and center alignment across all data cells.
- Set number formats: `0.00%` for retention, `0%` for volume achievement, currency format for overdue columns.
- Ensure gridlines are visible (`ws.views.sheetView[0].showGridLines = True`).

### Phase 9: Response Delivery
- **File Output:** Save workbook to an in-memory byte buffer (`io.BytesIO`) and write to `output/BDE_Performance_Report_<date>.xlsx`.
- **API Response:** Return downloadable binary stream with header `Content-Disposition: attachment; filename="BDE_Report.xlsx"`.
- **Chat Synthesis:** Present an interactive markdown summary table highlighting key executive metrics (Portfolio Retention %, Total Volume KG, Overdue Recovery) with a direct download link.
