-- Migration 001: Create customer_master table and associated indexes
-- Authoritative customer master table for Horeca Sales Intelligence

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

-- Index for normalized name lookups (case/punctuation-insensitive)
CREATE INDEX IF NOT EXISTS idx_customer_master_norm_name 
    ON customer_master (normalized_name);

-- Trigram index for fuzzy customer name matching
CREATE INDEX IF NOT EXISTS idx_customer_master_name_trgm 
    ON customer_master USING gin (LOWER(customer_name) gin_trgm_ops);

-- Index for Tally ID lookups
CREATE INDEX IF NOT EXISTS idx_customer_master_tally_id 
    ON customer_master (tally_id);

-- Index for route-based filtering
CREATE INDEX IF NOT EXISTS idx_customer_master_route 
    ON customer_master (route_number);
