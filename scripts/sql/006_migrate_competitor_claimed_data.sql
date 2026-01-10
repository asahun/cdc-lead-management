-- ============================================
-- Migration: Migrate competitor_claimed data to property-level tracking
-- Phase 2: Data Migration
-- ============================================
-- This migration:
-- 1. Identifies leads that were previously competitor_claimed (now converted to 'new')
-- 2. Marks all their properties as deleted_from_source = TRUE
-- 3. Sets deleted_from_source_at timestamps
--
-- IMPORTANT: Run this AFTER Phase 1 migration (005_remove_competitor_claimed_add_property_deletion.sql)
-- ============================================

-- ============================================
-- STEP 1: Identify and migrate leads that should have deleted properties
-- ============================================
-- Since Phase 1 converted competitor_claimed leads to 'new', we need to identify
-- which leads should have their properties marked as deleted.
--
-- Strategy: Mark properties as deleted if:
-- 1. The property's last_seen in the property table is older than the cutoff (same logic as weekly refresh)
-- 2. OR if we have historical data indicating the property was claimed
--
-- For now, we'll use the property table's last_seen to determine if properties should be marked as deleted.
-- The weekly refresh job will handle this going forward.

DO $$
DECLARE
    cutoff_timestamp TIMESTAMPTZ;
    properties_marked_count INTEGER := 0;
    leads_affected_count INTEGER := 0;
BEGIN
    -- Calculate cutoff: most recent Monday at 6 PM Eastern (same as weekly refresh logic)
    -- Note: This is a simplified calculation. Adjust timezone as needed.
    cutoff_timestamp := date_trunc('week', now() AT TIME ZONE 'America/New_York') 
                        - interval '7 days' 
                        + interval '18 hours';
    
    RAISE NOTICE 'Using cutoff timestamp: %', cutoff_timestamp;
    
    -- Mark properties as deleted if their last_seen is older than cutoff
    -- This identifies properties that would have been marked as competitor_claimed
    WITH properties_to_mark AS (
        UPDATE lead_property lp
        SET 
            deleted_from_source = TRUE,
            deleted_from_source_at = COALESCE(
                (SELECT p.last_seen FROM property p WHERE p.row_hash = lp.property_raw_hash),
                now()
            )
        FROM property p
        WHERE lp.property_raw_hash = p.row_hash
          AND p.last_seen < cutoff_timestamp
          AND lp.deleted_from_source = FALSE
        RETURNING lp.lead_id
    )
    SELECT COUNT(DISTINCT lead_id) INTO leads_affected_count
    FROM properties_to_mark;
    
    GET DIAGNOSTICS properties_marked_count = ROW_COUNT;
    
    RAISE NOTICE 'Marked % properties as deleted_from_source', properties_marked_count;
    RAISE NOTICE 'Affected % leads', leads_affected_count;
END $$;

-- ============================================
-- STEP 2: Handle edge cases - properties not found in property table
-- ============================================
-- If a lead_property references a property that no longer exists in the property table,
-- it was likely already removed. Mark it as deleted.
DO $$
DECLARE
    orphaned_properties_count INTEGER;
BEGIN
    WITH orphaned_properties AS (
        UPDATE lead_property lp
        SET 
            deleted_from_source = TRUE,
            deleted_from_source_at = lp.added_at  -- Use when it was added as fallback
        WHERE NOT EXISTS (
            SELECT 1 FROM property p WHERE p.row_hash = lp.property_raw_hash
        )
        AND lp.deleted_from_source = FALSE
        RETURNING lp.id
    )
    SELECT COUNT(*) INTO orphaned_properties_count
    FROM orphaned_properties;
    
    IF orphaned_properties_count > 0 THEN
        RAISE NOTICE 'Marked % orphaned properties (not found in property table) as deleted', orphaned_properties_count;
    END IF;
END $$;

-- ============================================
-- STEP 3: Verify migration results
-- ============================================
DO $$
DECLARE
    total_deleted_properties INTEGER;
    leads_with_all_deleted INTEGER;
    leads_with_some_deleted INTEGER;
BEGIN
    -- Count total deleted properties
    SELECT COUNT(*) INTO total_deleted_properties
    FROM lead_property
    WHERE deleted_from_source = TRUE;
    
    -- Count leads where ALL properties are deleted
    SELECT COUNT(DISTINCT lead_id) INTO leads_with_all_deleted
    FROM lead_property
    WHERE deleted_from_source = TRUE
    GROUP BY lead_id
    HAVING COUNT(*) = (
        SELECT COUNT(*) 
        FROM lead_property lp2 
        WHERE lp2.lead_id = lead_property.lead_id
    );
    
    -- Count leads where SOME properties are deleted
    SELECT COUNT(DISTINCT lead_id) INTO leads_with_some_deleted
    FROM (
        SELECT lead_id
        FROM lead_property
        WHERE deleted_from_source = TRUE
        GROUP BY lead_id
        HAVING COUNT(*) < (
            SELECT COUNT(*) 
            FROM lead_property lp2 
            WHERE lp2.lead_id = lead_property.lead_id
        )
    ) subq;
    
    RAISE NOTICE '=== Migration Summary ===';
    RAISE NOTICE 'Total properties marked as deleted: %', total_deleted_properties;
    RAISE NOTICE 'Leads with ALL properties deleted: %', leads_with_all_deleted;
    RAISE NOTICE 'Leads with SOME properties deleted: %', leads_with_some_deleted;
END $$;

-- ============================================
-- Migration complete
-- ============================================
-- Next steps (Phase 3):
-- 1. Create helper functions to compute competitor_claimed status from properties
-- 2. Update all code references to use computed status
-- 3. Update UI to show property-level deletion status
-- ============================================
