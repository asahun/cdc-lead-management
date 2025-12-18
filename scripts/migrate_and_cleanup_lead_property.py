#!/usr/bin/env python3
"""
Consolidated migration script: Migrate data AND drop old columns in one go.

This script is for FRESH INSTALLS or when you want to migrate and clean up immediately.
It does everything in one run:
1. Creates the lead_property table
2. Migrates existing data from lead to lead_property
3. Drops old columns from lead immediately
4. Verifies everything is clean

IMPORTANT: Backup your database before running this!

Usage:
    python scripts/migrate_and_cleanup_lead_property.py

Environment Variables:
    DATABASE_URL - PostgreSQL connection string (optional, uses default if not set)
"""

import os
import sys
from pathlib import Path

# Add project root to Python path so we can import project modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, inspect
from db import engine, SessionLocal, Base
from models import LeadProperty

def check_table_exists(db, table_name: str) -> bool:
    """Check if a table exists in the database."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def check_column_exists(db, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def migrate_and_cleanup():
    """Run the migration and immediately drop old columns."""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("LeadProperty Migration & Cleanup Script")
        print("=" * 60)
        print()
        
        # Step 1: Create table
        print("Step 1: Creating lead_property table...")
        if check_table_exists(db, "lead_property"):
            print("⚠ Table 'lead_property' already exists. Skipping creation.")
        else:
            # Create table using SQLAlchemy
            LeadProperty.__table__.create(bind=engine, checkfirst=True)
            print("✓ Table 'lead_property' created successfully")
        
        # Step 2: Check if data already migrated
        existing_count = db.execute(text("SELECT COUNT(*) FROM lead_property")).scalar()
        if existing_count > 0:
            print(f"\n⚠ Found {existing_count} existing records in lead_property table.")
            print("  Migration will skip existing records (ON CONFLICT).")
        
        # Step 3: Migrate data
        print("\nStep 2: Migrating data from lead to lead_property...")
        
        # Check if old columns still exist
        has_old_columns = check_column_exists(db, "lead", "property_raw_hash")
        
        if has_old_columns:
            # Count leads with properties
            leads_with_properties = db.execute(text("""
                SELECT COUNT(*) FROM lead
                WHERE property_raw_hash IS NOT NULL
            """)).scalar()
            
            print(f"  Found {leads_with_properties} leads with properties to migrate")
            
            if leads_with_properties > 0:
                # Migrate data (using ON CONFLICT to handle duplicates gracefully)
                result = db.execute(text("""
                    INSERT INTO lead_property (lead_id, property_id, property_raw_hash, property_amount, is_primary, added_at)
                    SELECT 
                        id as lead_id,
                        property_id,
                        property_raw_hash,
                        property_amount,
                        true as is_primary,
                        created_at as added_at
                    FROM lead
                    WHERE property_raw_hash IS NOT NULL
                    ON CONFLICT (property_raw_hash) DO NOTHING
                """))
                migrated_count = result.rowcount
                print(f"✓ Migrated {migrated_count} properties")
            else:
                print("  No data to migrate.")
        else:
            print("  ⚠ Old columns already removed. No data to migrate.")
        
        # Step 4: Verify data integrity
        print("\nStep 3: Verifying data integrity...")
        
        property_count = db.execute(text("SELECT COUNT(*) FROM lead_property")).scalar()
        print(f"  LeadProperty records: {property_count}")
        
        if property_count > 0:
            # Check for NULLs in required fields
            null_check = db.execute(text("""
                SELECT COUNT(*) FROM lead_property 
                WHERE property_id IS NULL OR property_raw_hash IS NULL
            """)).scalar()
            if null_check == 0:
                print("✓ No NULL values in required fields")
            else:
                print(f"⚠ WARNING: Found {null_check} records with NULL values in required fields")
            
            # Check for leads without primary property
            leads_without_primary = db.execute(text("""
                SELECT COUNT(DISTINCT lead_id) FROM lead_property
                WHERE lead_id NOT IN (
                    SELECT DISTINCT lead_id FROM lead_property WHERE is_primary = true
                )
            """)).scalar()
            if leads_without_primary == 0:
                print("✓ All leads have a primary property")
            else:
                print(f"⚠ WARNING: Found {leads_without_primary} leads without a primary property")
        
        # Step 5: Drop old columns
        print("\nStep 4: Dropping old columns from lead...")
        
        if has_old_columns:
            db.execute(text("ALTER TABLE lead DROP COLUMN IF EXISTS property_id"))
            db.execute(text("ALTER TABLE lead DROP COLUMN IF EXISTS property_raw_hash"))
            db.execute(text("ALTER TABLE lead DROP COLUMN IF EXISTS property_amount"))
            print("✓ Old columns dropped successfully")
        else:
            print("  Old columns already removed. Nothing to drop.")
        
        # Verify columns are dropped
        remaining_columns = db.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'lead' 
            AND column_name IN ('property_id', 'property_raw_hash', 'property_amount')
        """)).fetchall()
        
        if remaining_columns:
            print(f"⚠ WARNING: Some columns still exist: {[c[0] for c in remaining_columns]}")
        else:
            print("✓ Verified: All old columns removed")
        
        db.commit()
        print("\n" + "=" * 60)
        print("✓ Migration and cleanup completed successfully!")
        print("=" * 60)
        print("\nThe database now uses only the new LeadProperty structure.")
        print("Old columns have been removed. No lingering old structure remains.")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Migration failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """Main entry point."""
    print("\n⚠ WARNING: This will modify your database!")
    print("This script will:")
    print("  1. Migrate data from old columns to lead_property table")
    print("  2. IMMEDIATELY drop old columns (property_id, property_raw_hash, property_amount)")
    print("  3. Leave only the new structure")
    print("\nPlease ensure you have a backup before proceeding.\n")
    
    response = input("Do you want to continue? (yes/no): ")
    if response.lower() == "yes":
        success = migrate_and_cleanup()
        sys.exit(0 if success else 1)
    else:
        print("Migration cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()

