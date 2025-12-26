#!/usr/bin/env python3
"""
Handler for Recover Authorization Letter: builds field mapping from test data
and delegates filling to the shared pdf_filler.
"""

import json
import sys
from pathlib import Path

from scripts.pdf_fill_engine import fill_pdf_fields


def build_field_mapping(business: dict, claimant: dict, cdr_profile: dict) -> dict:
    """Return a flat mapping of field_name -> value for the Recover Authorization Letter."""
    field_mapping = {}

    # Business fields
    field_mapping.update(
        {
            "business_name": business.get("name", ""),
            "business_formation_state": business.get("formation_state", ""),
            "business_taxid": business.get("fein", ""),
            "business_control_no ": business.get("control_no", ""),
            "business_street": business.get("street", ""),
            "business_city": business.get("city", ""),
            "business_state": business.get("state", ""),
            "business_zip": business.get("zip", ""),
        }
    )

    # CDR/static profile
    field_mapping.update(
        {
            "cdr_identifier": cdr_profile.get("cdr_identifier", ""),
            "cdr_street": cdr_profile.get("agent_street", ""),
            "cdr_city": cdr_profile.get("agent_city", ""),
            "cdr_state": cdr_profile.get("agent_state", ""),
            "cdr_zip": cdr_profile.get("agent_zip", ""),
            "cdr_agent_email": cdr_profile.get("agent_email", ""),
            "cdr_agent_phone": cdr_profile.get("agent_phone", ""),
        }
    )

    # Claimant (primary contact)
    field_mapping.update(
        {
            "primary_claimant_fullname": claimant.get("name", ""),
            "primary_claimant_title": claimant.get("title", ""),
            "business_name": business.get("name", ""),
            "primary_claimant_sign": "",
            "primary_claimant_sign_date": "",
        }
    )

    # Agent (static profile)
    field_mapping.update(
        {
            "cdr_agent_name": cdr_profile.get("agent_name", ""),
            "cdr_agent_title": cdr_profile.get("agent_title", ""),
            "cdr_agent_sign": "",
            "cdr_agent_sign_date": "",
        }
    )

    return field_mapping


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/fill_recover_authorization_letter.py <pdf_path> [data_json_path] [output_path]"
        )
        sys.exit(1)

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "scripts/pdf_templates/Recover_Authorization_Letter.pdf"
    data_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/test_data_recover_authorization_letter.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "scripts/pdf_output/Recover_Authorization_Letter_filled.pdf"

    if not Path(pdf_path).exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    if not Path(data_path).exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)

    with open(data_path, "r") as f:
        data = json.load(f)

    cdr_path = Path("scripts/data/cdr_profile.json")
    if not cdr_path.exists():
        print(f"Error: CDR profile file not found: {cdr_path}")
        sys.exit(1)
    with open(cdr_path, "r") as f:
        cdr_profile = json.load(f)

    business = data.get("business", {})
    claimant = data.get("primary_contact", {})

    # Required checks
    required_business = ["name", "formation_state", "control_no", "street", "city", "state", "zip"]
    missing_business = [k for k in required_business if not business.get(k)]
    required_claimant = ["name", "title", "email", "phone", "mail"]
    missing_claimant = [k for k in required_claimant if not claimant.get(k)]
    if missing_business:
        print(f"Error: Missing required business fields: {missing_business}")
        sys.exit(1)
    if missing_claimant:
        print(f"Error: Missing required claimant/contact fields: {missing_claimant}")
        sys.exit(1)

    print(f"Filling Recover Authorization Letter using data file: {data_path}")
    field_mapping = build_field_mapping(business, claimant, cdr_profile)

    print("\nField mappings:")
    for field_name, value in sorted(field_mapping.items()):
        print(f"  {field_name:30s} = {value}")

    # Preserve template alignment/appearance and mark fields read-only (no drawing fallback).
    success = fill_pdf_fields(pdf_path, field_mapping, output_path, draw_fallback=False, lock_fields=True)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()


