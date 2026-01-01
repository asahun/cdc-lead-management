#!/usr/bin/env python3
"""
Recovery Agreement handler for UP-CDR2: build field mapping from lead/property/contact
data and delegate filling to the reportlab/pdfrw filler.
"""

import json
import sys
from pathlib import Path

from scripts.pdf_fill_reportlab import fill_pdf_fields_reportlab


def parse_input(data):
    """Support both legacy list input and structured dict input."""
    if isinstance(data, list):
        properties = data
        primary_contact = {}
        meta = {}
    else:
        properties = data.get("properties", [])
        primary_contact = data.get("primary_contact", {})
        meta = data.get("meta", {})
    return properties, primary_contact, meta


def build_field_mapping(properties, primary_contact, meta, cdr_profile):
    field_mapping = {}
    # Property rows
    for i, item in enumerate(properties, start=1):
        property_id_field = f"id_property_{i}"
        amount_field = f"amount_property_{i}"
        field_mapping[property_id_field] = item.get("property_id", "")
        field_mapping[amount_field] = item.get("amount", "")

    # Totals
    total_sum = 0.0
    for i in range(1, 16):
        amt = field_mapping.get(f"amount_property_{i}", "")
        try:
            total_sum += float(str(amt).replace(",", ""))
        except Exception:
            pass
    fee_pct_val = float(meta.get("cdr_fee_percentage", meta.get("cdr_fee_flat", 10.0)))
    recovered_pct = max(0.0, 100.0 - fee_pct_val)
    fee_amount = round(total_sum * (fee_pct_val / 100.0), 2)
    net_pay = round(total_sum - fee_amount, 2)

    field_mapping["total_properties_amount"] = f"{total_sum:,.2f}"
    field_mapping["cdr_fee_percentage"] = f"{fee_pct_val:.0f}"
    field_mapping["cdr_fee_amount"] = f"{fee_amount:,.2f}"
    field_mapping["claimant_net_pay"] = f"{net_pay:,.2f}"

    # Primary contact (required)
    field_mapping.update(
        {
            "primary_claimant_fullname": primary_contact.get("name", ""),
            "primary_claimant_phone": primary_contact.get("phone", ""),
            "primary_claimant_mail": primary_contact.get("mail", ""),
            "primary_claimant_email": primary_contact.get("email", ""),
            "business_taxid": primary_contact.get("taxid_ssn", ""),
            # Secondary intentionally left blank
            "secondary_claimant_name": "",
            "secondary_claimant_phone": "",
            "secondary_claimant_mail": "",
            "secondary_claimant_email": "",
            "secondary_ business_taxid": "",
        }
    )

    # CDR/profile data + meta
    addendum_yes = bool(meta.get("addendum_yes", False))
    field_mapping.update(
        {
            "cdr_name": cdr_profile.get("cdr_name", ""),
            "cdr_name_2": cdr_profile.get("cdr_name", ""),  # Alias for template duplicate field
            "cdr_address": f"{cdr_profile.get('agent_street', '')}, {cdr_profile.get('agent_city', '')} {cdr_profile.get('agent_state', '')} {cdr_profile.get('agent_zip', '')}".strip(),
            "cdr_identifier": cdr_profile.get("cdr_identifier", ""),
            "cdr_agent_name": cdr_profile.get("agent_name", ""),
            "cdr_agent_phone": cdr_profile.get("agent_phone", ""),
            "cdr_agent_email": cdr_profile.get("agent_email", ""),
            "addendum_yes": addendum_yes,
            "addendum_no": not addendum_yes,
            # Fee fields (ensure explicitly present)
            "cdr_fee_percentage": f"{fee_pct_val:.0f}",
            "cdr_fee_amount": f"{fee_amount:,.2f}",
            "claimant_net_pay": f"{net_pay:,.2f}",
            "claimant_recovered_percentage": f"{recovered_pct:.0f}",
            # Aliases in case template duplicates
            "cdr_fee_percentage_2": f"{fee_pct_val:.0f}",
            "cdr_fee_amount_2": f"{fee_amount:,.2f}",
            "claimant_net_pay_2": f"{net_pay:,.2f}",
            "claimant_recovered_percentage_2": f"{recovered_pct:.0f}",
        }
    )

    return field_mapping


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fill_recovery_agreement.py <pdf_path> [data_json_path] [output_path]")
        sys.exit(1)

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "scripts/pdf_templates/UP-CDR2_Recovery_Agreement.pdf"
    data_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/test_data_recovery_agreement.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "scripts/pdf_output/UP-CDR2 Recovery Agreement_filled.pdf"

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

    properties, primary_contact, meta = parse_input(data)

    # Validate required primary contact fields
    required_contact_fields = ["name", "phone", "mail", "email"]
    missing = [k for k in required_contact_fields if not primary_contact.get(k)]
    if missing:
        print(f"Error: Missing required primary contact fields: {missing}")
        sys.exit(1)

    print(f"Filling Recovery Agreement with {len(properties)} property rows...")
    field_mapping = build_field_mapping(properties, primary_contact, meta, cdr_profile)

    print("\nField mappings (including computed and contact data):")
    for field_name, value in sorted(field_mapping.items()):
        print(f"  {field_name:25s} = {value}")

    # Flatten via reportlab/pdfrw to ensure consistent rendering across viewers.
    success = fill_pdf_fields_reportlab(pdf_path, field_mapping, output_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()


