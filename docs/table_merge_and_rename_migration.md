# Table Merge and Rename Migration Guide

This document describes the complete migration process for:
1. Merging all year-specific property tables into a unified `property` table
2. Renaming tables for consistent naming conventions
3. Creating optimized indexes
4. Updating application code

**Date:** 2024
**Database Size:** >11GB property data

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Migration Steps](#migration-steps)
4. [Code Changes Summary](#code-changes-summary)
5. [Verification](#verification)
6. [Rollback Plan](#rollback-plan)

---

## Overview

### What Changed

**Table Merges:**
- All `ucp_main_*` tables → unified `property` table
- All property data now in one table with `reportyear` column for filtering

**Table Renames:**
- `business_lead` → `lead`
- `ucp_properties` → `property`
- `owner_relationship_authority` → `property_ownership_type`
- `scheduled_email` → `lead_scheduled_email`
- `print_log` → `lead_print_log`
- `journey_milestone` → `lead_journey_milestone`

**Code Changes:**
- Updated all model references
- Updated property service to use unified table with year filtering
- Updated all foreign key references
- Added year column to property displays

---

## Prerequisites

1. **Backup Database**
   ```bash
   pg_dump -U ucp_app -d ucp -F c -f backup_before_migration_$(date +%Y%m%d_%H%M%S).dump
   ```

2. **Ensure Sufficient Disk Space**
   - Table merge: ~11GB
   - Indexes: ~5-10GB additional space needed
   - **Total free space needed: ~20GB minimum**

3. **Pull Latest Code**
   - Ensure you have the latest code with all model changes

4. **Stop Application** (recommended during migration)
   - Prevents concurrent access during table operations

5. **psql Access** (if not using DBeaver)
   - All scripts work in psql (PostgreSQL command-line client)
   - See [Running Scripts in psql](#running-scripts-in-psql) section below

---

## Running Scripts in psql

All scripts in this document work perfectly in `psql` (PostgreSQL command-line client). Here's how to use them:

### Connect to Database

```bash
# Basic connection
psql -U ucp_app -d ucp

# Or with connection string
psql postgresql://ucp_app:password@localhost:5432/ucp

# For Docker PostgreSQL
psql -h localhost -p 5432 -U ucp_app -d ucp
```

### Running Scripts

**Option 1: Copy-paste into psql**
- Simply copy each SQL block from the document
- Paste into your psql session
- Press Enter to execute
- `RAISE NOTICE` messages will show progress

**Option 2: Save to file and run**
```bash
# Save a step to a file
cat > step1_create_table.sql << 'EOF'
-- Step 1 SQL here
EOF

# Run it
psql -U ucp_app -d ucp -f step1_create_table.sql
```

**Option 3: Run entire script from file**
```bash
# Save complete migration script to file
# Then run:
psql -U ucp_app -d ucp -f complete_migration.sql
```

### psql Tips

- **Enable timing**: `\timing` (shows execution time for each command)
- **Show progress**: `RAISE NOTICE` messages will display automatically
- **Exit psql**: `\q` or `Ctrl+D`
- **Continue on error**: Scripts use `DO $$` blocks that auto-commit, so progress is saved
- **Monitor progress**: The `RAISE NOTICE` statements will print to console as each table is processed

### Differences from DBeaver

- **Output**: `RAISE NOTICE` messages appear in console (same as DBeaver)
- **Transactions**: Same behavior - each statement auto-commits
- **Error handling**: Same - errors will stop the current block but previous work is saved
- **No GUI**: You'll see text output instead of a results grid (but that's fine for these operations)

### Example Output in psql

```
NOTICE:  Copying data from ucp_main_year_e_2025
NOTICE:  Completed ucp_main_year_e_2025
NOTICE:  Copying data from ucp_main_year_e_2024
NOTICE:  Completed ucp_main_year_e_2024
NOTICE:  All tables merged!
```

---

## Migration Steps

### Step 1: Create Unified Property Table

```sql
-- ============================================
-- STEP 1: Create table (auto-commits immediately)
-- ============================================
-- Using UNLOGGED for faster writes (we'll convert to logged after)
CREATE UNLOGGED TABLE property (
	propertyid numeric(20) NOT NULL,
	ownername varchar(50) NOT NULL,
	owneraddress1 text NULL,
	owneraddress2 text NULL,
	owneraddress3 text NULL,
	ownercity text NULL,
	ownerstate text NULL,
	ownerzipcode text NULL,
	ownerrelation text NULL,
	propertyamount numeric(18, 2) NOT NULL,
	lastactivitydate text NULL,
	reportyear int4 NULL,
	holdername text NULL,
	propertytypedescription text NULL,
	row_hash text NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	assigned_to_lead bool DEFAULT false NOT NULL,
	last_seen timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT property_propertyid_chk CHECK ((propertyid > (0)::numeric)),
	CONSTRAINT property_reportyear_chk CHECK (((reportyear IS NULL) OR ((reportyear >= 1000) AND (reportyear <= 9999))))
);

-- Create unique index on row_hash (primary key)
CREATE UNIQUE INDEX property_row_hash_uq ON property USING btree (row_hash);

-- Disable autovacuum during migration
ALTER TABLE property SET (autovacuum_enabled = false);
```

### Step 2: Merge All Property Tables

```sql
-- ============================================
-- STEP 2: Merge data (commits after each table)
-- ============================================
-- Each INSERT commits automatically (no transaction wrapper)
-- This automatically finds ALL tables matching the pattern
DO $$
DECLARE
    table_record RECORD;
    copy_sql TEXT;
BEGIN
    -- Loop through all property tables
    FOR table_record IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename LIKE 'ucp_main_%'
        ORDER BY tablename DESC
    LOOP
        RAISE NOTICE 'Copying data from %', table_record.tablename;
        
        -- Each INSERT auto-commits, so progress is saved
        -- Use INSERT with ON CONFLICT to handle duplicates
        copy_sql := format(
            'INSERT INTO property 
             SELECT * FROM %I 
             ON CONFLICT (row_hash) DO NOTHING',
            table_record.tablename
        );
        
        EXECUTE copy_sql;
        
        RAISE NOTICE 'Completed %', table_record.tablename;
    END LOOP;
    
    RAISE NOTICE 'All tables merged!';
END $$;
```

### Step 3: Convert to Logged Table

```sql
-- ============================================
-- STEP 3: Convert to logged (auto-commits)
-- ============================================
-- Convert to logged table (for durability)
ALTER TABLE property SET LOGGED;

-- Re-enable autovacuum
ALTER TABLE property SET (autovacuum_enabled = true);
```

### Step 4: Create All Indexes (with correct names)

```sql
-- ============================================
-- STEP 4: Create indexes ONE AT A TIME (each auto-commits)
-- ============================================
-- Run these separately, checking disk space between each
-- These indexes are optimized for the application's query patterns

-- Primary lookup indexes
CREATE INDEX idx_properties_propertyid ON property(propertyid);
CREATE INDEX idx_properties_ownername ON property(ownername);

-- 1. reportyear - Used in WHERE clauses (routers/leads.py:351, 357)
CREATE INDEX idx_properties_reportyear ON property(reportyear);

-- 2. propertyamount DESC - Used in WHERE (>= 10000) and ORDER BY (very common)
CREATE INDEX idx_properties_amount ON property(propertyamount DESC);

-- 3. Composite: (propertyamount DESC, row_hash ASC) - Most common ordering pattern
-- Used in: property_navigation_info, get_raw_hash_for_order, list_properties
CREATE INDEX idx_properties_amount_hash ON property(propertyamount DESC, row_hash ASC);

-- 4. Composite: (reportyear, propertyamount DESC) - Year + amount filtering together
CREATE INDEX idx_properties_year_amount ON property(reportyear, propertyamount DESC);

-- 5. assigned_to_lead (partial) - Filter for unassigned properties
CREATE INDEX idx_properties_assigned ON property(assigned_to_lead) 
WHERE assigned_to_lead = TRUE;

-- 6. last_seen (partial) - Filter for recent activity (routers/properties.py:89)
CREATE INDEX idx_properties_last_seen ON property(last_seen) 
WHERE last_seen IS NOT NULL;

-- 7. ownerrelation - Used in joins with OwnerRelationshipAuthority (routers/properties.py:115)
CREATE INDEX idx_properties_ownerrelation ON property(ownerrelation);

-- 8. ownername GIN index (for ILIKE performance) - Used in text search (routers/properties.py:97)
-- Only create if you have disk space - this is large but significantly speeds up ILIKE
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_properties_ownername_trgm ON property USING gin(ownername gin_trgm_ops);

-- Optional: Location indexes (if you filter by location)
CREATE INDEX idx_properties_state ON property(ownerstate);
CREATE INDEX idx_properties_city ON property(ownercity);

-- Update statistics for query planner
ANALYZE property;
```

### Step 5: Verify Data Migration

```sql
-- ============================================
-- STEP 5: Verify the migration
-- ============================================
-- Compare new table count with old tables total
-- Quick approximation using pg_class statistics (fast but approximate)
SELECT 
    (SELECT COUNT(*) FROM property) as new_table_count,
    (SELECT SUM(reltuples)::bigint 
     FROM pg_class 
     WHERE relname LIKE 'ucp_main_%' 
     AND relkind = 'r') as old_tables_approx_count;

-- Most accurate: Actual row count from all old tables (slower but exact)
SELECT 
    (SELECT COUNT(*) FROM property) as new_table_count,
    (SELECT SUM(reltuples)::bigint 
     FROM pg_class 
     WHERE relname LIKE 'ucp_main_%' 
     AND relkind = 'r') as old_tables_approx_count;

-- Most accurate: Actual row count from all old tables
-- This dynamically queries all old tables
DO $$
DECLARE
    table_record RECORD;
    total_count BIGINT := 0;
    table_count BIGINT;
    sql_text TEXT;
BEGIN
    FOR table_record IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename LIKE 'ucp_main_%'
    LOOP
        sql_text := format('SELECT COUNT(*) FROM %I', table_record.tablename);
        EXECUTE sql_text INTO table_count;
        total_count := total_count + table_count;
        RAISE NOTICE 'Table %: % rows', table_record.tablename, table_count;
    END LOOP;
    
    RAISE NOTICE 'Total old tables count: %', total_count;
    RAISE NOTICE 'New table count: %', (SELECT COUNT(*) FROM property);
END $$;

-- Check total rows and data integrity
SELECT 
    COUNT(*) as total_rows,
    COUNT(DISTINCT reportyear) as distinct_years,
    MIN(propertyamount) as min_amount,
    MAX(propertyamount) as max_amount,
    pg_size_pretty(pg_total_relation_size('property')) as table_size
FROM property;

-- Verify year distribution
SELECT reportyear, COUNT(*) 
FROM property 
GROUP BY reportyear 
ORDER BY reportyear DESC;
```

### Step 6: Drop Old Property Tables (After Verification)

```sql
-- ============================================
-- STEP 6: Drop old property tables
-- ============================================
-- WARNING: Only run this after verifying data is correct!

-- First, check which views exist (optional - for verification)
SELECT viewname 
FROM pg_views 
WHERE schemaname = 'public' 
AND viewname LIKE 'v_raw_amount_ge_%'
ORDER BY viewname;

-- Drop views that depend on old tables
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2025 CASCADE;
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2024 CASCADE;
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2023 CASCADE;

-- Then drop old property tables
DO $$
DECLARE
    table_record RECORD;
BEGIN
    FOR table_record IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename LIKE 'ucp_main_%'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', table_record.tablename);
        RAISE NOTICE 'Dropped table %', table_record.tablename;
    END LOOP;
END $$;
```

### Step 7: Rename Tables

```sql
-- ============================================
-- STEP 7: Rename tables for consistent naming
-- ============================================
-- All renames are instant (metadata-only operations)
-- Note: property table is already named correctly, no rename needed

ALTER TABLE business_lead RENAME TO lead;
ALTER TABLE owner_relationship_authority RENAME TO property_ownership_type;
ALTER TABLE scheduled_email RENAME TO lead_scheduled_email;
ALTER TABLE print_log RENAME TO lead_print_log;
ALTER TABLE journey_milestone RENAME TO lead_journey_milestone;
```

### Step 8: Verify Table Renames

```sql
-- ============================================
-- STEP 8: Verify all renames
-- ============================================
SELECT 
    'Tables renamed:' as status,
    tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename IN (
    'lead', 
    'property', 
    'property_ownership_type', 
    'lead_scheduled_email', 
    'lead_print_log', 
    'lead_journey_milestone'
)
ORDER BY tablename;
```

---

## Code Changes Summary

### Models Updated (`models.py`)

**Class Renames:**
- `BusinessLead` → `Lead`
- `OwnerRelationshipAuthority` → `PropertyOwnershipType`

**Table Name Changes:**
- `PropertyView.__tablename__ = "property"` (was `"ucp_main_year_e_2025"`)
- `Lead.__tablename__ = "lead"` (was `"business_lead"`)
- `PropertyOwnershipType.__tablename__ = "property_ownership_type"` (was `"owner_relationship_authority"`)
- `ScheduledEmail.__tablename__ = "lead_scheduled_email"` (was `"scheduled_email"`)
- `PrintLog.__tablename__ = "lead_print_log"` (was `"print_log"`)
- `JourneyMilestone.__tablename__ = "lead_journey_milestone"` (was `"journey_milestone"`)

**ForeignKey Updates:**
- All `ForeignKey("business_lead.id")` → `ForeignKey("lead.id")`
- All `relationship("BusinessLead")` → `relationship("Lead")`

### Property Service Updated (`services/property_service.py`)

**Key Changes:**
- `get_available_years()` - Now queries `SELECT DISTINCT reportyear FROM property`
- `get_property_table_for_year()` - Returns unified `property` table (no longer year-specific)
- All queries now filter by `WHERE reportyear = ?` instead of using different tables

**Query Pattern Change:**
```python
# OLD: Used different tables per year
prop_table = get_property_table_for_year("2025")  # Returns ucp_main_year_e_2025 table

# NEW: Uses unified table with year filter
prop_table = get_property_table_for_year("2025")  # Returns property table
# Then filter: WHERE reportyear = 2025
```

### Files Updated

**Models:**
- `models.py` - All table names and class names

**Services:**
- `services/property_service.py` - Unified table logic

**Routers:**
- `routers/properties.py` - Year filtering, PropertyOwnershipType
- `routers/leads.py` - Year filtering, Lead references

**Helpers:**
- `helpers/filter_helpers.py` - Lead references
- `helpers/property_helpers.py` - Lead references
- `helpers/linkedin_helpers.py` - Lead references

**Utils:**
- `utils/validators.py` - Lead references

**Templates:**
- `templates/lead_form.html` - Added year column to property displays

**JavaScript:**
- `static/js/property_management.js` - Added year column to modal

**CSS:**
- `static/css/styles.css` - Widened modal for additional column

---

## Verification

### 1. Verify Table Structure

```sql
-- Check unified property table exists
SELECT COUNT(*) FROM property;

-- Check all renamed tables exist
SELECT tablename FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename IN ('lead', 'property', 'property_ownership_type', 
                   'lead_scheduled_email', 'lead_print_log', 'lead_journey_milestone');
```

### 2. Verify Indexes

```sql
-- Check all indexes on property table
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'property'
ORDER BY indexname;
```

### 3. Verify Application

1. Start the application
2. Test property listing page - should filter by year
3. Test lead listing page - should work with year filter
4. Test property detail pages - should load correctly
5. Test adding properties to leads - should work
6. Verify year displays in property lists

### 4. Verify Data Integrity

```sql
-- Compare row counts (if old tables still exist for verification)
SELECT 
    (SELECT COUNT(*) FROM property) as new_table_count,
    (SELECT SUM(reltuples)::bigint 
     FROM pg_class 
     WHERE relname LIKE 'ucp_main_%' 
     AND relname != 'property') as old_tables_approx;
```

---

## Rollback Plan

If you need to rollback:

1. **Restore from backup:**
   ```bash
   pg_restore -U ucp_app -d ucp backup_before_migration_YYYYMMDD_HHMMSS.dump
   ```

2. **Or manually recreate old structure:**
   - Restore old tables from backup
   - Revert code changes (git checkout previous commit)
   - Restart application

---

## Performance Notes

### Index Creation Time
- For 11GB+ data, index creation can take 1-2 hours
- Create indexes one at a time if disk space is limited
- Monitor disk space during index creation

### Data Ingestion
- Weekly data loads (~11GB) will take ~1.5-2 hours with all indexes
- To speed up bulk loads:
  1. Drop non-essential indexes before load
  2. Run upsert operation
  3. Recreate indexes after load

### Query Performance
- Year filtering is now much faster (indexed)
- Amount filtering/sorting is faster (indexed)
- Owner name searches are faster (GIN index for ILIKE)

---

## Troubleshooting

### Issue: "Property table for year X not found"
**Solution:** Ensure `get_available_years()` is working and returns years from `property.reportyear`

### Issue: "No space left on device" during index creation
**Solution:** 
1. Drop old property tables first to free space
2. Create indexes one at a time
3. Monitor disk space: `df -h`

### Issue: Foreign key errors after rename
**Solution:** Foreign keys are automatically updated when tables are renamed. If issues persist, check:
```sql
SELECT conname, conrelid::regclass, confrelid::regclass 
FROM pg_constraint 
WHERE contype = 'f' 
AND confrelid::regclass::text LIKE '%lead%';
```

---

## Complete Migration Script

For convenience, here's the complete script combining all steps:

```sql
-- ============================================
-- COMPLETE MIGRATION SCRIPT
-- ============================================
-- Run this in DBeaver or psql
-- Estimated time: 2-4 hours for 11GB+ data

-- Performance settings
SET work_mem = '256MB';
SET maintenance_work_mem = '1GB';
SET synchronous_commit = OFF;

-- Step 1: Create unified table
CREATE UNLOGGED TABLE property (
	propertyid numeric(20) NOT NULL,
	ownername varchar(50) NOT NULL,
	owneraddress1 text NULL,
	owneraddress2 text NULL,
	owneraddress3 text NULL,
	ownercity text NULL,
	ownerstate text NULL,
	ownerzipcode text NULL,
	ownerrelation text NULL,
	propertyamount numeric(18, 2) NOT NULL,
	lastactivitydate text NULL,
	reportyear int4 NULL,
	holdername text NULL,
	propertytypedescription text NULL,
	row_hash text NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	assigned_to_lead bool DEFAULT false NOT NULL,
	last_seen timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT property_propertyid_chk CHECK ((propertyid > (0)::numeric)),
	CONSTRAINT property_reportyear_chk CHECK (((reportyear IS NULL) OR ((reportyear >= 1000) AND (reportyear <= 9999))))
);

CREATE UNIQUE INDEX property_row_hash_uq ON property USING btree (row_hash);
ALTER TABLE property SET (autovacuum_enabled = false);

-- Step 2: Merge all tables
DO $$
DECLARE
    table_record RECORD;
    copy_sql TEXT;
BEGIN
    FOR table_record IN 
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        AND tablename LIKE 'ucp_main_%'
        ORDER BY tablename DESC
    LOOP
        RAISE NOTICE 'Copying data from %', table_record.tablename;
        copy_sql := format(
            'INSERT INTO property 
             SELECT * FROM %I 
             ON CONFLICT (row_hash) DO NOTHING',
            table_record.tablename
        );
        EXECUTE copy_sql;
        RAISE NOTICE 'Completed %', table_record.tablename;
    END LOOP;
    RAISE NOTICE 'All tables merged!';
END $$;

-- Step 3: Convert to logged
ALTER TABLE property SET LOGGED;
ALTER TABLE property SET (autovacuum_enabled = true);

-- Step 4: Create indexes (run these one at a time if disk space is limited)
-- 1. reportyear - Used in WHERE clauses
CREATE INDEX idx_properties_reportyear ON property(reportyear);

-- 2. propertyamount DESC - Used in WHERE (>= 10000) and ORDER BY (very common)
CREATE INDEX idx_properties_amount ON property(propertyamount DESC);

-- 3. Composite: (propertyamount DESC, row_hash ASC) - Most common ordering pattern
CREATE INDEX idx_properties_amount_hash ON property(propertyamount DESC, row_hash ASC);

-- 4. Composite: (reportyear, propertyamount DESC) - Year + amount filtering together
CREATE INDEX idx_properties_year_amount ON property(reportyear, propertyamount DESC);

-- 5. assigned_to_lead (partial) - Filter for unassigned properties
CREATE INDEX idx_properties_assigned ON property(assigned_to_lead) WHERE assigned_to_lead = TRUE;

-- 6. last_seen (partial) - Filter for recent activity
CREATE INDEX idx_properties_last_seen ON property(last_seen) WHERE last_seen IS NOT NULL;

-- 7. ownerrelation - Used in joins with OwnerRelationshipAuthority
CREATE INDEX idx_properties_ownerrelation ON property(ownerrelation);

-- 8. ownername GIN index (for ILIKE performance) - Only create if you have disk space
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_properties_ownername_trgm ON property USING gin(ownername gin_trgm_ops);

-- Optional: Location indexes
CREATE INDEX idx_properties_propertyid ON property(propertyid);
CREATE INDEX idx_properties_ownername ON property(ownername);
CREATE INDEX idx_properties_state ON property(ownerstate);
CREATE INDEX idx_properties_city ON property(ownercity);

ANALYZE property;

-- Step 5: Check and drop old views
-- First, check which views exist (optional - for verification)
SELECT viewname 
FROM pg_views 
WHERE schemaname = 'public' 
AND viewname LIKE 'v_raw_amount_ge_%'
ORDER BY viewname;

-- Drop views that depend on old tables
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2025 CASCADE;
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2024 CASCADE;
DROP VIEW IF EXISTS v_raw_amount_ge_10000_2023 CASCADE;

-- Step 6: Drop old tables (after verification)
-- DO $$
-- DECLARE
--     table_record RECORD;
-- BEGIN
--     FOR table_record IN 
--         SELECT tablename 
--         FROM pg_tables 
--         WHERE schemaname = 'public' 
--         AND tablename LIKE 'ucp_main_%'
--     LOOP
--         EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', table_record.tablename);
--         RAISE NOTICE 'Dropped table %', table_record.tablename;
--     END LOOP;
-- END $$;

-- Step 7: Rename tables
-- Note: property table is already named correctly, no rename needed
ALTER TABLE business_lead RENAME TO lead;
ALTER TABLE owner_relationship_authority RENAME TO property_ownership_type;
ALTER TABLE scheduled_email RENAME TO lead_scheduled_email;
ALTER TABLE print_log RENAME TO lead_print_log;
ALTER TABLE journey_milestone RENAME TO lead_journey_milestone;

-- Step 8: Verify
SELECT 
    COUNT(*) as total_rows,
    COUNT(DISTINCT reportyear) as distinct_years,
    pg_size_pretty(pg_total_relation_size('property')) as table_size
FROM property;
```

---

## Post-Migration Checklist

- [ ] All data migrated successfully
- [ ] All indexes created
- [ ] Old tables dropped (after verification)
- [ ] Tables renamed
- [ ] Code deployed with new table names
- [ ] Application tested and working
- [ ] Year filtering working on properties page
- [ ] Year displays in property lists
- [ ] All queries performing well

---

## Notes

- The migration is **irreversible** once old tables are dropped
- Always backup before migration
- Index creation is the slowest part (1-2 hours for 11GB)
- Table renames are instant (metadata-only)
- The unified table approach simplifies future data ingestion

