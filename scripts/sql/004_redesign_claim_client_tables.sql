-- Create claim and client tables
-- This script creates all claim-related tables from scratch
-- For a clean database setup, run this script manually against the target Postgres DB.
-- If tables already exist, they will be dropped first (CASCADE will handle foreign keys)

-- Drop existing claim-related tables if they exist (for clean slate)
DROP TABLE IF EXISTS claim_document CASCADE;
DROP TABLE IF EXISTS claim_event CASCADE;
DROP TABLE IF EXISTS claim CASCADE;
DROP TABLE IF EXISTS client_mailing_address CASCADE;
DROP TABLE IF EXISTS client_contact CASCADE;
DROP TABLE IF EXISTS client CASCADE;
DROP TYPE IF EXISTS signer_type_enum CASCADE;

-- Create client table (reusable entity)
CREATE TABLE client (
    id SERIAL PRIMARY KEY,
    entitled_business_name TEXT NOT NULL,
    formation_state TEXT,
    control_no TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create client_contact table (signer contacts)
CREATE TYPE signer_type_enum AS ENUM ('primary', 'secondary');

CREATE TABLE client_contact (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    lead_contact_id BIGINT REFERENCES lead_contact(id) ON DELETE SET NULL,
    signer_type signer_type_enum NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    title TEXT,
    email TEXT,
    phone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_client_contact_client_id ON client_contact(client_id);
CREATE INDEX idx_client_contact_signer_type ON client_contact(client_id, signer_type);

-- Create client_mailing_address table
CREATE TABLE client_mailing_address (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    street TEXT NOT NULL,
    line2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_client_mailing_address_client_id ON client_mailing_address(client_id);

-- Create claim table (redesigned)
CREATE TABLE claim (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    lead_id BIGINT NOT NULL REFERENCES lead(id) ON DELETE CASCADE,
    claim_slug TEXT UNIQUE NOT NULL,
    
    -- Business name snapshot (duplicated from client for historical record)
    entitled_business_name TEXT NOT NULL,
    entitled_business_same_as_owner BOOLEAN DEFAULT TRUE,
    
    -- Fee structure (one of fee_pct or fee_flat must be set)
    fee_pct NUMERIC(5, 2),      -- Percentage (e.g., 10.50 for 10.5%), NULL if using flat fee
    fee_flat NUMERIC(18, 2),    -- Flat dollar amount, NULL if using percentage
    cdr_fee NUMERIC(18, 2),     -- Calculated fee amount (either fee_flat or calculated from fee_pct)
    
    -- Claim-specific data
    addendum_yes BOOLEAN DEFAULT FALSE,
    total_properties INTEGER,
    total_amount NUMERIC(18, 2),
    state_claim_id TEXT,
    check_mailing_address_id INTEGER REFERENCES client_mailing_address(id) ON DELETE SET NULL,
    output_dir TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraint: Either fee_pct or fee_flat must be set (but not both)
    CONSTRAINT chk_fee_type CHECK (
        (fee_pct IS NOT NULL AND fee_flat IS NULL) OR 
        (fee_pct IS NULL AND fee_flat IS NOT NULL)
    )
);

CREATE INDEX idx_claim_client_id ON claim(client_id);
CREATE INDEX idx_claim_lead_id ON claim(lead_id);
CREATE UNIQUE INDEX idx_claim_lead_id_unique ON claim(lead_id);  -- Enforce one-to-one with lead

-- Recreate claim_event table (same structure, data reset)
CREATE TABLE claim_event (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    payload TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_claim_event_claim_id ON claim_event(claim_id);

-- Recreate claim_document table (same structure, data reset)
CREATE TABLE claim_document (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    notes TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_claim_document_claim_id ON claim_document(claim_id);

