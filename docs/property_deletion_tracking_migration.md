# Property Deletion Tracking Migration Guide

This document describes the complete migration process for:
1. Adding property-level deletion tracking (`deleted_from_source` fields)
2. Removing `competitor_claimed` from lead status enum (now computed from properties)
3. Implementing computed statuses (`competitor_claimed` and `partially_claimed`)
4. Updating application code and UI

**Date:** 2024
**Status:** ✅ All Phases Complete

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Migration Steps](#migration-steps)
4. [Code Changes Summary](#code-changes-summary)
5. [Verification](#verification)
6. [Data Load Integration](#data-load-integration)

---

## Overview

### What Changed

**Database Changes:**
- Added `deleted_from_source` (Boolean) and `deleted_from_source_at` (DateTime) columns to `lead_property` table
- Removed `competitor_claimed` from `lead_status` enum type
- Created indexes on new columns for efficient queries

**Status Logic Changes:**
- **Before:** `competitor_claimed` was a stored enum value on `lead.status`
- **After:** Status is computed from properties:
  - `competitor_claimed` = all properties are `deleted_from_source = TRUE`
  - `partially_claimed` = some (but not all) properties are deleted
  - Otherwise = stored status (e.g., `ready`, `contact_in_progress`)

**Code Changes:**
- Added helper functions: `is_competitor_claimed()`, `is_partially_claimed()`, `get_effective_status()`
- Updated all code references to use computed status
- Updated templates to show computed status and property deletion badges
- Added "Status" column to properties table showing "Deleted" or "Active" badges

---

## Prerequisites

- **Database Backup:** Always backup your database before running migrations
- **Code Version:** Pull latest code that includes all Phase 1-3 changes
- **Database Access:** Ensure you have permissions to:
  - ALTER TABLE
  - DROP/CREATE TYPE
  - CREATE INDEX
- **Downtime:** Plan for brief downtime during migration (5-10 minutes)

---

## Migration Steps

### Step 1: Backup Database

```bash
# Create a backup before starting
pg_dump -U your_user -d your_database > backup_before_property_deletion_migration_$(date +%Y%m%d_%H%M%S).sql
```

### Step 2: Run Phase 1 Migration (Data Model Changes)

**File:** `scripts/sql/005_remove_competitor_claimed_add_property_deletion.sql`

**What it does:**
- Adds `deleted_from_source` and `deleted_from_source_at` columns to `lead_property` table
- Creates indexes on these columns
- Removes `competitor_claimed` from `lead_status` enum type
- Converts existing `competitor_claimed` leads to `'new'` status (temporary)

**To run:**
```bash
# Using psql
psql -U your_user -d your_database -f scripts/sql/005_remove_competitor_claimed_add_property_deletion.sql

# Or using DBeaver
# Open the SQL script and execute it
```

**Verification:**
```sql
-- Check columns were added
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'lead_property' 
AND column_name IN ('deleted_from_source', 'deleted_from_source_at');

-- Check enum was updated (should NOT include competitor_claimed)
SELECT enumlabel 
FROM pg_enum 
WHERE enumtypid = 'lead_status'::regtype 
ORDER BY enumsortorder;
```

### Step 3: Run Phase 2 Migration (Data Migration)

**File:** `scripts/sql/006_migrate_competitor_claimed_data.sql`

**What it does:**
- Marks properties as `deleted_from_source = TRUE` if their `last_seen` is older than cutoff
- Handles orphaned properties (not found in property table)
- Sets `deleted_from_source_at` timestamps

**To run:**
```bash
# Using psql
psql -U your_user -d your_database -f scripts/sql/006_migrate_competitor_claimed_data.sql

# Or using DBeaver
# Open the SQL script and execute it
```

**Verification:**
```sql
-- Check how many properties were marked as deleted
SELECT 
    COUNT(*) as total_properties,
    COUNT(*) FILTER (WHERE deleted_from_source = TRUE) as deleted_properties,
    COUNT(*) FILTER (WHERE deleted_from_source = FALSE) as active_properties
FROM lead_property;

-- Check leads with all properties deleted
SELECT l.id, l.owner_name, l.status, COUNT(lp.id) as total_props, 
       COUNT(*) FILTER (WHERE lp.deleted_from_source = TRUE) as deleted_props
FROM lead l
JOIN lead_property lp ON lp.lead_id = l.id
GROUP BY l.id, l.owner_name, l.status
HAVING COUNT(*) FILTER (WHERE lp.deleted_from_source = TRUE) = COUNT(lp.id)
LIMIT 10;
```

### Step 4: Deploy Code Changes

**Ensure you have the latest code with:**
- ✅ Updated `models.py` (LeadProperty with new fields, LeadStatus without competitor_claimed)
- ✅ Updated `utils/validators.py` (helper functions)
- ✅ Updated routers (leads.py, contacts.py, journey_api.py)
- ✅ Updated templates (lead_form.html, leads.html)
- ✅ Updated `main.py` (template filters)

**Deploy steps:**
1. Pull latest code from repository
2. Install/update dependencies if needed: `pip install -r requirements.txt`
3. Restart the application

**Note:** The code changes are already included in the repository. You just need to ensure you're on the latest version.

### Step 5: Verify Application Works

1. **Check application starts** without errors
2. **View a lead** - verify status displays correctly (may show `competitor_claimed` or `partially_claimed` if computed)
3. **Check properties table** - verify "Status" column shows "Deleted" or "Active" badges
4. **Test lead list** - verify status column shows computed statuses

---

## Code Changes Summary

### Models (`models.py`)

**LeadProperty:**
```python
# Added fields:
deleted_from_source = Column(Boolean, nullable=False, default=False)
deleted_from_source_at = Column(DateTime(timezone=True), nullable=True)
```

**LeadStatus Enum:**
```python
# Removed:
competitor_claimed = "competitor_claimed"  # ❌ Removed
```

### Helper Functions (`utils/validators.py`)

**New functions:**
- `is_competitor_claimed(lead: Lead) -> bool` - Returns True if all properties are deleted
- `is_partially_claimed(lead: Lead) -> bool` - Returns True if some (but not all) properties are deleted
- `get_effective_status(lead: Lead) -> LeadStatus | str` - Returns computed status

**Updated:**
- `is_lead_editable()` - Now uses `is_competitor_claimed()` instead of enum check

### Routers Updated

- `routers/leads.py` - Uses `is_competitor_claimed()` helper
- `routers/contacts.py` - Uses `is_competitor_claimed()` helper
- `routers/journey_api.py` - Uses `is_competitor_claimed()` helper

### Templates Updated

- `templates/lead_form.html` - Shows computed status, property deletion badges
- `templates/leads.html` - Shows computed status in list view
- Added template filter: `is_competitor_claimed` and `is_partially_claimed`

### Main Application (`main.py`)

- Added template filters for computed status checks

---

## Verification

### Database Verification

```sql
-- 1. Verify columns exist
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns 
WHERE table_name = 'lead_property' 
AND column_name IN ('deleted_from_source', 'deleted_from_source_at');

-- 2. Verify indexes exist
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'lead_property' 
AND indexname LIKE '%deleted%';

-- 3. Verify enum doesn't have competitor_claimed
SELECT enumlabel 
FROM pg_enum 
WHERE enumtypid = 'lead_status'::regtype 
ORDER BY enumsortorder;
-- Should NOT include 'competitor_claimed'

-- 4. Check data migration results
SELECT 
    COUNT(*) as total_leads,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM lead_property lp 
        WHERE lp.lead_id = lead.id 
        AND lp.deleted_from_source = TRUE
    )) as leads_with_deleted_properties,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM lead_property lp 
        WHERE lp.lead_id = lead.id 
        AND lp.deleted_from_source = TRUE
        GROUP BY lp.lead_id
        HAVING COUNT(*) FILTER (WHERE lp.deleted_from_source = TRUE) = COUNT(*)
    )) as leads_with_all_deleted
FROM lead;
```

### Application Verification

1. **Lead List View:**
   - Status column should show `competitor_claimed` or `partially_claimed` when applicable
   - Leads with all properties deleted should be read-only (grayed out)

2. **Lead Detail View:**
   - Header status should show computed status
   - Properties table should have "Status" column with "Deleted" or "Active" badges
   - Deleted properties should show red "Deleted" badge

3. **Functionality:**
   - Leads with some deleted properties should still be editable
   - Leads with all deleted properties should be read-only
   - Journey tracking should be hidden for competitor_claimed leads

---

## Data Load Integration

**Important:** Your weekly data load process needs to be updated.

### Old Way (Don't do this):
```python
# ❌ Don't update lead status anymore
lead.status = 'competitor_claimed'
```

### New Way:
```python
# ✅ Mark properties as deleted in lead_property table
# This should be done in your data load project after updating last_seen

def mark_deleted_properties_after_load(db):
    """Mark lead_property records as deleted if property wasn't in latest data load."""
    from datetime import datetime, timedelta
    import pytz
    
    # Calculate cutoff: most recent Monday at 6 PM Eastern
    eastern = pytz.timezone('America/New_York')
    now_eastern = datetime.now(eastern)
    days_since_monday = now_eastern.weekday()
    last_monday = now_eastern - timedelta(days=days_since_monday + 7)
    cutoff = last_monday.replace(hour=18, minute=0, second=0, microsecond=0)
    cutoff_utc = cutoff.astimezone(pytz.UTC)
    
    # Mark properties as deleted
    query = """
        UPDATE lead_property lp
        SET 
            deleted_from_source = TRUE,
            deleted_from_source_at = COALESCE(
                (SELECT p.last_seen FROM property p WHERE p.row_hash = lp.property_raw_hash),
                NOW()
            )
        FROM property p
        WHERE lp.property_raw_hash = p.row_hash
          AND p.last_seen < :cutoff
          AND lp.deleted_from_source = FALSE
    """
    
    result = db.execute(query, {"cutoff": cutoff_utc})
    db.commit()
    print(f"Marked {result.rowcount} properties as deleted_from_source")
```

**Integration Point:**
- Call this function **after** your data load updates `last_seen` for properties that appear
- Properties that don't appear in the new load will have old `last_seen` and will be marked as deleted

---

## Summary

### What Was Done

✅ **Phase 1:** Added database columns, removed enum value, created migration scripts  
✅ **Phase 2:** Migrated existing data to mark properties as deleted  
✅ **Phase 3:** Updated all code to use computed status, added UI badges  

### Key Benefits

- **More Accurate:** Tracks deletion at property level, not lead level
- **More Flexible:** Leads can have mixed deleted/active properties
- **Better UX:** Visual indicators show which properties are deleted
- **Computed Status:** `competitor_claimed` and `partially_claimed` computed on-the-fly

### Files Modified

**Database:**
- `scripts/sql/005_remove_competitor_claimed_add_property_deletion.sql`
- `scripts/sql/006_migrate_competitor_claimed_data.sql`

**Code:**
- `models.py`
- `utils/validators.py`
- `utils/__init__.py`
- `routers/leads.py`
- `routers/contacts.py`
- `routers/journey_api.py`
- `main.py`

**Templates:**
- `templates/lead_form.html`
- `templates/leads.html`

**Styles:**
- `static/css/styles.css`

---

## Troubleshooting

### Issue: Application won't start after migration

**Check:**
1. Did you run both SQL migrations in order?
2. Are you on the latest code version?
3. Check application logs for specific errors

### Issue: Status not showing correctly

**Check:**
1. Verify properties are loaded with the lead: `lead.properties`
2. Check if `deleted_from_source` values are set correctly in database
3. Verify template filters are registered in `main.py`

### Issue: Properties not marked as deleted after data load

**Check:**
1. Verify your data load project calls the mark function
2. Check cutoff timestamp calculation matches your data load schedule
3. Verify `last_seen` is being updated correctly for properties that appear

---

**Migration Complete!** 🎉

All phases are implemented and tested. The system now tracks property deletion at the property level and computes lead status accordingly.
