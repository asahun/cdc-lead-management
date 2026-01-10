-- ============================================
-- Migration: Remove competitor_claimed status and add property deletion tracking
-- Phase 1: Data Model Changes
-- ============================================
-- This migration:
-- 1. Adds deleted_from_source and deleted_from_source_at columns to lead_property table
-- 2. Removes competitor_claimed from lead_status enum type
--
-- IMPORTANT: This migration should be run BEFORE Phase 2 (data migration)
-- ============================================

-- ============================================
-- STEP 1: Add new columns to lead_property table
-- ============================================
-- Add deleted_from_source column (tracks if property was removed from weekly data source)
ALTER TABLE lead_property 
ADD COLUMN IF NOT EXISTS deleted_from_source BOOLEAN NOT NULL DEFAULT FALSE;

-- Add deleted_from_source_at column (timestamp when property was marked as deleted)
ALTER TABLE lead_property 
ADD COLUMN IF NOT EXISTS deleted_from_source_at TIMESTAMPTZ NULL;

-- Add index for efficient queries on deleted_from_source
CREATE INDEX IF NOT EXISTS idx_lead_property_deleted_from_source 
ON lead_property(deleted_from_source) 
WHERE deleted_from_source = TRUE;

-- Add index for efficient queries on deleted_from_source_at
CREATE INDEX IF NOT EXISTS idx_lead_property_deleted_from_source_at 
ON lead_property(deleted_from_source_at) 
WHERE deleted_from_source_at IS NOT NULL;

-- ============================================
-- STEP 2: Remove competitor_claimed from lead_status enum
-- ============================================
-- PostgreSQL doesn't support directly removing enum values.
-- We'll convert the column to text, drop/recreate the enum, then convert back.

-- Step 2a: Check if competitor_claimed exists in any leads
-- Convert them to 'new' status first (will be properly migrated in Phase 2)
DO $$
DECLARE
    competitor_claimed_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO competitor_claimed_count
    FROM lead
    WHERE status = 'competitor_claimed';
    
    IF competitor_claimed_count > 0 THEN
        RAISE NOTICE 'Found % leads with competitor_claimed status. Converting to ''new'' (will be properly migrated in Phase 2).', competitor_claimed_count;
        UPDATE lead 
        SET status = 'new'::lead_status
        WHERE status = 'competitor_claimed';
    ELSE
        RAISE NOTICE 'No leads found with competitor_claimed status.';
    END IF;
END $$;

-- Step 2b: Convert status column to text temporarily
ALTER TABLE lead 
ALTER COLUMN status TYPE TEXT 
USING status::text;

-- Step 2c: Drop the existing enum type
DROP TYPE IF EXISTS lead_status;

-- Step 2d: Recreate enum type without competitor_claimed
CREATE TYPE lead_status AS ENUM (
    'new',
    'researching',
    'contact_in_progress',
    'response_received',
    'claim_created',
    'no_response',
    'ready'
);

-- Step 2e: Convert status column back to enum type
ALTER TABLE lead 
ALTER COLUMN status TYPE lead_status 
USING status::lead_status;

-- ============================================
-- STEP 3: Verify changes
-- ============================================
-- Verify columns were added
DO $$
DECLARE
    deleted_col_exists BOOLEAN;
    deleted_at_col_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'lead_property' 
        AND column_name = 'deleted_from_source'
    ) INTO deleted_col_exists;
    
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'lead_property' 
        AND column_name = 'deleted_from_source_at'
    ) INTO deleted_at_col_exists;
    
    IF deleted_col_exists AND deleted_at_col_exists THEN
        RAISE NOTICE '✓ Columns added successfully to lead_property table';
    ELSE
        RAISE WARNING '✗ Some columns may not have been added correctly';
    END IF;
END $$;

-- Verify enum type was updated
DO $$
DECLARE
    enum_values TEXT[];
BEGIN
    SELECT array_agg(enumlabel ORDER BY enumsortorder)
    INTO enum_values
    FROM pg_enum
    WHERE enumtypid = 'lead_status'::regtype;
    
    IF 'competitor_claimed' = ANY(enum_values) THEN
        RAISE WARNING '✗ competitor_claimed still exists in enum type';
    ELSE
        RAISE NOTICE '✓ competitor_claimed removed from lead_status enum';
    END IF;
    
    RAISE NOTICE 'Current lead_status enum values: %', array_to_string(enum_values, ', ');
END $$;

-- ============================================
-- Migration complete
-- ============================================
-- Next steps (Phase 2):
-- 1. Migrate existing competitor_claimed leads to mark their properties as deleted_from_source
-- 2. Update those leads to appropriate status (new/researching/etc.)
-- ============================================
