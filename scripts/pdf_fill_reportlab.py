"""
PDF filler using pdfrw + reportlab.

Reads widget positions from the template and draws text/checkmarks directly
onto an overlay, then merges that overlay back into the original PDF to
produce a flattened, viewer-agnostic output.
"""

from io import BytesIO
from typing import Dict, Any

from pdfrw import PdfReader, PdfWriter, PageMerge, PdfName
from reportlab.pdfgen import canvas


def _norm(key: str) -> str:
    return (key or "").strip().lower().replace(" ", "").replace("-", "").replace("__", "_")


def _parse_font_size(annot, default_size: float) -> float:
    try:
        da = getattr(annot, "DA", None)
        if not da:
            return default_size
        parts = str(da).replace("(", " ").replace(")", " ").split()
        if "Tf" in parts:
            idx = parts.index("Tf")
            if idx > 0:
                return float(parts[idx - 1])
    except Exception:
        pass
    return default_size


def fill_pdf_fields_reportlab(
    pdf_path: str,
    field_mapping: Dict[str, Any],
    output_path: str,
    *,
    font_name: str = "Helvetica",
    font_size: float = 9.0,
) -> bool:
    reader = PdfReader(pdf_path)
    normalized_map = {_norm(k): v for k, v in (field_mapping or {}).items()}
    used_keys = set()
    unmapped_fields = []

    overlay_buf = BytesIO()
    c = canvas.Canvas(overlay_buf)

    page_count = len(reader.pages)
    for page_index in range(page_count):
        page = reader.pages[page_index]
        mediabox = page.MediaBox
        width = float(mediabox[2]) - float(mediabox[0])
        height = float(mediabox[3]) - float(mediabox[1])
        c.setPageSize((width, height))

        annots = getattr(page, "Annots", []) or []
        for annot in annots:
            if getattr(annot, "Subtype", None) != PdfName.Widget:
                continue
            field_name = getattr(annot, "T", None)
            if not field_name:
                continue
            field_name = str(field_name).strip("()")
            value = None
            if field_name in field_mapping:
                value = field_mapping[field_name]
            else:
                norm = _norm(field_name)
                if norm in normalized_map:
                    value = normalized_map[norm]
            if value is None:
                unmapped_fields.append(field_name)
                continue
            used_keys.add(field_name)

            rect = annot.Rect
            if not rect or len(rect) != 4:
                continue
            x0, y0, x1, y1 = map(float, rect)
            box_h = y1 - y0
            fs = _parse_font_size(annot, font_size)
            text_y = y0 + max((box_h - fs) * 0.5, 0) + 0.5

            c.setFont(font_name, fs)

            if getattr(annot, "FT", None) == PdfName.Btn:
                is_checked = False
                if isinstance(value, bool):
                    is_checked = value
                else:
                    is_checked = str(value).lower() in ["true", "1", "yes", "on", "checked", "x"]
                if is_checked:
                    c.drawCentredString((x0 + x1) * 0.5, text_y, "X")
            else:
                # Default to left-align to preserve expected layout (avoid unintended centering)
                c.drawString(x0 + 1, text_y, str(value))

        c.showPage()

    c.save()

    overlay_pdf = PdfReader(fdata=overlay_buf.getvalue())
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i < len(overlay_pdf.pages):
            PageMerge(page).add(overlay_pdf.pages[i]).render()
        writer.addpage(page)
    writer.write(output_path)

    # Logging helpers
    unused_keys = [
        k for k in field_mapping.keys()
        if k not in used_keys and _norm(k) not in used_keys
    ]
    if unmapped_fields:
        print(f"[reportlab_filler] Unmapped form fields ({len(unmapped_fields)}): {unmapped_fields[:20]}{' ...' if len(unmapped_fields) > 20 else ''}")
    if unused_keys:
        print(f"[reportlab_filler] Mapping keys not used ({len(unused_keys)}): {unused_keys[:20]}{' ...' if len(unused_keys) > 20 else ''}")
    return True

