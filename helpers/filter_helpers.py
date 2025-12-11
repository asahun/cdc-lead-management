"""
Filter and navigation helpers for leads and properties.
"""

from urllib.parse import urlencode
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, and_

from models import (
    BusinessLead,
    LeadAttempt,
    LeadStatus,
    ContactChannel,
    PrintLog,
    ScheduledEmail,
    ScheduledEmailStatus,
)


def build_count_filter(operator: str | None, count: int | None, subquery) -> Optional:
    """Build a count filter condition from operator, count, and subquery."""
    if not operator or count is None:
        return None
    
    if operator == ">=":
        return subquery >= count
    elif operator == "=":
        return subquery == count
    elif operator == "<=":
        return subquery <= count
    return None


def build_lead_filters(
    q: str | None,
    attempt_type: str | None,
    attempt_operator: str | None,
    attempt_count_int: int | None,
    print_log_operator: str | None,
    print_log_count_int: int | None,
    print_log_mailed: str | None,
    scheduled_email_operator: str | None,
    scheduled_email_count_int: int | None,
    failed_email_operator: str | None,
    failed_email_count_int: int | None,
    status: str | None,
):
    """Build filter conditions for leads query. Returns list of filter conditions."""
    filters = []
    
    # Text search filter
    if q:
        pattern = f"%{q}%"
        filters.append(
            or_(
                BusinessLead.property_id.ilike(pattern),
                BusinessLead.owner_name.ilike(pattern)
            )
        )
    
    # Attempt count filter
    if attempt_type and attempt_operator and attempt_count_int is not None:
        attempt_filter = []
        if attempt_type != "all":
            try:
                attempt_filter.append(LeadAttempt.channel == ContactChannel[attempt_type])
            except (KeyError, ValueError):
                # Invalid attempt type, skip this filter
                pass
        
        # Build subquery only if we have valid attempt_type or it's "all"
        if attempt_filter or attempt_type == "all":
            # Build base subquery
            attempt_count_subq_base = (
                select(func.coalesce(func.count(LeadAttempt.id), 0))
                .where(LeadAttempt.lead_id == BusinessLead.id)
                .correlate(BusinessLead)
            )
            # Add channel filter only if attempt_type is not "all"
            if attempt_filter:
                attempt_count_subq_base = attempt_count_subq_base.where(*attempt_filter)
            
            attempt_count_subq = attempt_count_subq_base.scalar_subquery()
            filter_condition = build_count_filter(attempt_operator, attempt_count_int, attempt_count_subq)
            if filter_condition is not None:
                filters.append(filter_condition)

    # Print log count filter
    if print_log_operator and print_log_count_int is not None:
        print_log_filter = []
        if print_log_mailed == "mailed":
            print_log_filter.append(PrintLog.mailed == True)
        elif print_log_mailed == "not_mailed":
            print_log_filter.append(PrintLog.mailed == False)
        # Note: if print_log_mailed is "all" or empty, no additional filter is applied
        print_log_count_subq = (
            select(func.coalesce(func.count(PrintLog.id), 0))
            .where(PrintLog.lead_id == BusinessLead.id)
            .where(*print_log_filter)
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        filter_condition = build_count_filter(print_log_operator, print_log_count_int, print_log_count_subq)
        if filter_condition is not None:
            filters.append(filter_condition)

    # Scheduled email count filter (pending + sent)
    if scheduled_email_operator and scheduled_email_count_int is not None:
        scheduled_email_count_subq = (
            select(func.coalesce(func.count(ScheduledEmail.id), 0))
            .where(ScheduledEmail.lead_id == BusinessLead.id)
            .where(ScheduledEmail.status.in_([ScheduledEmailStatus.pending, ScheduledEmailStatus.sent]))
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        filter_condition = build_count_filter(scheduled_email_operator, scheduled_email_count_int, scheduled_email_count_subq)
        if filter_condition is not None:
            filters.append(filter_condition)

    # Failed email count filter
    if failed_email_operator and failed_email_count_int is not None:
        failed_email_count_subq = (
            select(func.coalesce(func.count(ScheduledEmail.id), 0))
            .where(ScheduledEmail.lead_id == BusinessLead.id)
            .where(ScheduledEmail.status == ScheduledEmailStatus.failed)
            .correlate(BusinessLead)
            .scalar_subquery()
        )
        filter_condition = build_count_filter(failed_email_operator, failed_email_count_int, failed_email_count_subq)
        if filter_condition is not None:
            filters.append(filter_condition)

    # Status filter
    if status and status.strip():
        try:
            status_enum = LeadStatus[status]
            filters.append(BusinessLead.status == status_enum)
        except (KeyError, ValueError):
            pass  # Invalid status, ignore
    
    return filters


def build_filter_query_string(
    q: str | None,
    attempt_type: str | None,
    attempt_operator: str | None,
    attempt_count: str | None,
    print_log_operator: str | None,
    print_log_count: str | None,
    print_log_mailed: str | None,
    scheduled_email_operator: str | None,
    scheduled_email_count: str | None,
    failed_email_operator: str | None,
    failed_email_count: str | None,
    status: str | None,
) -> str:
    """Build query string from filter parameters."""
    params = {}
    if q:
        params["q"] = q
    if attempt_type and attempt_type != "all":
        params["attempt_type"] = attempt_type
    if attempt_operator:
        params["attempt_operator"] = attempt_operator
    if attempt_count:
        params["attempt_count"] = attempt_count
    if print_log_operator:
        params["print_log_operator"] = print_log_operator
    if print_log_count:
        params["print_log_count"] = print_log_count
    if print_log_mailed and print_log_mailed != "all":
        params["print_log_mailed"] = print_log_mailed
    if scheduled_email_operator:
        params["scheduled_email_operator"] = scheduled_email_operator
    if scheduled_email_count:
        params["scheduled_email_count"] = scheduled_email_count
    if failed_email_operator:
        params["failed_email_operator"] = failed_email_operator
    if failed_email_count:
        params["failed_email_count"] = failed_email_count
    if status:
        params["status"] = status
    if params:
        return "?" + urlencode(params)
    return ""


def lead_navigation_info(
    db: Session,
    lead_id: int,
    q: str | None = None,
    attempt_type: str | None = None,
    attempt_operator: str | None = None,
    attempt_count_int: int | None = None,
    print_log_operator: str | None = None,
    print_log_count_int: int | None = None,
    print_log_mailed: str | None = None,
    scheduled_email_operator: str | None = None,
    scheduled_email_count_int: int | None = None,
    failed_email_operator: str | None = None,
    failed_email_count_int: int | None = None,
    status: str | None = None,
):
    """Get navigation info for a lead (prev/next based on filtered ordering)."""
    # Build filters using the same logic as list_leads
    filters = build_lead_filters(
        q, attempt_type, attempt_operator, attempt_count_int,
        print_log_operator, print_log_count_int, print_log_mailed,
        scheduled_email_operator, scheduled_email_count_int,
        failed_email_operator, failed_email_count_int, status
    )
    
    # Use the same ordering as the leads list
    lead_ordering = BusinessLead.created_at.desc()
    
    # Create ranked subquery with prev/next, applying filters
    ranked_query = select(
        BusinessLead.id.label("lead_id"),
        func.row_number().over(order_by=lead_ordering).label("order_id"),
        func.lag(BusinessLead.id).over(order_by=lead_ordering).label("prev_lead_id"),
        func.lead(BusinessLead.id).over(order_by=lead_ordering).label("next_lead_id"),
    )
    
    if filters:
        ranked_query = ranked_query.where(and_(*filters))
    
    ranked = ranked_query.subquery()
    
    nav_row = db.execute(
        select(
            ranked.c.order_id,
            ranked.c.prev_lead_id,
            ranked.c.next_lead_id,
        ).where(ranked.c.lead_id == lead_id)
    ).one_or_none()
    
    if not nav_row:
        return {
            "order_id": None,
            "prev_lead_id": None,
            "next_lead_id": None,
        }
    
    return {
        "order_id": nav_row.order_id,
        "prev_lead_id": nav_row.prev_lead_id,
        "next_lead_id": nav_row.next_lead_id,
    }

