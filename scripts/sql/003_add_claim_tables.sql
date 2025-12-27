-- Adds claim, claim_event, claim_document tables
-- Run manually against the target Postgres DB.

CREATE TABLE IF NOT EXISTS claim (
    id SERIAL PRIMARY KEY,
    lead_id BIGINT NOT NULL REFERENCES lead(id) ON DELETE CASCADE,
    claim_slug TEXT UNIQUE NOT NULL,
    business_name TEXT,
    formation_state TEXT,
    control_no TEXT,
    fee_pct TEXT,
    addendum_yes BOOLEAN DEFAULT FALSE,
    cdr_identifier TEXT,
    cdr_agent_name TEXT,
    primary_contact_name TEXT,
    primary_contact_title TEXT,
    primary_contact_email TEXT,
    primary_contact_phone TEXT,
    primary_contact_mail TEXT,
    state_claim_id TEXT,
    output_dir TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claim_event (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    payload TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claim_document (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    notes TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claim_event_claim_id ON claim_event(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_document_claim_id ON claim_document(claim_id);


