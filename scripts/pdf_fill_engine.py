#!/usr/bin/env python3
"""
Shared PDF filler using PyMuPDF (fitz).
Sets widget values, regenerates appearance streams, preserves template alignment.
"""

import sys
from pathlib import Path
from typing import Dict, Any


def fill_pdf_fields(
    pdf_path: str,
    field_mapping: Dict[str, Any],
    output_path: str,
    *,
    draw_fallback: bool = False,
    font_size: float = 8.0,
    lock_fields: bool = False,
) -> bool:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("Error: PyMuPDF is required. Install with: pip install pymupdf")
        return False

    if not Path(pdf_path).exists():
        print(f"Error: PDF file not found: {pdf_path}")
        return False

    try:
        doc = fitz.open(pdf_path)
        print(f"✓ Opened PDF with {len(doc)} pages")

        filled_count = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            widgets = page.widgets() or []

            for widget in widgets:
                field_name = widget.field_name
                field_type = widget.field_type

                if field_name not in field_mapping:
                    continue

                value = field_mapping[field_name]
                try:
                    if draw_fallback:
                        # Draw text/checkmark directly and remove widget to ensure visibility across viewers,
                        # attempting to honor template font size and reasonable alignment heuristics.
                        if field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                            rect = widget.rect
                            # Use widget font size when available, else fallback.
                            fs = widget.text_fontsize or font_size
                            # Slight inset to avoid touching borders/labels.
                            padding_lr = 1
                            padding_top = 1
                            r_inset = fitz.Rect(rect.x0 + padding_lr, rect.y0 + padding_top, rect.x1 - padding_lr, rect.y1 - padding_lr)
                            # Heuristic alignment: center common id/number fields, left otherwise.
                            lname = (field_name or "").lower()
                            center_keys = ["control", "fein", "zip", "identifier", "id", "phone", "date"]
                            align = fitz.TEXT_ALIGN_CENTER if any(k in lname for k in center_keys) else fitz.TEXT_ALIGN_LEFT
                            status = page.insert_textbox(
                                r_inset,
                                str(value),
                                fontsize=fs,
                                fontname="helv",
                                color=(0, 0, 0),
                                align=align,
                            )
                            if status <= 0:
                                page.insert_text(
                                    (r_inset.x0, r_inset.y0),
                                    str(value),
                                    fontsize=fs,
                                    fontname="helv",
                                    color=(0, 0, 0),
                                )
                            try:
                                widget._annot.delete()
                            except Exception:
                                pass
                            filled_count += 1
                            print(f"  ✓ Drawn '{field_name}' on page {page_num + 1} with '{value}' (flattened, fs={fs}, align={'center' if align==fitz.TEXT_ALIGN_CENTER else 'left'})")
                        elif field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                            is_checked = False
                            if isinstance(value, bool):
                                is_checked = value
                            else:
                                is_checked = str(value).lower() in ['true', '1', 'yes', 'on', 'checked', 'x']
                            fs = widget.text_fontsize or font_size
                            if is_checked:
                                page.insert_textbox(
                                    widget.rect,
                                    "X",
                                    fontsize=fs,
                                    fontname="helv",
                                    color=(0, 0, 0),
                                    align=fitz.TEXT_ALIGN_CENTER,
                                )
                            try:
                                widget._annot.delete()
                            except Exception:
                                pass
                            filled_count += 1
                            print(f"  ✓ Drawn checkbox '{field_name}' on page {page_num + 1} to {is_checked} (flattened)")
                    else:
                        if field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                            if lock_fields:
                                widget.field_flags = (widget.field_flags or 0) | fitz.PDF_FIELD_IS_READ_ONLY
                            widget.field_value = str(value)
                            widget.update()
                            filled_count += 1
                            print(f"  ✓ Set '{field_name}' on page {page_num + 1} to '{value}' (template alignment)")
                        elif field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                            is_checked = False
                            if isinstance(value, bool):
                                is_checked = value
                            else:
                                is_checked = str(value).lower() in ['true', '1', 'yes', 'on', 'checked', 'x']
                            if lock_fields:
                                widget.field_flags = (widget.field_flags or 0) | fitz.PDF_FIELD_IS_READ_ONLY
                            widget.field_value = "On" if is_checked else "Off"
                            widget.update()
                            filled_count += 1
                            print(f"  ✓ Set checkbox '{field_name}' on page {page_num + 1} to {is_checked}")
                except Exception as e:
                    print(f"  ⚠ Could not fill '{field_name}': {e}")

        print(f"\n✓ Filled {filled_count} form fields")

        # Hint viewers to regenerate appearances if needed
        doc.need_appearances(True)
        doc.save(output_path, garbage=4, deflate=True, clean=True)
        print(f"  ✓ Saved filled PDF to: {output_path}")
        doc.close()
        return True
    except Exception as e:
        print(f"Error filling PDF: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    if len(sys.argv) < 4:
        print("Usage: python scripts/pdf_filler.py <pdf_path> <output_path> <field_mapping_json>")
        print("Note: field_mapping_json should be a path to a JSON file with a flat dict of field -> value.")
        sys.exit(1)

    import json

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]
    mapping_path = sys.argv[3]

    if not Path(mapping_path).exists():
        print(f"Error: mapping file not found: {mapping_path}")
        sys.exit(1)

    with open(mapping_path, "r") as f:
        mapping = json.load(f)

    ok = fill_pdf_fields(pdf_path, mapping, output_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()


