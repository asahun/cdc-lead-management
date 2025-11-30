# main.py
from datetime import datetime
from io import BytesIO
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, cast, String, update

from db import Base, SessionLocal, engine
from models import (
    PropertyView,
    BusinessLead,
    LeadStatus,
    LeadContact,
    LeadAttempt,
    LeadComment,
    ContactChannel,
    OwnerType,
    BusinessOwnerStatus,
    OwnerSize,
    IndividualOwnerStatus,
    ContactType,
)

from letters import (
    LetterGenerationError,
    get_property_for_lead,
    render_letter_pdf,
)
from gpt_api import fetch_entity_intelligence, GPTConfigError, GPTServiceError

from fastapi.templating import Jinja2Templates


Base.metadata.create_all(
    bind=engine,
    tables=[
        BusinessLead.__table__,
        LeadContact.__table__,
        LeadAttempt.__table__,
        LeadComment.__table__,
    ],
)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def bootstrap_assignment_flags():
    _sync_existing_property_assignments()


def format_currency(value):
    if value is None or value == "":
        return "—"

    if isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return str(value)

    return f"${decimal_value:,.2f}"


templates.env.filters["currency"] = format_currency



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

PAGE_SIZE = 20
PROPERTY_MIN_AMOUNT = Decimal("10000")
PROPERTY_AMOUNT_FILTER = PropertyView.propertyamount >= PROPERTY_MIN_AMOUNT
PROPERTY_ORDERING = (
    PropertyView.propertyamount.desc(),
    PropertyView.raw_hash.asc(),
)


def _mark_property_assigned(db: Session, property_raw_hash: str | None, property_id: str | None):
    update_stmt = None
    if property_raw_hash:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.raw_hash == property_raw_hash)
            .values(assigned_to_lead=True)
        )
    elif property_id:
        update_stmt = (
            update(PropertyView)
            .where(PropertyView.propertyid == property_id)
            .values(assigned_to_lead=True)
        )

    if update_stmt is not None:
        db.execute(update_stmt)


def _sync_existing_property_assignments():
    db = SessionLocal()
    try:
        raw_hashes = {
            value
            for value in db.scalars(
                select(BusinessLead.property_raw_hash).where(
                    BusinessLead.property_raw_hash.is_not(None)
                )
            ).all()
            if value
        }
        if raw_hashes:
            db.execute(
                update(PropertyView)
                .where(PropertyView.raw_hash.in_(tuple(raw_hashes)))
                .values(assigned_to_lead=True)
            )

        property_ids = {
            value
            for value in db.scalars(
                select(BusinessLead.property_id).where(
                    BusinessLead.property_id.is_not(None)
                )
            ).all()
            if value
        }
        if property_ids:
            db.execute(
                update(PropertyView)
                .where(PropertyView.propertyid.in_(tuple(property_ids)))
                .values(assigned_to_lead=True)
            )

        if raw_hashes or property_ids:
            db.commit()
    finally:
        db.close()


def _get_property_by_id(db: Session, property_id: str) -> PropertyView | None:
    return db.scalar(
        select(PropertyView)
        .where(PROPERTY_AMOUNT_FILTER)
        .where(PropertyView.propertyid == property_id)
    )


def _get_property_by_order(db: Session, order_id: int) -> PropertyView | None:
    raw_hash = _get_raw_hash_for_order(db, order_id)
    if not raw_hash:
        return None
    return _get_property_by_raw_hash(db, raw_hash)


def _get_property_by_raw_hash(db: Session, raw_hash: str) -> PropertyView | None:
    return db.scalar(
        select(PropertyView)
        .where(PROPERTY_AMOUNT_FILTER)
        .where(PropertyView.raw_hash == raw_hash)
    )


def _ranked_navigation_row(db: Session, raw_hash: str):
    ranked = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
            func.lag(PropertyView.raw_hash).over(order_by=PROPERTY_ORDERING).label("prev_hash"),
            func.lead(PropertyView.raw_hash).over(order_by=PROPERTY_ORDERING).label("next_hash"),
        )
        .where(PROPERTY_AMOUNT_FILTER)
        .subquery()
    )
    return db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_hash,
            ranked.c.next_hash,
        ).where(ranked.c.raw_hash == raw_hash)
    ).one_or_none()


def _property_navigation_info(db: Session, raw_hash: str):
    nav_row = _ranked_navigation_row(db, raw_hash)
    if not nav_row:
        return {
            "order_id": None,
            "prev_order_id": None,
            "next_order_id": None,
            "prev_hash": None,
            "next_hash": None,
        }

    order_id = nav_row.order_id
    prev_hash = nav_row.prev_hash
    next_hash = nav_row.next_hash

    return {
        "order_id": order_id,
        "prev_order_id": order_id - 1 if prev_hash else None,
        "next_order_id": order_id + 1 if next_hash else None,
        "prev_hash": prev_hash,
        "next_hash": next_hash,
    }


def _get_raw_hash_for_order(db: Session, order_id: int) -> str | None:
    ranked = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
        )
        .where(PROPERTY_AMOUNT_FILTER)
        .subquery()
    )
    return db.scalar(
        select(ranked.c.raw_hash).where(ranked.c.order_id == order_id)
    )


def _build_gpt_payload(lead: BusinessLead, prop: PropertyView) -> dict[str, Any]:
    report_year_value = None
    if getattr(prop, "reportyear", None):
        try:
            report_year_value = int(str(prop.reportyear))
        except (TypeError, ValueError):
            report_year_value = None

    return {
        "business_name": lead.owner_name or prop.ownername or "",
        "property_state": prop.ownerstate or "",
        "holder_name_on_record": prop.holdername,
        "last_activity_date": prop.lastactivitydate,
        "property_report_year": report_year_value,
    }

@app.get("/", response_class=HTMLResponse)
@app.get("/properties", response_class=HTMLResponse)
def list_properties(
    request: Request,
    page: int = 1,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    filters = [PROPERTY_AMOUNT_FILTER]

    if q:
        pattern = f"%{q}%"
        prop_id_text = cast(PropertyView.propertyid, String)
        filters.append(
            or_(
                prop_id_text.ilike(pattern),
                PropertyView.ownername.ilike(pattern),
            )
        )

    count_stmt = (
        select(func.count())
        .select_from(PropertyView)
        .where(*filters)
    )

    ranked_stmt = (
        select(
            PropertyView.raw_hash.label("raw_hash"),
            PropertyView.propertyid.label("propertyid"),
            PropertyView.ownername.label("ownername"),
            PropertyView.propertyamount.label("propertyamount"),
            PropertyView.assigned_to_lead.label("assigned_to_lead"),
            func.row_number().over(order_by=PROPERTY_ORDERING).label("order_id"),
        )
        .where(*filters)
    )

    ranked_subq = ranked_stmt.subquery()
    stmt = (
        select(ranked_subq)
        .order_by(ranked_subq.c.order_id)
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )

    rows_result = db.execute(stmt).mappings().all()
    rows = [dict(row) for row in rows_result]
    total = db.scalar(count_stmt) or 0

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    return templates.TemplateResponse(
        "properties.html",
        {
            "request": request,
            "properties": rows,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
        },
    )


@app.get(
    "/properties/{property_id}",
    response_class=HTMLResponse,
)
def property_detail(
    request: Request,
    property_id: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )

@app.get("/leads/new_from_property", response_class=HTMLResponse)
def new_lead_from_property(
    request: Request,
    property_id: str,
    db: Session = Depends(get_db),
):
    # 1) Ensure we actually got a non-empty property_id
    if not property_id:
        raise HTTPException(status_code=400, detail="property_id query parameter is required")

    # 2) Fetch row from the view using propertyid as PK
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail=f"Property '{property_id}' not found in view")

    if prop.assigned_to_lead:
        existing_lead = db.scalar(
            select(BusinessLead).where(
                or_(
                    BusinessLead.property_raw_hash == prop.raw_hash,
                    BusinessLead.property_id == prop.propertyid,
                )
            )
        )
        if existing_lead:
            return RedirectResponse(
                url=f"/leads/{existing_lead.id}/edit",
                status_code=303,
            )
        raise HTTPException(
            status_code=400,
            detail="This property is already linked to an existing lead.",
        )

    # 3) Pass the 3 fields to the template
    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": None,
            "mode": "create",
            "property_id": prop.propertyid,          # view column
            "owner_name": prop.ownername,           # view column
            "property_amount": prop.propertyamount, # view column
            "statuses": list(LeadStatus),
            "contacts": [],
            "attempts": [],
            "channels": list(ContactChannel),
            "comments": [],
            "owner_types": list(OwnerType),
            "business_owner_statuses": list(BusinessOwnerStatus),
            "owner_sizes": list(OwnerSize),
            "individual_owner_statuses": list(IndividualOwnerStatus),
            "contact_types": list(ContactType),
            "owner_type": OwnerType.business,
            "business_owner_status": BusinessOwnerStatus.active,
            "owner_size": OwnerSize.corporate,
            "individual_owner_status": IndividualOwnerStatus.alive,
            "new_business_name": "",
            "contact_edit_target": None,
            "property_raw_hash": getattr(prop, "raw_hash", None),
            "can_generate_letters": False,
        },
    )


@app.get("/api/properties/{property_id}")
def property_detail_json(
    property_id: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    column_names = prop.__table__.columns.keys()
    data = {column: getattr(prop, column) for column in column_names}

    nav = _property_navigation_info(db, prop.raw_hash)

    return JSONResponse(
        {
            "property": data,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )


@app.get("/properties/by_hash/{raw_hash}", response_class=HTMLResponse)
def property_detail_by_hash(
    request: Request,
    raw_hash: str,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_raw_hash(db, raw_hash)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@app.get("/properties/by_order/{order_id}", response_class=HTMLResponse)
def property_detail_by_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_order(db, order_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    nav = _property_navigation_info(db, prop.raw_hash)

    context = request.query_params.get("context", "")
    show_navigation = context != "lead"
    show_add_to_lead = context != "lead" and not prop.assigned_to_lead

    return templates.TemplateResponse(
        "property_detail.html",
        {
            "request": request,
            "property": prop,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"] if show_navigation else None,
            "next_order_id": nav["next_order_id"] if show_navigation else None,
            "prev_raw_hash": nav["prev_hash"] if show_navigation else None,
            "next_raw_hash": nav["next_hash"] if show_navigation else None,
            "show_navigation": show_navigation,
            "show_add_to_lead": show_add_to_lead,
        },
    )


@app.get("/api/properties/by_order/{order_id}")
def property_detail_json_by_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    prop = _get_property_by_order(db, order_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    column_names = prop.__table__.columns.keys()
    data = {column: getattr(prop, column) for column in column_names}

    nav = _property_navigation_info(db, prop.raw_hash)

    return JSONResponse(
        {
            "property": data,
            "order_id": nav["order_id"],
            "prev_order_id": nav["prev_order_id"],
            "next_order_id": nav["next_order_id"],
            "prev_raw_hash": nav["prev_hash"],
            "next_raw_hash": nav["next_hash"],
        }
    )


@app.post("/leads/create")
def create_lead(
    property_id: str = Form(...),
    owner_name: str = Form(...),
    property_amount: float | None = Form(None),
    property_raw_hash: str | None = Form(None),
    status: LeadStatus = Form(LeadStatus.new),
    notes: str | None = Form(None),
    owner_type: OwnerType = Form(OwnerType.business),
    business_owner_status: BusinessOwnerStatus | None = Form(None),
    owner_size: OwnerSize | None = Form(None),
    new_business_name: str | None = Form(None),
    individual_owner_status: IndividualOwnerStatus | None = Form(None),
    db: Session = Depends(get_db),
):
    if owner_type == OwnerType.business:
        individual_owner_status = None
        if not business_owner_status:
            business_owner_status = BusinessOwnerStatus.active
        if not owner_size:
            owner_size = OwnerSize.corporate
        if business_owner_status not in (
            BusinessOwnerStatus.acquired_or_merged,
            BusinessOwnerStatus.active_renamed,
        ):
            new_business_name = None
        else:
            if not new_business_name or not new_business_name.strip():
                raise HTTPException(
                    status_code=400,
                    detail="New owner name is required when status is acquired_or_merged or active_renamed.",
                )
    else:
        business_owner_status = None
        owner_size = None
        new_business_name = None
        if not individual_owner_status:
            individual_owner_status = IndividualOwnerStatus.alive

    lead = BusinessLead(
        property_id=property_id,
        owner_name=owner_name,
        property_amount=property_amount,
        status=status,
        notes=notes,
        owner_type=owner_type,
        business_owner_status=business_owner_status,
        owner_size=owner_size,
        new_business_name=new_business_name,
        individual_owner_status=individual_owner_status,
        property_raw_hash=property_raw_hash,
    )
    db.add(lead)
    _mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()
    db.refresh(lead)
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)

@app.get("/leads", response_class=HTMLResponse)
def list_leads(
    request: Request,
    page: int = 1,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1

    stmt = select(BusinessLead)
    count_stmt = select(func.count()).select_from(BusinessLead)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )
        count_stmt = count_stmt.where(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(BusinessLead.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    leads = db.scalars(stmt).all()

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1

    return templates.TemplateResponse(
        "leads.html",
        {
            "request": request,
            "leads": leads,
            "page": page,
            "total_pages": total_pages,
            "q": q or "",
            "total": total,
        },
    )


@app.get("/leads/{lead_id}/entity-intel")
async def lead_entity_intelligence(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    prop: PropertyView | None = None
    if lead.property_raw_hash:
        prop = _get_property_by_raw_hash(db, lead.property_raw_hash)

    if not prop and lead.property_id:
        prop = _get_property_by_id(db, lead.property_id)

    if not prop:
        raise HTTPException(
            status_code=404,
            detail="Linked property record not found for this lead.",
        )

    payload = _build_gpt_payload(lead, prop)

    try:
        analysis = await run_in_threadpool(fetch_entity_intelligence, payload)
    except GPTConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GPTServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"input": payload, "analysis": analysis}


@app.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def edit_lead(
    request: Request,
    lead_id: int,
    edit_contact_id: int | None = None,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contacts = list(lead.contacts)
    attempts = sorted(
        lead.attempts,
        key=lambda attempt: attempt.created_at or datetime.min,
        reverse=True,
    )
    comments = sorted(
        lead.comments,
        key=lambda comment: comment.created_at or datetime.min,
        reverse=True,
    )

    contact_edit_target = None
    if edit_contact_id:
        contact_edit_target = next(
            (contact for contact in contacts if contact.id == edit_contact_id),
            None,
        )

    return templates.TemplateResponse(
        "lead_form.html",
        {
            "request": request,
            "lead": lead,
            "mode": "edit",
            "property_id": lead.property_id,
            "owner_name": lead.owner_name,
            "property_amount": lead.property_amount,
            "statuses": list(LeadStatus),
            "contacts": contacts,
            "attempts": attempts,
            "channels": list(ContactChannel),
            "comments": comments,
            "contact_edit_target": contact_edit_target,
            "owner_types": list(OwnerType),
            "business_owner_statuses": list(BusinessOwnerStatus),
            "owner_sizes": list(OwnerSize),
            "individual_owner_statuses": list(IndividualOwnerStatus),
            "contact_types": list(ContactType),
            "owner_type": lead.owner_type,
            "business_owner_status": lead.business_owner_status,
            "owner_size": lead.owner_size,
            "new_business_name": lead.new_business_name or "",
            "individual_owner_status": lead.individual_owner_status,
            "property_raw_hash": lead.property_raw_hash,
            "can_generate_letters": bool(lead.property_raw_hash or lead.property_id),
        },
    )


@app.post("/leads/{lead_id}/update")
def update_lead(
    lead_id: int,
    property_id: str = Form(...),
    owner_name: str = Form(...),
    property_amount: float | None = Form(None),
    property_raw_hash: str | None = Form(None),
    status: LeadStatus = Form(LeadStatus.new),
    notes: str | None = Form(None),
    owner_type: OwnerType = Form(OwnerType.business),
    business_owner_status: BusinessOwnerStatus | None = Form(None),
    owner_size: OwnerSize | None = Form(None),
    new_business_name: str | None = Form(None),
    individual_owner_status: IndividualOwnerStatus | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if owner_type == OwnerType.business:
        individual_owner_status = None
        if not business_owner_status:
            business_owner_status = BusinessOwnerStatus.active
        if not owner_size:
            owner_size = OwnerSize.corporate
        if business_owner_status not in (
            BusinessOwnerStatus.acquired_or_merged,
            BusinessOwnerStatus.active_renamed,
        ):
            new_business_name = None
        else:
            if not new_business_name or not new_business_name.strip():
                raise HTTPException(
                    status_code=400,
                    detail="New owner name is required when status is acquired_or_merged or active_renamed.",
                )
    else:
        business_owner_status = None
        owner_size = None
        if not individual_owner_status:
            individual_owner_status = IndividualOwnerStatus.alive
        new_business_name = None

    lead.property_id = property_id
    lead.owner_name = owner_name
    lead.property_amount = property_amount
    lead.status = status
    lead.notes = notes
    lead.owner_type = owner_type
    lead.business_owner_status = business_owner_status
    lead.owner_size = owner_size
    lead.new_business_name = new_business_name
    lead.individual_owner_status = individual_owner_status
    lead.property_raw_hash = property_raw_hash

    lead.updated_at = datetime.utcnow()

    _mark_property_assigned(db, property_raw_hash, property_id)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead.id}/edit", status_code=303)

# ---------- CONTACTS FOR A LEAD ----------

@app.get("/leads/{lead_id}/contacts", response_class=HTMLResponse)
def lead_contacts(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return RedirectResponse(
        url=f"/leads/{lead.id}/edit#contacts",
        status_code=302,
    )


@app.post("/leads/{lead_id}/contacts/create")
def create_lead_contact(
    lead_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = LeadContact(
        lead_id=lead.id,
        contact_name=contact_name,
        title=title,
        email=email,
        phone=phone,
        linkedin_url=linkedin_url,
        address_street=address_street,
        address_city=address_city,
        address_state=address_state or "GA",
        address_zipcode=address_zipcode,
        contact_type=contact_type,
    )
    db.add(contact)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/delete")
def delete_lead_contact(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    db.delete(contact)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/update")
def update_lead_contact(
    lead_id: int,
    contact_id: int,
    contact_name: str = Form(...),
    title: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    linkedin_url: str | None = Form(None),
    address_street: str | None = Form(None),
    address_city: str | None = Form(None),
    address_state: str | None = Form(None),
    address_zipcode: str | None = Form(None),
    contact_type: ContactType = Form(ContactType.employee),
    db: Session = Depends(get_db),
):
    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.contact_name = contact_name
    contact.title = title
    contact.email = email
    contact.phone = phone
    contact.linkedin_url = linkedin_url
    contact.address_street = address_street
    contact.address_city = address_city
    contact.address_state = address_state or "GA"
    contact.address_zipcode = address_zipcode
    contact.contact_type = contact_type
    contact.updated_at = datetime.utcnow()

    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#contacts", status_code=303)


@app.post("/leads/{lead_id}/contacts/{contact_id}/letters")
def generate_contact_letter(
    lead_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    contact = db.get(LeadContact, contact_id)
    if not contact or contact.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    if not any([contact.address_street, contact.address_city, contact.address_state, contact.address_zipcode]):
        raise HTTPException(
            status_code=400,
            detail="Contact must have an address before generating a letter.",
        )

    property_details = get_property_for_lead(db, lead)
    if not property_details:
        property_details = _get_property_by_id(db, lead.property_id)

    if not property_details:
        raise HTTPException(
            status_code=400,
            detail="Lead is not associated with a property record.",
        )

    try:
        pdf_bytes, filename = render_letter_pdf(templates.env, lead, contact, property_details)
    except LetterGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)

# ---------- ATTEMPTS / ACTIONS FOR A LEAD ----------

@app.get("/leads/{lead_id}/attempts", response_class=HTMLResponse)
def lead_attempts(
    request: Request,
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return RedirectResponse(
        url=f"/leads/{lead.id}/edit#attempts",
        status_code=302,
    )


@app.post("/leads/{lead_id}/attempts/create")
def create_lead_attempt(
    lead_id: int,
    channel: ContactChannel = Form(...),
    attempt_number: int = Form(1),
    contact_id: str | None = Form(None),
    outcome: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Normalize contact_id from empty string
    if not contact_id:
        contact_id_val = None
    else:
        contact_id_val = int(contact_id)

    attempt = LeadAttempt(
        lead_id=lead.id,
        contact_id=contact_id_val,
        channel=channel,
        attempt_number=attempt_number,
        outcome=outcome,
        notes=notes,
    )
    db.add(attempt)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#attempts", status_code=303)


# ---------- COMMENTS FOR A LEAD ----------


@app.post("/leads/{lead_id}/comments/create")
def create_lead_comment(
    lead_id: int,
    body: str = Form(...),
    author: str | None = Form(None),
    db: Session = Depends(get_db),
):
    lead = db.get(BusinessLead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    comment = LeadComment(
        lead_id=lead.id,
        body=body,
        author=author,
    )
    db.add(comment)
    db.commit()

    return RedirectResponse(url=f"/leads/{lead.id}/edit#comments", status_code=303)


@app.post("/leads/{lead_id}/comments/{comment_id}/delete")
def delete_lead_comment(
    lead_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
):
    comment = db.get(LeadComment, comment_id)
    if not comment or comment.lead_id != lead_id:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.delete(comment)
    db.commit()
    return RedirectResponse(url=f"/leads/{lead_id}/edit#comments", status_code=303)

