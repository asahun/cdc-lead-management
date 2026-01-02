"""
Claim routes and file management.
"""

from datetime import datetime
import json
import logging
import mimetypes
from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from db import get_db
from helpers.claim_files import get_claim_files_dir, list_claim_files, resolve_claim_file
from models import Claim, ClaimDocument, ClaimEvent, Lead
from services.agreement_service import (
    create_claim_from_lead,
    generate_agreements_for_claim,
    list_documents_for_claim,
    list_events_for_claim,
)

logger = logging.getLogger(__name__)

CLAIM_STATUS_VALUES = [
    "claim_created",
    "agreement_generated",
    "agreement_sent",
    "agreement_signed",
    "claim_preparing",
    "claim_submitted",
    "pending",
    "approved",
    "rejected",
    "more_info",
]

# Import shared templates from main to ensure filters are registered
# This will be set by main.py after filters are registered
templates = None  # Will be set by main.py

router = APIRouter()


@router.post("/claims")
async def claim_create(
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    lead_id = body.get("lead_id")
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")
    control_no = body.get("control_no") or ""
    formation_state = body.get("formation_state") or ""
    fee_pct = body.get("fee_pct") or "10"
    addendum_yes = bool(body.get("addendum_yes", False))
    entitled_business_name = body.get("entitled_business_name")
    entitled_business_same_as_owner = body.get("entitled_business_same_as_owner", True)

    try:
        result = create_claim_from_lead(
            db=db,
            lead_id=lead_id,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=fee_pct,
            addendum_yes=addendum_yes,
            user=None,
            entitled_business_name=entitled_business_name,
            entitled_business_same_as_owner=entitled_business_same_as_owner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("claim_create failed")
        raise HTTPException(status_code=500, detail="Failed to create claim")

    return result


@router.get("/claims", response_class=HTMLResponse)
def claims_list(
    request: Request,
    status: str = Query("", description="Filter by claim status"),
    db: Session = Depends(get_db),
):
    claims = db.query(Claim).order_by(Claim.created_at.desc()).all()
    claim_rows = []
    for claim in claims:
        events = list_events_for_claim(db, claim.id)
        status_events = [e for e in events if e.get("state") in CLAIM_STATUS_VALUES]
        last_event = status_events[0] if status_events else None
        doc_count = (
            db.query(ClaimDocument).filter(ClaimDocument.claim_id == claim.id).count()
        )
        last_event_created_at = None
        if last_event:
            ts = last_event.get("created_at")
            last_event_created_at = ts if isinstance(ts, str) else ts.isoformat() if ts else None
        current_state = last_event["state"] if last_event else None

        lead_owner = ""
        lead_status = ""
        if claim.lead_id:
            lead = db.query(Lead).filter(Lead.id == claim.lead_id).first()
            if lead:
                lead_owner = lead.owner_name or ""
                lead_status = str(lead.status) if getattr(lead, "status", None) else ""

        client = claim.client
        fee_display = None
        if claim.fee_flat:
            fee_display = f"${claim.fee_flat:,.2f}"
        elif claim.fee_pct:
            fee_display = f"{claim.fee_pct}%"

        claim_rows.append(
            {
                "id": claim.id,
                "claim_slug": claim.claim_slug,
                "lead_id": claim.lead_id,
                "lead_owner": lead_owner,
                "lead_status": lead_status,
                "control_no": client.control_no if client else None,
                "formation_state": client.formation_state if client else None,
                "fee_pct": str(claim.fee_pct) if claim.fee_pct else None,
                "fee_flat": str(claim.fee_flat) if claim.fee_flat else None,
                "fee_display": fee_display,
                "addendum_yes": claim.addendum_yes,
                "output_dir": claim.output_dir,
                "created_at": claim.created_at,
                "last_event": last_event,
                "last_event_created_at": last_event_created_at,
                "current_state": current_state,
                "doc_count": doc_count,
            }
        )
    if status:
        claim_rows = [c for c in claim_rows if c["current_state"] == status]

    return templates.TemplateResponse(
        "claims.html",
        {
            "request": request,
            "claims": claim_rows,
            "claim_status_values": CLAIM_STATUS_VALUES,
            "status_filter": status,
        },
    )


@router.get("/claims/{claim_id}", response_class=HTMLResponse)
def claim_detail(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    client = claim.client
    primary_contact = None
    secondary_contact = None
    check_address = claim.check_mailing_address

    if client:
        from models import ClientContact, SignerType

        contacts = db.query(ClientContact).filter(ClientContact.client_id == client.id).all()
        for contact in contacts:
            if contact.signer_type == SignerType.primary:
                primary_contact = contact
            elif contact.signer_type == SignerType.secondary:
                secondary_contact = contact

    lead_primary_contact = None
    if claim.lead:
        for c in claim.lead.contacts:
            if c.is_primary:
                lead_primary_contact = c
                break

    lead_primary_contact_json = {}
    if lead_primary_contact:
        lead_primary_contact_json = {
            "contact_name": lead_primary_contact.contact_name or "",
            "title": lead_primary_contact.title or "",
            "email": lead_primary_contact.email or "",
            "phone": lead_primary_contact.phone or "",
            "address_street": lead_primary_contact.address_street or "",
            "address_city": lead_primary_contact.address_city or "",
            "address_state": lead_primary_contact.address_state or "",
            "address_zipcode": lead_primary_contact.address_zipcode or "",
        }

    total_properties = 0
    total_amount = 0.0
    if claim.lead:
        from models import LeadProperty

        properties = (
            db.query(LeadProperty).filter(LeadProperty.lead_id == claim.lead.id).all()
        )
        total_properties = len(properties)
        for prop in properties:
            if prop.property_amount:
                total_amount += float(prop.property_amount)

    cdr_fee = None
    if claim.fee_flat:
        cdr_fee = float(claim.fee_flat)
    elif claim.fee_pct and total_amount > 0:
        cdr_fee = float(total_amount) * (float(claim.fee_pct) / 100.0)

    if (
        claim.total_properties != total_properties
        or claim.total_amount != total_amount
        or (cdr_fee and claim.cdr_fee != cdr_fee)
    ):
        claim.total_properties = total_properties
        claim.total_amount = total_amount
        if cdr_fee:
            claim.cdr_fee = cdr_fee
        db.commit()

    events = list_events_for_claim(db, claim.id)
    status_events = [e for e in events if e.get("state") in CLAIM_STATUS_VALUES]
    current_status = status_events[0]["state"] if status_events else None
    docs = list_documents_for_claim(db, claim.id)
    generated_docs = [
        d for d in docs if d["doc_type"] in ("agreement_generated", "authorization_generated")
    ]
    package_docs = [
        d for d in docs if d["doc_type"] not in ("agreement_generated", "authorization_generated")
    ]

    check_address_same_as_contact = False
    if check_address and lead_primary_contact:
        check_address_same_as_contact = (
            (check_address.street or "") == (lead_primary_contact.address_street or "")
            and (check_address.city or "") == (lead_primary_contact.address_city or "")
            and (check_address.state or "") == (lead_primary_contact.address_state or "")
            and (check_address.zip or "") == (lead_primary_contact.address_zipcode or "")
            and check_address.line2 is None
        )

    return templates.TemplateResponse(
        "claim_detail.html",
        {
            "request": request,
            "claim": claim,
            "client": client,
            "primary_contact": primary_contact,
            "secondary_contact": secondary_contact,
            "check_address": check_address,
            "lead_primary_contact": lead_primary_contact,
            "lead_primary_contact_json": json.dumps(lead_primary_contact_json),
            "check_address_same_as_contact": check_address_same_as_contact,
            "events": events,
            "current_status": current_status,
            "generated_docs": generated_docs,
            "package_docs": package_docs,
            "download_base": "",
            "claim_status_values": CLAIM_STATUS_VALUES,
        },
    )


@router.get("/claims/{claim_id}/events")
def claim_events(
    claim_id: int,
    db: Session = Depends(get_db),
):
    try:
        events = list_events_for_claim(db, claim_id)
    except Exception:
        logger.exception("claim_events failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim events")
    return {"events": events}


@router.get("/claims/{claim_id}/documents")
def claim_documents(
    claim_id: int,
    db: Session = Depends(get_db),
):
    try:
        docs = list_documents_for_claim(db, claim_id)
    except Exception:
        logger.exception("claim_documents failed")
        raise HTTPException(status_code=500, detail="Failed to fetch claim documents")
    for d in docs:
        d["download_url"] = f"/claims/{claim_id}/documents/{d['id']}/download"
        d["preview_url"] = f"/claims/{claim_id}/documents/{d['id']}/download?inline=1"
    return {"documents": docs}


@router.get("/claims/{claim_id}/documents/{doc_id}/download")
def claim_document_download(
    claim_id: int,
    doc_id: int,
    inline: bool = Query(False),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(ClaimDocument)
        .filter(ClaimDocument.id == doc_id, ClaimDocument.claim_id == claim_id)
        .one_or_none()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=404, detail="File not found")
    media_type, _ = mimetypes.guess_type(doc.file_path)
    media_type = media_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=doc.file_path,
        filename=doc.original_name or Path(doc.file_path).name,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{Path(doc.file_path).name}"'},
    )


@router.get("/claims/{claim_id}/files")
def claim_files(
    claim_id: int,
    type: str = Query("generated", regex="^(generated|package)$"),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    target = get_claim_files_dir(base_dir, type)
    files = list_claim_files(target)
    for f in files:
        f["download_url"] = f"/claims/{claim_id}/files/download?type={type}&name={f['name']}"
        f["preview_url"] = f"{f['download_url']}&inline=1"
    return {"files": files}


@router.get("/claims/{claim_id}/files/download")
def claim_file_download(
    claim_id: int,
    name: str = Query(...),
    type: str = Query("generated", regex="^(generated|package)$"),
    inline: bool = Query(False),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    try:
        file_path = resolve_claim_file(base_dir, type, name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path")
    media_type, _ = mimetypes.guess_type(str(file_path))
    media_type = media_type or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    return FileResponse(
        path=str(file_path),
        filename=name,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


@router.delete("/claims/{claim_id}/files")
def claim_file_delete(
    claim_id: int,
    name: str = Query(...),
    type: str = Query("generated", regex="^(generated|package)$"),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    base_dir = Path(claim.output_dir or "")
    try:
        file_path = resolve_claim_file(base_dir, type, name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path")

    file_path_absolute = str(file_path.resolve()).replace("\\", "/")
    file_path_relative = str(file_path).replace("\\", "/")

    all_docs = db.query(ClaimDocument).filter(ClaimDocument.claim_id == claim.id).all()

    doc = None
    for d in all_docs:
        if not d.file_path:
            continue
        normalized_db_path = d.file_path.replace("\\", "/")

        if normalized_db_path == file_path_absolute or normalized_db_path == file_path_relative:
            doc = d
            break

        try:
            stored_absolute = str(Path(d.file_path).resolve()).replace("\\", "/")
            if stored_absolute == file_path_absolute:
                doc = d
                break
        except Exception:
            pass

        db_filename = normalized_db_path.split("/")[-1].split("\\")[-1]
        target_filename = name

        if db_filename == target_filename:
            doc = d
            break

        if normalized_db_path.endswith("/" + name) or normalized_db_path.endswith("\\" + name):
            doc = d
            break
        if normalized_db_path.endswith(name):
            doc = d
            break

    file_path.unlink(missing_ok=True)

    doc_type_for_event = None
    original_name_for_event = name
    docs_to_delete = []

    if doc:
        doc_type_for_event = doc.doc_type
        original_name_for_event = doc.original_name or name
        docs_to_delete.append(doc)

        duplicates = (
            db.query(ClaimDocument)
            .filter(
                ClaimDocument.claim_id == claim.id,
                ClaimDocument.doc_type == doc.doc_type,
                ClaimDocument.original_name == doc.original_name,
                ClaimDocument.id != doc.id,
            )
            .all()
        )

        if duplicates:
            docs_to_delete.extend(duplicates)

    for d in docs_to_delete:
        db.delete(d)

    if docs_to_delete:
        db.flush()
        for d in docs_to_delete:
            still_exists = db.query(ClaimDocument).filter(ClaimDocument.id == d.id).first()
            if still_exists:
                logger.error("Document %s still exists after delete and flush!", d.id)
    else:
        logger.warning(
            "ClaimDocument not found for deletion: claim_id=%s, name=%s, type=%s",
            claim.id,
            name,
            type,
        )

    event_state = "generated_file_deleted" if type == "generated" else "package_file_deleted"
    event = ClaimEvent(
        claim_id=claim.id,
        state=event_state,
        payload=json.dumps(
            {"file_type": type, "doc_type": doc_type_for_event, "name": original_name_for_event, "file_name": name}
        ),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    return {"deleted": True}


@router.post("/claims/{claim_id}/documents/upload")
async def claim_upload_document(
    claim_id: int,
    doc_type: str = Form(...),
    notes: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if not doc_type:
        raise HTTPException(status_code=400, detail="doc_type is required")
    if not file:
        raise HTTPException(status_code=400, detail="file is required")

    if not claim.output_dir:
        claim.output_dir = str(Path("scripts/pdf_output") / f"claim-{claim.id}")
    output_dir = Path(claim.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    package_dir = output_dir / "package"
    package_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest_path = package_dir / safe_name
    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    normalized_file_path = str(dest_path.resolve()).replace("\\", "/")

    existing_doc = (
        db.query(ClaimDocument)
        .filter(
            ClaimDocument.claim_id == claim.id,
            ClaimDocument.doc_type == doc_type,
            ClaimDocument.file_path == normalized_file_path,
        )
        .first()
    )

    if not existing_doc:
        relative_path = str(dest_path).replace("\\", "/")
        existing_doc = (
            db.query(ClaimDocument)
            .filter(
                ClaimDocument.claim_id == claim.id,
                ClaimDocument.doc_type == doc_type,
                ClaimDocument.file_path == relative_path,
            )
            .first()
        )

    if not existing_doc:
        all_same_type = (
            db.query(ClaimDocument)
            .filter(ClaimDocument.claim_id == claim.id, ClaimDocument.doc_type == doc_type)
            .all()
        )
        for d in all_same_type:
            try:
                stored_resolved = str(Path(d.file_path).resolve()).replace("\\", "/")
                if stored_resolved == normalized_file_path:
                    existing_doc = d
                    break
            except Exception:
                pass

    if existing_doc:
        existing_doc.file_path = normalized_file_path
        existing_doc.original_name = file.filename or safe_name
        if notes:
            existing_doc.notes = notes
        doc = existing_doc
    else:
        doc = ClaimDocument(
            claim_id=claim.id,
            doc_type=doc_type,
            original_name=file.filename or safe_name,
            file_path=normalized_file_path,
            notes=notes,
        )
        db.add(doc)

    upload_event = ClaimEvent(
        claim_id=claim.id,
        state="package_file_uploaded",
        payload=json.dumps({"doc_type": doc_type, "name": file.filename or safe_name, "file_name": safe_name}),
        created_at=datetime.utcnow(),
    )
    db.add(upload_event)
    db.commit()

    return {
        "id": doc.id,
        "doc_type": doc.doc_type,
        "original_name": doc.original_name,
        "file_path": doc.file_path,
        "notes": doc.notes,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.post("/claims/{claim_id}/agreements/generate")
async def claim_generate_agreements(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    control_no = body.get("control_no") or ""
    formation_state = body.get("formation_state") or ""
    fee_pct = body.get("fee_pct")
    fee_flat = body.get("fee_flat")
    addendum_yes = bool(body.get("addendum_yes", False))

    if not control_no or not formation_state:
        raise HTTPException(status_code=400, detail="control_no and formation_state are required")

    if not fee_pct and not fee_flat:
        fee_pct = "10"

    try:
        result = generate_agreements_for_claim(
            db=db,
            claim_id=claim_id,
            control_no=control_no,
            formation_state=formation_state,
            fee_pct=fee_pct or "10",
            addendum_yes=addendum_yes,
            user=None,
            fee_flat=fee_flat,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("claim_generate_agreements failed")
        raise HTTPException(status_code=500, detail="Failed to generate agreements")

    return result


@router.post("/claims/{claim_id}/client-info")
async def claim_save_client_info(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from models import Client, ClientContact, ClientMailingAddress, SignerType

    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if not claim.lead:
        raise HTTPException(status_code=400, detail="Lead not found for claim")

    body = await request.json()

    client = claim.client
    if not client:
        client = Client(
            entitled_business_name=body.get("entitled_business_name", ""),
            formation_state=None,
            control_no=None,
        )
        db.add(client)
        db.flush()
        claim.client_id = client.id
        db.flush()

    client.entitled_business_name = body.get("entitled_business_name", "")
    if "control_no" in body:
        client.control_no = body.get("control_no") or None
    if "formation_state" in body:
        client.formation_state = body.get("formation_state") or None

    claim.entitled_business_name = body.get("entitled_business_name", "")
    claim.entitled_business_same_as_owner = body.get("entitled_business_same_as_owner", True)

    fee_type = body.get("fee_type", "percentage")
    if fee_type == "flat":
        fee_flat_val = body.get("fee_flat")
        if fee_flat_val:
            claim.fee_flat = float(fee_flat_val)
            claim.fee_pct = None
        else:
            claim.fee_pct = 10.0
            claim.fee_flat = None
    else:
        fee_pct_val = body.get("fee_pct", "10")
        claim.fee_pct = float(fee_pct_val) if fee_pct_val else 10.0
        claim.fee_flat = None

    if "addendum_yes" in body:
        claim.addendum_yes = body.get("addendum_yes", False)

    if claim.lead:
        from models import LeadProperty

        properties = (
            db.query(LeadProperty).filter(LeadProperty.lead_id == claim.lead.id).all()
        )
        total_amount = sum(
            float(p.property_amount) if p.property_amount else 0.0 for p in properties
        )
        if claim.fee_flat:
            claim.cdr_fee = float(claim.fee_flat)
        elif claim.fee_pct and total_amount > 0:
            claim.cdr_fee = round(total_amount * (float(claim.fee_pct) / 100.0), 2)

    lead_primary_contact = None
    for c in claim.lead.contacts:
        if c.is_primary:
            lead_primary_contact = c
            break

    primary_signer_same = body.get("primary_signer_same_as_contact", False)
    primary_signer_data = body.get("primary_signer")

    if primary_signer_same and lead_primary_contact:
        primary_client_contact = (
            db.query(ClientContact)
            .filter(
                ClientContact.client_id == client.id,
                ClientContact.signer_type == SignerType.primary,
            )
            .first()
        )
        if not primary_client_contact:
            name_parts = (lead_primary_contact.contact_name or "").strip().split(" ", 1)
            first_name = name_parts[0] if name_parts else ""
            last_name = name_parts[1] if len(name_parts) > 1 else ""
            primary_client_contact = ClientContact(
                client_id=client.id,
                lead_contact_id=lead_primary_contact.id,
                signer_type=SignerType.primary,
                first_name=first_name,
                last_name=last_name,
                title=lead_primary_contact.title,
                email=lead_primary_contact.email,
                phone=lead_primary_contact.phone,
            )
            db.add(primary_client_contact)
        else:
            name_parts = (lead_primary_contact.contact_name or "").strip().split(" ", 1)
            primary_client_contact.first_name = name_parts[0] if name_parts else ""
            primary_client_contact.last_name = name_parts[1] if len(name_parts) > 1 else ""
            primary_client_contact.title = lead_primary_contact.title
            primary_client_contact.email = lead_primary_contact.email
            primary_client_contact.phone = lead_primary_contact.phone
            primary_client_contact.lead_contact_id = lead_primary_contact.id
    elif primary_signer_data:
        primary_client_contact = (
            db.query(ClientContact)
            .filter(
                ClientContact.client_id == client.id,
                ClientContact.signer_type == SignerType.primary,
            )
            .first()
        )
        if not primary_client_contact:
            primary_client_contact = ClientContact(
                client_id=client.id,
                signer_type=SignerType.primary,
                first_name=primary_signer_data.get("first_name", ""),
                last_name=primary_signer_data.get("last_name", ""),
                title=primary_signer_data.get("title"),
                email=primary_signer_data.get("email"),
                phone=primary_signer_data.get("phone"),
            )
            db.add(primary_client_contact)
        else:
            primary_client_contact.first_name = primary_signer_data.get("first_name", "")
            primary_client_contact.last_name = primary_signer_data.get("last_name", "")
            primary_client_contact.title = primary_signer_data.get("title")
            primary_client_contact.email = primary_signer_data.get("email")
            primary_client_contact.phone = primary_signer_data.get("phone")
            primary_client_contact.lead_contact_id = None

    secondary_signer_enabled = body.get("secondary_signer_enabled", False)
    secondary_signer_data = body.get("secondary_signer")

    existing_secondary = (
        db.query(ClientContact)
        .filter(
            ClientContact.client_id == client.id,
            ClientContact.signer_type == SignerType.secondary,
        )
        .first()
    )

    if secondary_signer_enabled and secondary_signer_data and (
        secondary_signer_data.get("first_name") or secondary_signer_data.get("last_name")
    ):
        if not existing_secondary:
            secondary_client_contact = ClientContact(
                client_id=client.id,
                signer_type=SignerType.secondary,
                first_name=secondary_signer_data.get("first_name", ""),
                last_name=secondary_signer_data.get("last_name", ""),
                title=secondary_signer_data.get("title"),
                email=secondary_signer_data.get("email"),
                phone=secondary_signer_data.get("phone"),
            )
            db.add(secondary_client_contact)
        else:
            existing_secondary.first_name = secondary_signer_data.get("first_name", "")
            existing_secondary.last_name = secondary_signer_data.get("last_name", "")
            existing_secondary.title = secondary_signer_data.get("title")
            existing_secondary.email = secondary_signer_data.get("email")
            existing_secondary.phone = secondary_signer_data.get("phone")
    elif not secondary_signer_enabled and existing_secondary:
        db.delete(existing_secondary)

    check_address_same = body.get("check_address_same_as_contact", False)
    check_address_data = body.get("check_address")

    check_address = (
        db.query(ClientMailingAddress).filter(ClientMailingAddress.client_id == client.id).first()
    )

    if check_address_same and lead_primary_contact:
        if not check_address:
            check_address = ClientMailingAddress(
                client_id=client.id,
                street=lead_primary_contact.address_street or "",
                line2=None,
                city=lead_primary_contact.address_city or "",
                state=lead_primary_contact.address_state or "",
                zip=lead_primary_contact.address_zipcode or "",
            )
            db.add(check_address)
            db.flush()
        else:
            check_address.street = lead_primary_contact.address_street or ""
            check_address.city = lead_primary_contact.address_city or ""
            check_address.state = lead_primary_contact.address_state or ""
            check_address.zip = lead_primary_contact.address_zipcode or ""
            check_address.line2 = None
        claim.check_mailing_address_id = check_address.id
    elif check_address_data:
        if not check_address:
            check_address = ClientMailingAddress(
                client_id=client.id,
                street=check_address_data.get("street", ""),
                line2=check_address_data.get("line2"),
                city=check_address_data.get("city", ""),
                state=check_address_data.get("state", ""),
                zip=check_address_data.get("zip", ""),
            )
            db.add(check_address)
            db.flush()
        else:
            check_address.street = check_address_data.get("street", "")
            check_address.line2 = check_address_data.get("line2")
            check_address.city = check_address_data.get("city", "")
            check_address.state = check_address_data.get("state", "")
            check_address.zip = check_address_data.get("zip", "")
        claim.check_mailing_address_id = check_address.id

    primary_signer_same = body.get("primary_signer_same_as_contact", False)
    check_address_same = body.get("check_address_same_as_contact", False)
    save_event_payload = {
        "entitled_business_name": claim.entitled_business_name,
        "control_no": client.control_no,
        "formation_state": client.formation_state,
        "fee_type": fee_type,
        "fee_pct": str(claim.fee_pct) if claim.fee_pct else None,
        "fee_flat": str(claim.fee_flat) if claim.fee_flat else None,
        "addendum_yes": claim.addendum_yes,
        "primary_signer_same_as_contact": primary_signer_same,
        "check_address_same_as_contact": check_address_same,
    }
    save_event = ClaimEvent(
        claim_id=claim.id,
        state="client_claim_data_saved",
        payload=json.dumps(save_event_payload),
        created_at=datetime.utcnow(),
    )
    db.add(save_event)
    db.commit()

    return {"success": True, "message": "Client and claim information saved"}


@router.post("/claims/{claim_id}/status")
async def claim_set_status(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.json()
    state = body.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="state is required")
    if state not in CLAIM_STATUS_VALUES:
        raise HTTPException(status_code=400, detail="invalid state")

    claim = db.query(Claim).filter(Claim.id == claim_id).one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    event = ClaimEvent(
        claim_id=claim.id,
        state=state,
        payload=json.dumps({"status": state}),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    return {
        "id": event.id,
        "state": event.state,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
