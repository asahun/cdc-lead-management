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

## Migration Tasks

### Multiple Properties Per Lead Migration

This migration moves property data from `business_lead` table to a new `lead_property` table, enabling multiple properties per lead.

#### Prerequisites

1. **Backup your database** before running any migration scripts
2. Ensure you have PostgreSQL client tools installed (`psql`, `pg_dump`)
3. Set `DATABASE_URL` environment variable if using non-default connection

#### Migration Steps

**Step 1: Backup Database**
```bash
pg_dump -U ucp_app -d ucp -F c -f backup_before_lead_property_migration.dump
```

**Step 2: Run Migration Script**
```bash
python scripts/migrate_and_cleanup_lead_property.py
```

This script does everything in one run:
- Creates `lead_property` table
- Migrates existing property data from `business_lead` to `lead_property`
- **Immediately drops old columns** (property_id, property_raw_hash, property_amount)
- Verifies data integrity
- Leaves only the new structure (no lingering old columns)

**Note:** The script will prompt you for confirmation before proceeding. Make sure you have a backup before running it.

#### Verification Steps

After running the migration script:

```sql
-- Verify old columns are gone
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'business_lead' 
AND column_name IN ('property_id', 'property_raw_hash', 'property_amount');
-- Should return 0 rows

-- Verify new structure works
SELECT l.id, l.owner_name, lp.property_id, lp.is_primary
FROM business_lead l
LEFT JOIN lead_property lp ON l.id = lp.lead_id
LIMIT 10;

-- Verify all leads have primary property
SELECT COUNT(*) FROM lead_property WHERE is_primary = true;
```

#### Rollback Procedure

If issues occur after migration:

1. **Before dropping old columns**: Old columns still exist, so you can:
   - Revert code to previous version
   - Old code will continue working with old columns

2. **After dropping old columns**: You must restore from backup:
   ```bash
   # Restore full backup
   pg_restore -U ucp_app -d ucp -c backup_before_lead_property_migration.dump
   
   # Or restore SQL backup
   psql -U ucp_app -d ucp < backup_before_lead_property_migration.sql
   ```

#### Script Reference

- `scripts/migrate_and_cleanup_lead_property.py` - **Migration script** (migrates data + drops old columns in one go)

**Command to run:**
```bash
python scripts/migrate_and_cleanup_lead_property.py
```





