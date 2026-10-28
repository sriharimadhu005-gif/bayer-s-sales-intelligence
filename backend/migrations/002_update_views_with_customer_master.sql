-- Migration 002: Update analytical views to prioritize authoritative customer_master
-- Non-destructive view updates maintaining identical column data types

CREATE OR REPLACE VIEW vw_customer_sales_analytics AS
SELECT
    ds.sale_date,
    ds.route_number,
    ds.customer_id,
    COALESCE(cm.customer_name, c.name, ds.customer_name)::varchar(120) AS customer_name,
    COALESCE(cm.phone, c.phone)::varchar(30) AS phone,
    COALESCE(cm.address, c.address) AS address,
    COALESCE(cm.credit_limit, c.credit_limit) AS credit_limit,
    COALESCE(cm.credit_balance, c.credit_balance) AS credit_balance,
    ds.sku_name,
    ds.qty_kg,
    COALESCE(cm.tally_id, rc.code)::varchar(15) AS tally_code,
    COALESCE(sfm.main_group, rc.category, src.category, 'Unknown')::varchar(50) AS category,
    sfm.sub_main_group,
    sfm.sub_group,
    sfm.blend_ratio,
    rc.approved_rate,
    rc.gst_percent,
    COALESCE(rc.approved_inclusive, rc.std_rate, src.std_rate) AS approved_inclusive,
    COALESCE(rc.std_rate, src.std_rate) AS std_rate,
    ROUND((ds.qty_kg * COALESCE(rc.approved_inclusive, rc.std_rate, src.std_rate, 0::numeric)), 2) AS estimated_revenue
FROM daily_sales ds
LEFT JOIN customer_master cm 
    ON ds.customer_id = cm.customer_id
LEFT JOIN customers c 
    ON ds.customer_id::text = c.customer_id::text
LEFT JOIN sku_alias_map sam 
    ON LOWER(TRIM(ds.sku_name)) = LOWER(TRIM(sam.sales_sku_name))
LEFT JOIN sku_family_master sfm 
    ON LOWER(TRIM(ds.sku_name)) = LOWER(TRIM(sfm.product_code))
    OR sam.family_id = sfm.id
LEFT JOIN standard_rate_cards src 
    ON LOWER(TRIM(COALESCE(sam.rate_card_sku_name, ds.sku_name))) = LOWER(TRIM(src.sku_name))
LEFT JOIN rate_cards rc 
    ON ds.customer_id::text = rc.customer_id::text 
    AND LOWER(TRIM(COALESCE(sam.rate_card_sku_name, ds.sku_name))) = LOWER(TRIM(rc.sku_name));

CREATE OR REPLACE VIEW vw_daily_financial_summary AS
SELECT
    drs.summary_date,
    drs.route_number,
    drs.customer_id,
    COALESCE(cm.customer_name, c.name, drs.customer_name)::varchar(120) AS customer_name,
    COALESCE(cm.phone, c.phone)::varchar(30) AS phone,
    COALESCE(cm.credit_limit, c.credit_limit) AS credit_limit,
    COALESCE(cm.credit_balance, c.credit_balance) AS credit_balance,
    drs.cash,
    drs.credit,
    drs.closing_balance
FROM daily_route_summary drs
LEFT JOIN customer_master cm 
    ON drs.customer_id = cm.customer_id
LEFT JOIN customers c 
    ON drs.customer_id = c.customer_id;

CREATE OR REPLACE VIEW vw_route_sku_breakdown AS
SELECT
    dsd.summary_date,
    dsd.route_number,
    dsd.customer_id,
    COALESCE(cm.customer_name, c.name, dsd.customer_name)::varchar(120) AS customer_name,
    dsd.sku_name,
    dsd.qty_kg,
    COALESCE(sfm.main_group, rc.category, src.category, 'Unknown')::varchar(50) AS category,
    sfm.sub_main_group,
    sfm.sub_group,
    sfm.blend_ratio,
    COALESCE(rc.approved_inclusive, rc.std_rate, src.std_rate) AS approved_inclusive,
    ROUND((dsd.qty_kg * COALESCE(rc.approved_inclusive, rc.std_rate, src.std_rate, 0::numeric)), 2) AS estimated_revenue
FROM daily_route_sku_details dsd
LEFT JOIN customer_master cm 
    ON dsd.customer_id = cm.customer_id
LEFT JOIN customers c 
    ON dsd.customer_id::text = c.customer_id::text
LEFT JOIN sku_alias_map sam 
    ON LOWER(TRIM(dsd.sku_name)) = LOWER(TRIM(sam.sales_sku_name))
LEFT JOIN sku_family_master sfm 
    ON LOWER(TRIM(dsd.sku_name)) = LOWER(TRIM(sfm.product_code))
    OR sam.family_id = sfm.id
LEFT JOIN standard_rate_cards src 
    ON LOWER(TRIM(COALESCE(sam.rate_card_sku_name, dsd.sku_name))) = LOWER(TRIM(src.sku_name))
LEFT JOIN rate_cards rc 
    ON dsd.customer_id::text = rc.customer_id::text 
    AND LOWER(TRIM(COALESCE(sam.rate_card_sku_name, dsd.sku_name))) = LOWER(TRIM(rc.sku_name));
