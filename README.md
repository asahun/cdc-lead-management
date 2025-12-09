# Lead Management App

FastAPI application for managing business leads and unclaimed property records.

## Prerequisites

- Python 3.10 or higher
- PostgreSQL database
- OpenAI API key (for entity intelligence features)

## Installation (Windows)

### 1. Install Python

```powershell
# Using winget (recommended)
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements

# Close and reopen PowerShell, then verify:
python --version
```

### 2. Clone or copy the project

```powershell
cd C:\path\to\your\projects
git clone <repository-url> lead_app
# OR copy the project folder manually
```

### 3. Create and activate a virtual environment (recommended)

```powershell
cd lead_app
python -m venv .venv
.\.venv\Scripts\activate
```

**Note:** Virtual environments are recommended but not required. They isolate dependencies from other Python projects.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Install Playwright browser (for PDF generation)

```powershell
playwright install chromium
```

### 6. Set environment variables

In PowerShell, set these before running the app:

```powershell
# Database connection (adjust as needed)
$env:DATABASE_URL="postgresql+psycopg2://username:password@localhost:5432/database_name"

# OpenAI API key (required for entity intelligence)
$env:OPENAI_API_KEY="key"

# Optional: Custom GPT model
$env:GPT_ENTITY_MODEL="gpt-5.1"

# Optional: Request timeout
$env:GPT_ENTITY_TIMEOUT_SECONDS="45"
```

**To make environment variables permanent:**
- Open "Environment Variables" in Windows Settings
- Add them under "User variables" or "System variables"

**DB setup
- DB name:ucp, u:ucp_app, p:DBPASSWORD
- psql -U postgres -c "CREATE ROLE \"ucp_app\" WITH LOGIN PASSWORD 'DBPASSWORD';"
- psql -U postgres -c "CREATE DATABASE \"ucp\" OWNER \"ucp_app\";"
- pg_restore -U ucp_app -d ucp /tmp/db.dump

### 7. Run the server

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The app will be available at `http://localhost:8000`

## Project Structure

- `main.py` - FastAPI application and routes
- `models.py` - SQLAlchemy database models
- `db.py` - Database connection configuration
- `gpt_api.py` - OpenAI integration for entity intelligence
- `letters.py` - PDF letter generation
- `templates/` - Jinja2 HTML templates
- `static/` - CSS, JavaScript, and image assets

## Features

- Lead management with contacts, attempts, and comments
- Property detail views with assignment tracking
- Entity intelligence via GPT (successor research)
- PDF letter generation for contacts
- Responsive UI with localStorage state persistence

## Mgration tasks

ALTER TYPE lead_status ADD VALUE IF NOT EXISTS 'competitor_claimed';
ALTER TYPE lead_status ADD VALUE IF NOT EXISTS 'ready';

-- Create ENUM types for journey tracking
CREATE TYPE journey_status AS ENUM ('active', 'completed', 'paused');

CREATE TYPE journey_milestone_type AS ENUM (
    'email_1',
    'email_followup_1',
    'email_followup_2',
    'email_followup_3',
    'linkedin_connection',
    'linkedin_message_1',
    'linkedin_message_2',
    'linkedin_message_3',
    'linkedin_inmail',
    'mail_1',
    'mail_2',
    'mail_3'
);

CREATE TYPE milestone_status AS ENUM ('pending', 'completed', 'skipped', 'overdue');

-- Note: The tables `lead_journey` and `journey_milestone` will be created automatically
-- by SQLAlchemy's Base.metadata.create_all() when the application starts.

-- Add primary contact tracking columns
ALTER TABLE lead_contact ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE lead_journey ADD COLUMN IF NOT EXISTS primary_contact_id BIGINT REFERENCES lead_contact(id) ON DELETE SET NULL;

WITH cutoff AS (
    SELECT date_trunc('week', now())  -- Monday 00:00 (DB timezone)
           - interval '7 days'        -- previous Monday
           + interval '18 hours'      -- 6:00 PM
           AS ts
)
UPDATE business_lead bl
SET status = 'competitor_claimed',
    updated_at = now()
FROM ucp_main_year_e_2025 p, cutoff c
WHERE bl.property_raw_hash  = p.row_hash 
  AND p.last_seen < c.ts
  AND bl.status <> 'competitor_claimed';



