-- Creates lead_client and lead_client_event tables to track agreement/claim lifecycle
-- Run manually against the target Postgres DB.

CREATE TABLE IF NOT EXISTS lead_client (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    control_no TEXT,
    formation_state TEXT,
    fee_pct TEXT,
    addendum_yes BOOLEAN DEFAULT FALSE,
    output_dir TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lead_client_event (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES lead_client(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    payload JSONB,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lead_client_event_client_id ON lead_client_event(client_id);


