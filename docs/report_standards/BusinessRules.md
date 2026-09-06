# Business Rules & Decision Logic: BDE Performance Report

## Document Control
- **Document ID:** BR-BDE-001
- **Associated SOP:** SOP-BDE-001 (`BDE_Report.md`)
- **Authoritative Reference:** Reverse-engineered from `4.BDE Report.xlsx`
- **Application:** AI Instruction Layer & Report Generation Engine

---

## 1. Section 1: Customer Retention & SLA Management

### 1.1 The 93% Retention SLA Benchmark
In the Horeca coffee and tea distribution model, an ongoing customer account typically places weekly or bi-weekly orders. A monthly customer retention rate of **93% (0.93)** represents the mandatory operational threshold. 
- Any route operating below 93% is experiencing account leakage that threatens territory route density.
- Cell **E2** in the canonical specification records this threshold as `0.93`.

### 1.2 Retention Calculations
For any given Route $i$:
1. **Previous Month Count ($C_i$):** Total count of unique active customers who made at least one recorded purchase in the preceding calendar month.
2. **Current Month Count ($D_i$):** Total count of unique customers from the previous month's active cohort who made at least one recorded purchase during the current month-to-date period.
3. **Retention Percentage ($E_i$):**
   $$\text{Retention \%} = \frac{D_i}{C_i}$$
   *(Cell Formula: `=+D5/C5`)*

4. **Retention Balance ($F_i$):**
   $$\text{Retention Balance} = \operatorname{ROUNDUP}\left((E_i - 0.93) \times C_i, 0\right)$$
   *(Cell Formula: `=ROUNDUP((E5-0.93)*C5,0)`)*

### 1.3 Mathematical Equivalence & Interpretation of Retention Balance
Expanding the formula reveals the exact business meaning:
$$(E_i - 0.93) \times C_i = \left(\frac{D_i}{C_i} - 0.93\right) \times C_i = D_i - 0.93 \times C_i$$
- **$0.93 \times C_i$** is the **Target Retained Customer Count** needed to hit the 93% SLA.
- **$D_i - 0.93 \times C_i$** is the **Account Variance**.
- **Negative Balance (e.g. -28):** Deficit. The BDE is short by 28 retained accounts. At least 28 dormant accounts must re-order before month-end to satisfy the SLA.
- **Zero Balance (0):** Exactly on the 93% benchmark.
- **Positive Balance (e.g. +14):** Surplus. The route has retained more accounts than the minimum 93% target.
- **Rounding Convention:** Excel's `ROUNDUP(..., 0)` rounds away from zero. This ensures that any fractional deficit (e.g., -27.2 accounts) is rounded to a full customer account (-28 accounts), because partial customer accounts cannot exist.

### 1.4 Aggregation Rule for Retention
- **Total Prev Month Count (C12):** `=SUM(C5:C11)`
- **Total Current Month Count (D12):** `=SUM(D5:D11)`
- **Portfolio Retention Percentage (E12):** `=+D12/C12`
  - **CRITICAL RULE:** Portfolio retention must NEVER be computed as the average of route percentages (`AVERAGE(E5:E11)`). It must be the weighted ratio of total active customers to total previous customers.
- **Total Retention Balance (F12):** `=SUM(F5:F11)`
  - *Template Anomaly Note:* In the original sample workbook, cell F12 contained `=SUM(F5:F10)`, accidentally omitting Route 7 due to human formula drag error. The canonical business standard is `=SUM(F5:F11)`.

---

## 2. Section 1: Outstanding Overdue Collection Management

### 2.1 Strategic Context
Customer credit in Horeca is strictly managed. BDEs are not merely sales personnel; they are accountable for credit collections on their routes.

### 2.2 Calculations & Definitions
1. **Target ($H_i$):** The monthly recovery target in INR for overdue accounts assigned to Route $i$.
2. **Current ($I_i$):** The actual INR amount collected or recovered against overdue balances month-to-date.
3. **Balance ($J_i$):**
   $$\text{Overdue Balance} = I_i - H_i$$
   *(Cell Formula: `=+I5-H5`)*
- **Negative Balance:** Shortfall against recovery target (e.g., Target 350,000, Collected 0 $\rightarrow$ Balance -350,000).
- **Zero Balance:** Recovery target met 100%.
- **Positive Balance:** Over-recovery (collected more overdue arrears than targeted).

---

## 3. Section 2: Product Volume Performance (Coffee & Tea)

### 3.1 Separation of Coffee and Tea
- **Coffee (Columns C-E):** Premium, high-margin SKU family. Tracked in kilograms (KG).
- **Tea (Columns F-H):** Fast-moving, high-volume SKU family. Tracked in kilograms (KG).
- Separation prevents product cannibalization where a sales rep satisfies overall tonnage solely through lower-margin tea.

### 3.2 Volume Formulas
For each Route $i$:
1. **Coffee Balance ($E_i$):** `=+D{r}-C{r}` ($\text{Achieved} - \text{Target}$)
2. **Tea Balance ($H_i$):** `=+G{r}-F{r}` ($\text{Achieved} - \text{Target}$)
3. **Total Target ($I_i$):** `=+C{r}+F{r}` ($\text{Coffee Target} + \text{Tea Target}$)
4. **Total Achieved ($J_i$):** `=+D{r}+G{r}` ($\text{Coffee Achieved} + \text{Tea Achieved}$)
5. **Total Balance ($K_i$):** `=+J{r}-I{r}` ($\text{Total Achieved} - \text{Total Target}$)
6. **Total Achievement Percentage ($L_i$):** `=+J{r}/I{r}` ($\text{Total Achieved} / \text{Total Target}$)

### 3.3 Variance Interpretation
- **Negative Balance:** Shortfall in kilograms against budget.
- **Positive Balance:** Surplus volume sold over budget.
- **Portfolio Totals (Row 24):** All Target, Achieved, and Balance columns use `=SUM(...)`. Column L uses the weighted portfolio ratio `=+J24/I24`.

---

## 4. Section 3: Customer Acquisition (Regain & New Customers)

### 4.1 Account Classification Logic
The business distinguishes sharply between reactivating lost accounts and acquiring completely new accounts:

```
                  +----------------------------------------------+
                  | Customer Placed Order in Current Month       |
                  +----------------------+-----------------------+
                                         |
            +----------------------------+----------------------------+
            |                                                         |
[Account Existed in System Prior to Current Month]        [Account Created in Current Month]
            |                                                         |
Was active in previous month?                                         |
   - YES: Counts in Section 1 (Retention D)                           |
   - NO:  Counts in Section 3 (Regain D)                 Counts in Section 3 (New Customers I & J)
```

1. **Regained Account:**
   - A customer account whose record already existed in `customers`, but had **zero orders in the preceding calendar month**.
   - Placed at least one order in the current reporting month.
   - Represents successfully recovered churn.

2. **New Account:**
   - An account onboarded during the current reporting period (first order date occurs in current month).
   - Tracked across two dimensions:
     - **Headcount (Nos):** Number of distinct accounts opened.
     - **Quantity (KGs):** Total volume consumed by these new accounts.

### 4.2 Acquisition Formulas
1. **Regain Balance ($E_i$):** `=+D{r}-C{r}` ($\text{Achieved Regains} - \text{Target Regains}$)
2. **New Customers Balance in Nos ($K_i$):** `=+I{r}-G{r}` ($\text{Achieved Nos} - \text{Target Nos}$)
3. **New Customers Balance in Kgs ($L_i$):** `=+J{r}-H{r}` ($\text{Achieved KG} - \text{Target KG}$)

### 4.3 Missing / Unassigned Targets Handling
In the canonical workbook, certain cells (e.g. Route 7 Target Regain $C35$) were left blank because no formal quota was set for that route.
- **Rule:** If a target is blank or null in the database, treat the target as `0` for variance calculations, or display a blank cell if required by corporate convention. The formula `=+D35-C35` seamlessly handles blank cells in Excel (evaluating blank as 0).

---

## 5. Edge Cases & Anomaly Handling

| Scenario | Condition | System Behavior / Formula Guardrail |
| :--- | :--- | :--- |
| **Zero Previous Month Customers** | $C_i = 0$ | If a route is newly opened with no prior month history, formula must avoid `#DIV/0!`. The engine outputs `=IF(C5>0, D5/C5, 0)`. |
| **Zero Current Month Customers** | $D_i = 0$ | Retention % evaluates to `0.00%`. Retention Balance equals `ROUNDUP(-0.93 * C_i, 0)` (maximum deficit). |
| **Zero Target Volume** | $I_i = 0$ | Total % formula evaluates to `=IF(I17>0, J17/I17, 0)` to prevent `#DIV/0!`. |
| **Route Inactivity** | No sales recorded on route | Route row must still be rendered (Routes 1-7 are persistent). Values are 0, formulas remain intact. |
| **Negative Sales Values** | Returns / Credit notes | Included in aggregate net volume. Net KG may reduce achieved totals. |
| **Duplicate Route Codes** | Multiple records for Route $i$ | All transactions must be aggregated by `route_number` before population. Exactly one row per route (1 to 7). |
