#!/usr/bin/env python3
"""
Extract fillable form field names from a PDF file.

Usage:
    python scripts/extract_pdf_fields.py path/to/form.pdf
"""

import sys
import json
from pathlib import Path


def extract_fields_pypdf2(pdf_path: str) -> dict:
    """Extract fields using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        
        reader = PdfReader(pdf_path)
        fields = {}
        
        def get_field_value(obj, key, default=''):
            """Safely get value from PDF object."""
            try:
                if hasattr(obj, 'get'):
                    val = obj.get(key, default)
                    # Handle IndirectObject
                    if hasattr(val, 'get_object'):
                        return val.get_object()
                    return val
                return getattr(obj, key, default) if hasattr(obj, key) else default
            except:
                return default
        
        def process_field(field_ref, prefix=""):
            """Recursively process a field reference."""
            try:
                field_obj = field_ref.get_object() if hasattr(field_ref, 'get_object') else field_ref
                
                # Get field name
                field_name_obj = get_field_value(field_obj, '/T')
                if isinstance(field_name_obj, bytes):
                    field_name = field_name_obj.decode('utf-8', errors='ignore')
                else:
                    field_name = str(field_name_obj) if field_name_obj else 'Unnamed'
                
                full_name = f"{prefix}.{field_name}" if prefix else field_name
                
                # Get field type
                field_type = get_field_value(field_obj, '/FT', 'Unknown')
                if isinstance(field_type, bytes):
                    field_type = field_type.decode('utf-8', errors='ignore')
                else:
                    field_type = str(field_type)
                
                # Get field value
                field_value = get_field_value(field_obj, '/V', '')
                if isinstance(field_value, bytes):
                    field_value = field_value.decode('utf-8', errors='ignore')
                elif field_value:
                    field_value = str(field_value)
                else:
                    field_value = ''
                
                if field_name and field_name != 'Unnamed':
                    fields[full_name] = {
                        'type': field_type,
                        'value': field_value,
                        'method': 'PyPDF2'
                    }
                
                # Handle nested fields (Kids)
                kids = get_field_value(field_obj, '/Kids')
                if kids:
                    if not isinstance(kids, list):
                        kids = [kids]
                    for kid in kids:
                        process_field(kid, prefix=full_name if field_name else prefix)
                        
            except Exception as e:
                print(f"   Error processing field: {e}")
        
        root = reader.trailer.get('/Root', {})
        if isinstance(root, dict) and '/AcroForm' in root:
            acro_form = root['/AcroForm']
            if isinstance(acro_form, dict) and '/Fields' in acro_form:
                fields_list = acro_form['/Fields']
                if not isinstance(fields_list, list):
                    fields_list = [fields_list]
                for field_ref in fields_list:
                    process_field(field_ref)
        
        return fields
    except Exception as e:
        print(f"PyPDF2 extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def extract_fields_pypdf(pdf_path: str) -> dict:
    """Extract fields using pypdf (modern library)."""
    try:
        from pypdf import PdfReader
        
        reader = PdfReader(pdf_path)
        fields = {}
        
        if reader.metadata:
            print(f"PDF Title: {reader.metadata.get('/Title', 'N/A')}")
        
        # Try get_form_text_fields method
        try:
            form_fields = reader.get_form_text_fields()
            if form_fields:
                for field_name, field_value in form_fields.items():
                    # Try to find which page this field is on by checking annotations
                    page_num = None
                    for p_num, page in enumerate(reader.pages):
                        if '/Annots' in page:
                            annots = page['/Annots']
                            if annots:
                                for annot_ref in annots:
                                    try:
                                        annot = annot_ref.get_object()
                                        if annot.get('/T') == field_name:
                                            page_num = p_num + 1
                                            break
                                    except:
                                        pass
                            if page_num:
                                break
                    
                    fields[field_name] = {
                        'type': 'text',
                        'value': str(field_value) if field_value else '',
                        'method': 'pypdf (get_form_text_fields)',
                        'page': page_num
                    }
        except Exception as e:
            print(f"   get_form_text_fields failed: {e}")
        
        # Try accessing root/AcroForm structure
        try:
            if hasattr(reader, 'trailer') and reader.trailer:
                root = reader.trailer.get('/Root', {})
                if root and '/AcroForm' in root:
                    acro_form = root['/AcroForm']
                    if acro_form and '/Fields' in acro_form:
                        fields_list = acro_form['/Fields']
                        if not isinstance(fields_list, list):
                            fields_list = [fields_list]
                        
                        def process_field_pypdf(field_ref, prefix=""):
                            try:
                                field = field_ref.get_object() if hasattr(field_ref, 'get_object') else field_ref
                                field_name = field.get('/T', 'Unnamed')
                                if isinstance(field_name, bytes):
                                    field_name = field_name.decode('utf-8', errors='ignore')
                                else:
                                    field_name = str(field_name) if field_name else 'Unnamed'
                                
                                full_name = f"{prefix}.{field_name}" if prefix else field_name
                                field_type = field.get('/FT', 'Unknown')
                                field_value = field.get('/V', '')
                                
                                if field_name and field_name != 'Unnamed' and full_name not in fields:
                                    # Try to find page number by checking annotations
                                    page_num = None
                                    for p_num, page in enumerate(reader.pages):
                                        if '/Annots' in page:
                                            annots = page['/Annots']
                                            if annots:
                                                for annot_ref in annots:
                                                    try:
                                                        annot = annot_ref.get_object()
                                                        if annot.get('/T') == field_name:
                                                            page_num = p_num + 1
                                                            break
                                                    except:
                                                        pass
                                        if page_num:
                                            break
                                    
                                    fields[full_name] = {
                                        'type': str(field_type),
                                        'value': str(field_value) if field_value else '',
                                        'method': 'pypdf (AcroForm)',
                                        'page': page_num
                                    }
                                
                                # Handle Kids
                                kids = field.get('/Kids', [])
                                if kids:
                                    if not isinstance(kids, list):
                                        kids = [kids]
                                    for kid in kids:
                                        process_field_pypdf(kid, prefix=full_name if field_name else prefix)
                            except Exception as e:
                                pass
                        
                        for field_ref in fields_list:
                            process_field_pypdf(field_ref)
        except Exception as e:
            print(f"   AcroForm access failed: {e}")
        
        # Check for annotations (sometimes fields are stored as annotations)
        # Can specify start_page to skip early pages
        try:
            start_page = 0  # Can be overridden
            for page_num, page in enumerate(reader.pages):
                if page_num < start_page:
                    continue
                if '/Annots' in page:
                    annots = page['/Annots']
                    if annots:
                        print(f"   Found annotations on page {page_num + 1}")
                        for annot_ref in annots:
                            try:
                                annot = annot_ref.get_object()
                                annot_subtype = annot.get('/Subtype')
                                
                                # Check for Widget (form field) or Text (text annotation)
                                if annot_subtype in ['/Widget', '/Text']:
                                    field_name = annot.get('/T', 'Unnamed')
                                    if not field_name or field_name == 'Unnamed':
                                        # Try alternative name field
                                        field_name = annot.get('/NM', 'Unnamed')
                                    
                                    if field_name and field_name != 'Unnamed':
                                        field_value = annot.get('/V', '')
                                        fields[str(field_name)] = {
                                            'type': str(annot_subtype),
                                            'value': str(field_value) if field_value else '',
                                            'method': f'pypdf (annotation page {page_num + 1})',
                                            'page': page_num + 1  # Store page number
                                        }
                            except Exception as e:
                                pass
        except Exception as e:
            print(f"   Annotation check failed: {e}")
        
        return fields
    except ImportError:
        print("pypdf not installed, skipping...")
        return {}
    except Exception as e:
        print(f"pypdf extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def extract_fields_pdfrw(pdf_path: str) -> dict:
    """Extract fields using pdfrw."""
    try:
        from pdfrw import PdfReader
        from pypdf import PdfReader as PypdfReader
        
        reader = PdfReader(pdf_path)
        fields = {}
        
        # Also open with pypdf to get page information
        pypdf_reader = PypdfReader(pdf_path)
        
        if reader.Root and reader.Root.AcroForm and reader.Root.AcroForm.Fields:
            def process_field(field, prefix=""):
                """Recursively process fields (handles nested fields)."""
                field_name = field.T if hasattr(field, 'T') and field.T else None
                if field_name:
                    full_name = f"{prefix}.{field_name}" if prefix else field_name
                    field_type = field.FT if hasattr(field, 'FT') else 'Unknown'
                    field_value = field.V if hasattr(field, 'V') else ''
                    
                    # Try to find page number by checking annotations
                    page_num = None
                    for p_num, page in enumerate(pypdf_reader.pages):
                        if '/Annots' in page:
                            annots = page['/Annots']
                            if annots:
                                for annot_ref in annots:
                                    try:
                                        annot = annot_ref.get_object()
                                        if annot.get('/T') == field_name:
                                            page_num = p_num + 1
                                            break
                                    except:
                                        pass
                        if page_num:
                            break
                    
                    fields[full_name] = {
                        'type': str(field_type),
                        'value': str(field_value) if field_value else '',
                        'method': 'pdfrw',
                        'page': page_num
                    }
                
                # Handle nested fields (Kids)
                if hasattr(field, 'Kids') and field.Kids:
                    for kid in field.Kids:
                        process_field(kid, prefix=full_name if field_name else prefix)
            
            for field in reader.Root.AcroForm.Fields:
                process_field(field)
        
        return fields
    except ImportError:
        print("pdfrw not installed, skipping...")
        return {}
    except Exception as e:
        print(f"pdfrw extraction failed: {e}")
        return {}


def inspect_pdf_structure(pdf_path: str):
    """Inspect PDF structure to understand form type."""
    try:
        from pypdf import PdfReader
        
        reader = PdfReader(pdf_path)
        root = reader.trailer.get('/Root', {})
        
        print("\n[PDF Structure Inspection]")
        print("-" * 60)
        
        # Check for AcroForm
        if '/AcroForm' in root:
            acro_form = root['/AcroForm']
            print("✓ AcroForm found")
            print(f"  Keys: {list(acro_form.keys()) if isinstance(acro_form, dict) else 'N/A'}")
            
            # Check for XFA
            if '/XFA' in acro_form:
                print("⚠ XFA forms detected (XML Forms Architecture)")
                print("  This requires special handling - XFA is different from AcroForm")
            else:
                print("  No XFA detected")
            
            if '/Fields' in acro_form:
                fields = acro_form['/Fields']
                print(f"  Fields reference: {type(fields)}")
                if isinstance(fields, list):
                    print(f"  Number of field references: {len(fields)}")
        else:
            print("✗ No AcroForm found in PDF root")
        
        # Check pages for annotations (can specify start_page)
        start_page = 4  # Page 5 (0-indexed = 4)
        print(f"\nChecking pages {start_page + 1} to {len(reader.pages)} for annotations...")
        total_annots = 0
        annot_details = []
        
        for page_num, page in enumerate(reader.pages):
            if page_num < start_page:
                continue
            if '/Annots' in page:
                annots = page['/Annots']
                if annots:
                    count = len(annots) if isinstance(annots, list) else 1
                    total_annots += count
                    print(f"  Page {page_num + 1}: {count} annotation(s)")
                    
                    # Get details about annotations
                    if isinstance(annots, list):
                        for annot_ref in annots[:3]:  # Show first 3 details
                            try:
                                annot = annot_ref.get_object()
                                subtype = annot.get('/Subtype', 'Unknown')
                                name = annot.get('/T', annot.get('/NM', 'Unnamed'))
                                print(f"    - Type: {subtype}, Name: {name}")
                            except:
                                pass
        
        if total_annots > 0:
            print(f"\n✓ Total annotations found (pages {start_page + 1}+): {total_annots}")
        else:
            print(f"\n✗ No annotations found on pages {start_page + 1}+")
        
        print("-" * 60)
        
    except Exception as e:
        print(f"Structure inspection failed: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/extract_pdf_fields.py <path_to_pdf>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print(f"Extracting form fields from: {pdf_path}\n")
    print("=" * 60)
    
    # First, inspect the PDF structure
    inspect_pdf_structure(pdf_path)
    
    # Try multiple methods
    all_fields = {}
    
    # Try PyPDF2 (already in requirements)
    print("\n[1] Trying PyPDF2...")
    fields_pypdf2 = extract_fields_pypdf2(pdf_path)
    if fields_pypdf2:
        print(f"   Found {len(fields_pypdf2)} fields with PyPDF2")
        all_fields.update(fields_pypdf2)
    else:
        print("   No fields found with PyPDF2")
    
    # Try pypdf
    print("\n[2] Trying pypdf...")
    fields_pypdf = extract_fields_pypdf(pdf_path)
    if fields_pypdf:
        print(f"   Found {len(fields_pypdf)} fields with pypdf")
        all_fields.update(fields_pypdf)
    else:
        print("   No fields found with pypdf")
    
    # Try pdfrw
    print("\n[3] Trying pdfrw...")
    fields_pdfrw = extract_fields_pdfrw(pdf_path)
    if fields_pdfrw:
        print(f"   Found {len(fields_pdfrw)} fields with pdfrw")
        all_fields.update(fields_pdfrw)
    else:
        print("   No fields found with pdfrw")
    
    print("\n" + "=" * 60)
    print(f"\nTotal unique fields found: {len(all_fields)}\n")
    
    if all_fields:
        # Group fields by page
        fields_by_page = {}
        fields_no_page = []
        
        for field_name, field_info in all_fields.items():
            page_num = field_info.get('page')
            if page_num:
                if page_num not in fields_by_page:
                    fields_by_page[page_num] = []
                fields_by_page[page_num].append((field_name, field_info))
            else:
                fields_no_page.append((field_name, field_info))
        
        # Display organized by page
        print("Field Details (Grouped by Page):")
        print("=" * 60)
        
        # Sort pages
        for page_num in sorted(fields_by_page.keys()):
            page_fields = fields_by_page[page_num]
            print(f"\n📄 PAGE {page_num} ({len(page_fields)} fields)")
            print("-" * 60)
            for i, (field_name, field_info) in enumerate(sorted(page_fields), 1):
                print(f"  {i:2d}. {field_name}")
                print(f"      Type: {field_info['type']}")
                if field_info.get('value'):
                    print(f"      Value: {field_info['value']}")
                print(f"      Method: {field_info.get('method', 'unknown')}")
        
        # Fields without page info
        if fields_no_page:
            print(f"\n❓ FIELDS WITHOUT PAGE INFO ({len(fields_no_page)} fields)")
            print("-" * 60)
            for i, (field_name, field_info) in enumerate(sorted(fields_no_page), 1):
                print(f"  {i:2d}. {field_name}")
                print(f"      Type: {field_info['type']}")
                if field_info.get('value'):
                    print(f"      Value: {field_info['value']}")
                print(f"      Method: {field_info.get('method', 'unknown')}")
        
        # Save to JSON organized by page
        output_file = Path(pdf_path).stem + "_fields.json"
        output_by_page = {}
        for page_num in sorted(fields_by_page.keys()):
            output_by_page[f"page_{page_num}"] = {
                field_name: field_info for field_name, field_info in fields_by_page[page_num]
            }
        if fields_no_page:
            output_by_page["no_page_info"] = {
                field_name: field_info for field_name, field_info in fields_no_page
            }
        
        with open(output_file, 'w') as f:
            json.dump(output_by_page, f, indent=2)
        
        # Also save flat version for backward compatibility
        flat_output_file = Path(pdf_path).stem + "_fields_flat.json"
        with open(flat_output_file, 'w') as f:
            json.dump(all_fields, f, indent=2)
        
        print(f"\n✓ Field names saved to:")
        print(f"  - {output_file} (organized by page)")
        print(f"  - {flat_output_file} (flat structure)")
    else:
        print("⚠ No form fields found. The PDF might not have fillable fields,")
        print("  or the fields might be in a format not recognized by these libraries.")
        print("\nPossible reasons:")
        print("  - PDF uses XFA forms (requires different approach)")
        print("  - Fields are not properly defined in the PDF")
        print("  - PDF is image-based with overlay fields")


if __name__ == "__main__":
    main()

