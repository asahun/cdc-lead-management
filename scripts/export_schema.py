#!/usr/bin/env python3
"""
Database Schema Export Script

Exports the PostgreSQL database schema (tables, types, constraints, etc.)
to SQL files for backup and recreation on different machines.

Usage:
    python scripts/export_schema.py

Environment Variables:
    DATABASE_URL - PostgreSQL connection string
        Format: postgresql://user:password@host:port/database
        or: postgresql+psycopg2://user:password@host:port/database
        Default: postgresql+psycopg2://ucp_app:EJe5&fWgxt6gow@localhost:5432/ucp

Output:
    docs/schema/schema.sql - Current schema (overwrites on each run)
    docs/schema/schema_YYYYMMDD_HHMMSS.sql - Timestamped backup (optional)
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote


def parse_database_url(database_url: str) -> dict:
    """
    Parse PostgreSQL connection URL into components.
    
    Handles both postgresql:// and postgresql+psycopg2:// formats.
    """
    # Remove the driver prefix if present (postgresql+psycopg2://)
    if "://" in database_url:
        # Extract the part after the last + or ://
        if "+" in database_url.split("://")[0]:
            # postgresql+psycopg2://user:pass@host:port/db
            url_part = database_url.split("://", 1)[1]
            database_url = f"postgresql://{url_part}"
    
    parsed = urlparse(database_url)
    
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": parsed.path.lstrip("/") if parsed.path else None,
    }


def export_schema(
    host: str,
    port: int,
    user: str,
    database: str,
    password: str = None,
    output_dir: Path = None,
    create_backup: bool = True,
) -> tuple[Path, Path | None]:
    """
    Export database schema using pg_dump.
    
    Returns:
        (main_schema_path, backup_path or None)
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent / "docs" / "schema"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    main_schema_path = output_dir / "schema.sql"
    backup_path = None
    
    # Create timestamped backup if requested and main file exists
    if create_backup and main_schema_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = output_dir / f"schema_{timestamp}.sql"
        print(f"Creating backup: {backup_path.name}")
    
    # Build pg_dump command
    cmd = [
        "pg_dump",
        "--schema-only",  # Only schema, no data
        "--no-owner",     # Don't include ownership commands
        "--no-privileges", # Don't include privilege commands
        "--host", host,
        "--port", str(port),
        "--username", user,
        "--dbname", database,
        "--file", str(main_schema_path),
    ]
    
    # Set password via environment variable (more secure than command line)
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    
    print(f"Exporting schema from {user}@{host}:{port}/{database}...")
    print(f"Output: {main_schema_path}")
    
    try:
        result = subprocess.run(
            cmd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        
        # Copy to backup if needed
        if backup_path:
            import shutil
            shutil.copy2(main_schema_path, backup_path)
            print(f"Backup created: {backup_path.name}")
        
        print("✓ Schema exported successfully")
        return main_schema_path, backup_path
        
    except subprocess.CalledProcessError as e:
        print(f"✗ Error running pg_dump:", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("✗ Error: pg_dump not found. Please install PostgreSQL client tools.", file=sys.stderr)
        print("  On macOS: brew install postgresql", file=sys.stderr)
        print("  On Ubuntu: sudo apt-get install postgresql-client", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://ucp_app:EJe5&fWgxt6gow@localhost:5432/ucp"
    )
    
    db_config = parse_database_url(database_url)
    
    if not db_config["user"] or not db_config["database"]:
        print("✗ Error: DATABASE_URL must include username and database name", file=sys.stderr)
        sys.exit(1)
    
    # Allow backup creation to be disabled via environment variable
    create_backup = os.getenv("SCHEMA_EXPORT_BACKUP", "true").lower() == "true"
    
    main_path, backup_path = export_schema(
        host=db_config["host"],
        port=db_config["port"],
        user=db_config["user"],
        database=db_config["database"],
        password=db_config["password"],
        create_backup=create_backup,
    )
    
    print(f"\nSchema exported to: {main_path}")
    if backup_path:
        print(f"Backup saved to: {backup_path}")
    print("\nTo recreate database on another machine:")
    print(f"  psql -U {db_config['user']} -d {db_config['database']} < {main_path}")


if __name__ == "__main__":
    main()

