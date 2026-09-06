# Standard Operating Procedure: BDE Performance Report (SOP-BDE-001)

## Document Control
- **Document ID:** SOP-BDE-001
- **Document Title:** Standard Operating Procedure for Business Development Executive (BDE) Performance Reporting
- **Canonical Specification Source:** `4.BDE Report.xlsx`
- **Target Audience:** Regional Sales Managers, Commercial Directors, Operations Leads, AI Reporting Agent
- **Reporting Cadence:** Snapshot-based / MTD (Month-To-Date) tracking at Day 1, Day 20, Day 25, and Month-End (01 / 01-09)
- **Scope:** Route operations across all distribution territories (Routes 1 through 7)

---

## 1. Executive Summary & Purpose

The **BDE Performance Report** is the definitive operational scorecard used by commercial leadership to monitor the performance of Business Development Executives (BDEs) assigned to specific distribution routes (Routes 1 to 7).

The report provides a unified view of three interdependent sales disciplines:
1. **Customer Health & Financial Stewardship:** Are active customer relationships being maintained, and are overdue credit accounts being recovered according to targets?
2. **Core Category Volume Delivery:** Are sales volume targets for high-margin Coffee and volume-driving Tea being achieved on each route?
3. **Territory Expansion & Account Acquisition:** Are lost/dormant accounts being regained, and are new accounts being acquired with viable volume?

By synthesizing retention, collections, volume performance, and customer acquisition into a single 36-row matrix, the system allows management to pinpoint underperforming routes, balance workloads, and enforce commercial accountability.

---

## 2. Report Structure & Anatomical Breakdown

Every BDE Performance Report adheres strictly to a standardized 3-section layout structured over 36 rows and 12 columns (Columns B through L, with Column A reserved as a spacer).

```
+-------------------------------------------------------------------------------------------------------+
| Row 1-2:   Header & Baseline Configuration [Performance Report | SLA Threshold 93%]                   |
+-------------------------------------------------------------------------------------------------------+
| Section 1: Retention & Outstanding Overdue (Rows 3-12)                                                |
|            - Prev Month vs Current Month Active Customer Counts                                       |
|            - Retention % and Retention Balance (vs 93% benchmark)                                     |
|            - Overdue Target vs Current Collected vs Overdue Balance                                   |
|            - Total Row: Weighted Retention % & Total Overdue Recovery                                 |
+-------------------------------------------------------------------------------------------------------+
| Rows 13-14: Section Separator                                                                         |
+-------------------------------------------------------------------------------------------------------+
| Section 2: Product Volume Performance - Coffee & Tea (Rows 15-24)                                    |
|            - Coffee Target (KG), Achieved (KG), Variance Balance                                      |
|            - Tea Target (KG), Achieved (KG), Variance Balance                                         |
|            - Combined Route Total: Total Target, Total Achieved, Balance, and Achievement %           |
|            - Total Row: Portfolio Volume Achievement & Target Realization                             |
+-------------------------------------------------------------------------------------------------------+
| Rows 25-26: Section Separator                                                                         |
+-------------------------------------------------------------------------------------------------------+
| Section 3: Customer Acquisition - Regain & New Accounts (Rows 27-36)                                  |
|            - Regained Accounts: Target vs Achieved vs Balance                                         |
|            - New Accounts: Target Accounts (Nos) & Target Qty (KG)                                    |
|                            Achieved Accounts (Nos) & Achieved Qty (KG)                                |
|                            Variance in Nos & Variance in KGs                                          |
|            - Total Row: Total Regains & Net Expansion Volume                                          |
+-------------------------------------------------------------------------------------------------------+
```

### Why Each Section Exists

#### Section 1: Retention & Outstanding Overdue
- **Strategic Purpose:** Prevents "churn and burn" expansion. In Horeca distribution, retaining existing hospitality accounts is 5x cheaper than acquiring new ones. Furthermore, aggressive volume delivery is worthless if credit collections fail. This section pairs customer retention directly with overdue cash recovery to enforce disciplined commercial behavior.
- **Key Indicators:** Retention Percentage, Customer Deficit against 93% benchmark, Overdue Variance.

#### Section 2: Product Volume Performance (Coffee & Tea)
- **Strategic Purpose:** Balances product mix. Coffee carries higher gross margins, while Tea drives route density and frequency of visits. Separating them prevents BDEs from hiding poor coffee sales behind bulk tea numbers.
- **Key Indicators:** Coffee Volume (KG), Tea Volume (KG), Combined Realization %.

#### Section 3: Customer Acquisition (Regain & New Customers)
- **Strategic Purpose:** Drives pipeline renewal. Accounts churn due to competitive poaching, chef changes, or temporary closures. This section tracks both **Regains** (reactivating previously lost customers) and **New Accounts** (greenfield onboarding), monitoring both account count and actual KG volume consumed.
- **Key Indicators:** Regain Achievement, New Account Count, Initial Order Volume (KG per new account).

---

## 3. Operational Rules for the AI Reporting Engine

When generating any variation of the BDE Report, the AI reporting engine must adhere to the following principles:

1. **Strict Separation of Data and Logic:**
   - Never copy values from previous sample sheets.
   - All numbers must be computed directly from database tables (`customers`, `daily_sales`, `daily_route_summary`, `rate_cards`).
2. **Formula Preservation:**
   - In the generated Excel document, calculated cells MUST contain valid Excel formulas (e.g. `=+D5/C5`, `=ROUNDUP((E5-0.93)*C5,0)`), NOT static calculated values. This ensures the output workbook remains dynamic for stakeholder inspection.
3. **Territory Completeness:**
   - Routes 1 through 7 must all be represented. If a route had zero activity during the period, it must still appear with zero counts and appropriate variance formulas rather than being omitted.
4. **Weighted Aggregations:**
   - Never average percentages across routes. Portfolio retention is `Total Current / Total Previous`. Total achievement is `Total Achieved / Total Target`.

---

## 4. Document Directory Overview

The documentation layer is organized into seven modular standards:
- **`BDE_Report.md`** *(this document)*: Master SOP and canonical specification.
- **[`BusinessRules.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/BusinessRules.md)**: Exhaustive business logic, SLA definitions, deficit vs. surplus interpretation, and edge-case behaviors.
- **[`FormulaReference.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/FormulaReference.md)**: Precise cell coordinates, mathematical formulas, and dependency chains for every cell in the 36x12 layout.
- **[`FieldMappings.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/FieldMappings.md)**: Relational database schema mapping with complete SQL CTE queries.
- **[`FormattingGuide.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/FormattingGuide.md)**: Exact styling, fonts, palette colors, borders, column widths, row heights, and OpenPyXL implementation rules.
- **[`ReportGenerationFlow.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/ReportGenerationFlow.md)**: End-to-end lifecycle from prompt interpretation to SQL dispatch and binary delivery.
- **[`Architecture.md`](file:///c:/Users/sriha/OneDrive/Desktop/bayer's%20sales%20intelligence/docs/report_standards/Architecture.md)**: AI Instruction Layer integration and dynamic SOP loader architecture.
