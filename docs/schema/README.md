# Database Schema Export

This directory contains exported PostgreSQL database schemas for backup and recreation on different machines.

## Files

- `schema.sql` - Current database schema (overwritten on each export)
- `schema_YYYYMMDD_HHMMSS.sql` - Timestamped backups (created automatically)

## Usage

### Export Schema

Run the export script:

```bash
python scripts/export_schema.py
```

The script will:
1. Read database connection from `DATABASE_URL` environment variable
2. Export schema-only (no data) using `pg_dump`
3. Save to `docs/schema/schema.sql`
4. Create a timestamped backup if the main file already exists

### Environment Variables

- `DATABASE_URL` - PostgreSQL connection string (required)
  - Format: `postgresql://user:password@host:port/database`
  - Or: `postgresql+psycopg2://user:password@host:port/database`
  - Default: Uses the same default as the app

- `SCHEMA_EXPORT_BACKUP` - Create timestamped backups (optional)
  - Set to `false` to disable backup creation
  - Default: `true`

### Recreate Database on Another Machine

1. Ensure PostgreSQL is installed and running
2. Create the database and user (if needed):
   ```bash
   psql -U postgres -c "CREATE ROLE ucp_app WITH LOGIN PASSWORD 'your_password';"
   psql -U postgres -c "CREATE DATABASE ucp OWNER ucp_app;"
   ```
3. Import the schema:
   ```bash
   psql -U ucp_app -d ucp < docs/schema/schema.sql
   ```

## What's Included

The schema export includes:
- All ENUM types (lead_status, owner_type, journey_status, etc.)
- All table definitions (business_lead, lead_contact, journey_milestone, etc.)
- All constraints (primary keys, foreign keys, check constraints)
- All indexes
- Sequences (for auto-incrementing IDs)

**Note:** The export does NOT include:
- Data (rows) - only structure
- Ownership information (uses --no-owner flag)
- Privilege information (uses --no-privileges flag)

## Maintenance

Run this script whenever the database schema changes:
- After adding new tables
- After modifying table structures
- After creating new ENUM types
- After adding indexes or constraints

The script reads directly from the database, so it always reflects the current state, regardless of what's in the code.

