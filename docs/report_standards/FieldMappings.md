# Database Field Mappings & Query Specification: BDE Performance Report

## Document Control
- **Document ID:** FM-BDE-001
- **Associated SOP:** SOP-BDE-001 (`BDE_Report.md`)
- **Target Schema:** PostgreSQL (`horeca_sales_db`)
- **Application:** SQL Generation Engine, Data Extraction Pipeline

---

## 1. Schema Overview & Relational Entities

The BDE Performance Report draws upon both transactional sales tables and daily route financial summaries:

```
[ customers ] (customer_id PK, route_number, credit_limit, credit_balance)
     ▲
     │ 1:N
[ daily_sales ] (sale_date, route_number, customer_id FK, sku_name, qty_kg)
     │
     │ SKU JOIN
[ rate_cards / sku_alias_map ] (sku_name, category = 'Coffee' | 'Tea')

[ daily_route_summary ] (summary_date, route_number, customer_id FK, cash, credit, closing_balance)
```

---

## 2. Direct Field Mapping Matrix

| Report Section | Report Field | Column | Source Table / View | SQL Expression / Logic |
| :--- | :--- | :---: | :--- | :--- |
| **Section 1** | Prev Month Count | C | `daily_sales` | `COUNT(DISTINCT customer_id)` where `sale_date` in $M_{-1}$ |
| **Section 1** | Current Month Count | D | `daily_sales` | `COUNT(DISTINCT customer_id)` where `sale_date` in $M_0$ AND `customer_id` IN (cohort of $M_{-1}$) |
| **Section 1** | Target Overdue | H | `bde_route_targets` / config | Overdue recovery quota assigned per route |
| **Section 1** | Current Overdue | I | `daily_route_summary` | `SUM(credit)` or `SUM(cash)` collected against overdue balance in $M_0$ |
| **Section 2** | Coffee Target | C | `bde_route_targets` / config | Coffee volume target (KG) per route |
| **Section 2** | Coffee Achieved | D | `daily_sales` + `rate_cards` | `SUM(qty_kg)` where `category = 'Coffee'` in $M_0$ |
| **Section 2** | Tea Target | F | `bde_route_targets` / config | Tea volume target (KG) per route |
| **Section 2** | Tea Achieved | G | `daily_sales` + `rate_cards` | `SUM(qty_kg)` where `category = 'Tea'` in $M_0$ |
| **Section 3** | Target Regain Cust | C | `bde_route_targets` / config | Regain target count per route |
| **Section 3** | Regain Achieved | D | `daily_sales` + `customers` | `COUNT(DISTINCT customer_id)` who purchased in $M_0$, existed prior to $M_0$, but had 0 orders in $M_{-1}$ |
| **Section 3** | Target New Customers | G | `bde_route_targets` / config | New account quota per route |
| **Section 3** | Target New Qty | H | `bde_route_targets` / config | New account volume quota (KG) |
| **Section 3** | New Cust Achieved | I | `daily_sales` + `customers` | `COUNT(DISTINCT customer_id)` whose earliest recorded sale date is within $M_0$ |
| **Section 3** | New Cust Achieved Qty| J | `daily_sales` + `customers` | `SUM(qty_kg)` for transactions by New Customers in $M_0$ |

---

## 3. Canonical SQL Extraction Pipeline

The following parameterized SQL query extracts all 7 routes in a single efficient execution:

```sql
WITH params AS (
    -- Configure reporting period: Current Month (M0) and Previous Month (M-1)
    SELECT 
        DATE_TRUNC('month', :report_date::DATE)::DATE AS m0_start,
        (:report_date::DATE) AS m0_end,
        (DATE_TRUNC('month', :report_date::DATE) - INTERVAL '1 month')::DATE AS m_prev_start,
        (DATE_TRUNC('month', :report_date::DATE) - INTERVAL '1 day')::DATE AS m_prev_end
),
routes AS (
    SELECT generate_series(1, 7) AS route_number
),
prev_month_customers AS (
    -- Unique active customers in previous calendar month
    SELECT 
        s.route_number,
        s.customer_id
    FROM daily_sales s
    CROSS JOIN params p
    WHERE s.sale_date BETWEEN p.m_prev_start AND p.m_prev_end
    GROUP BY s.route_number, s.customer_id
),
prev_month_counts AS (
    SELECT 
        route_number,
        COUNT(DISTINCT customer_id) AS prev_count
    FROM prev_month_customers
    GROUP BY route_number
),
curr_month_sales AS (
    -- All sales in current month to date
    SELECT 
        s.route_number,
        s.customer_id,
        s.qty_kg,
        COALESCE(r.category, 'Other') AS category,
        s.sale_date
    FROM daily_sales s
    CROSS JOIN params p
    LEFT JOIN rate_cards r ON LOWER(TRIM(s.sku_name)) = LOWER(TRIM(r.sku_name))
    WHERE s.sale_date BETWEEN p.m0_start AND p.m0_end
),
retention_counts AS (
    -- Customers from prev month cohort who purchased in current month
    SELECT 
        c.route_number,
        COUNT(DISTINCT c.customer_id) AS retained_count
    FROM curr_month_sales c
    INNER JOIN prev_month_customers pm 
        ON c.route_number = pm.route_number 
       AND c.customer_id = pm.customer_id
    GROUP BY c.route_number
),
category_volumes AS (
    -- Section 2: Coffee & Tea Achieved Volumes (KG)
    SELECT 
        route_number,
        COALESCE(SUM(CASE WHEN category = 'Coffee' OR category ILIKE '%coffee%' THEN qty_kg ELSE 0 END), 0) AS coffee_achieved_kg,
        COALESCE(SUM(CASE WHEN category = 'Tea' OR category ILIKE '%tea%' THEN qty_kg ELSE 0 END), 0) AS tea_achieved_kg
    FROM curr_month_sales
    GROUP BY route_number
),
first_sale_ever AS (
    -- Detect first purchase date per customer to identify new accounts
    SELECT 
        customer_id,
        MIN(sale_date) AS first_sale_date
    FROM daily_sales
    GROUP BY customer_id
),
new_customer_activity AS (
    -- Section 3: New Customers (first purchase ever occurs in M0)
    SELECT 
        c.route_number,
        COUNT(DISTINCT c.customer_id) AS new_cust_achieved_nos,
        COALESCE(SUM(c.qty_kg), 0) AS new_cust_achieved_kg
    FROM curr_month_sales c
    INNER JOIN first_sale_ever f ON c.customer_id = f.customer_id
    CROSS JOIN params p
    WHERE f.first_sale_date >= p.m0_start
    GROUP BY c.route_number
),
regain_activity AS (
    -- Section 3: Regains (purchased in M0, first sale prior to M0, but 0 sales in M-1)
    SELECT 
        c.route_number,
        COUNT(DISTINCT c.customer_id) AS regain_achieved_nos
    FROM curr_month_sales c
    INNER JOIN first_sale_ever f ON c.customer_id = f.customer_id
    CROSS JOIN params p
    WHERE f.first_sale_date < p.m0_start
      AND c.customer_id NOT IN (SELECT customer_id FROM prev_month_customers)
    GROUP BY c.route_number
),
overdue_collections AS (
    -- Section 1: Overdue Recovery Collections from Daily Route Summary
    SELECT 
        drs.route_number,
        COALESCE(SUM(drs.cash), 0) AS current_collected_inr
    FROM daily_route_summary drs
    CROSS JOIN params p
    WHERE drs.summary_date BETWEEN p.m0_start AND p.m0_end
    GROUP BY drs.route_number
)
-- Unified Assembly for Routes 1 to 7
SELECT 
    r.route_number,
    -- Section 1: Retention & Overdue
    COALESCE(pmc.prev_count, 0) AS prev_month_count,
    COALESCE(rc.retained_count, 0) AS current_month_count,
    COALESCE(oc.current_collected_inr, 0) AS current_overdue_collected,
    -- Section 2: Product Volumes
    ROUND(COALESCE(cv.coffee_achieved_kg, 0)::NUMERIC, 1) AS coffee_achieved_kg,
    ROUND(COALESCE(cv.tea_achieved_kg, 0)::NUMERIC, 1) AS tea_achieved_kg,
    -- Section 3: Customer Acquisition
    COALESCE(ra.regain_achieved_nos, 0) AS regain_achieved_nos,
    COALESCE(nca.new_cust_achieved_nos, 0) AS new_cust_achieved_nos,
    ROUND(COALESCE(nca.new_cust_achieved_kg, 0)::NUMERIC, 1) AS new_cust_achieved_kg
FROM routes r
LEFT JOIN prev_month_counts pmc ON r.route_number = pmc.route_number
LEFT JOIN retention_counts rc ON r.route_number = rc.route_number
LEFT JOIN category_volumes cv ON r.route_number = cv.route_number
LEFT JOIN new_customer_activity nca ON r.route_number = nca.route_number
LEFT JOIN regain_activity ra ON r.route_number = ra.route_number
LEFT JOIN overdue_collections oc ON r.route_number = oc.route_number
ORDER BY r.route_number ASC;
```

---

## 4. Target Baseline Configuration & Fallbacks

In enterprise environments where target quotas reside in an external database table or config file, the system references `bde_targets`. When dynamic quotas are absent, the engine applies the official operational targets recorded in the canonical specification:

```python
DEFAULT_BDE_TARGETS = {
    1: {"overdue": 350000, "coffee_kg": 9387, "tea_kg": 4511, "regain_nos": 28, "new_nos": 5, "new_kg": 200},
    2: {"overdue": 950000, "coffee_kg": 10770, "tea_kg": 5863, "regain_nos": 23, "new_nos": 8, "new_kg": 250},
    3: {"overdue": 850000, "coffee_kg": 12689, "tea_kg": 6551, "regain_nos": 23, "new_nos": 10, "new_kg": 300},
    4: {"overdue": 750000, "coffee_kg": 11323, "tea_kg": 7200, "regain_nos": 35, "new_nos": 10, "new_kg": 300},
    5: {"overdue": 50000,  "coffee_kg": 6234,  "tea_kg": 3252, "regain_nos": 20, "new_nos": 5, "new_kg": 150},
    6: {"overdue": 550000, "coffee_kg": 10717, "tea_kg": 6077, "regain_nos": 22, "new_nos": 8, "new_kg": 250},
    7: {"overdue": 300000, "coffee_kg": 3389,  "tea_kg": 2845, "regain_nos": 0,  "new_nos": 7, "new_kg": 200},
}
```
*(Note: These defaults serve as configurable baselines. The AI reporting engine populates target columns from database query parameters or config tables, ensuring no hardcoding in the execution logic).*
