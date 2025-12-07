"""
Email scheduler using APScheduler to send scheduled emails.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from db import SessionLocal
from models import ScheduledEmail, ScheduledEmailStatus, LeadAttempt, ContactChannel
from email_service import send_email, resolve_profile, extract_profile_marker
from utils import get_next_attempt_number

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=timezone.utc)


def _process_scheduled_emails():
    """Check for due scheduled emails and send them."""
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        
        # Find all pending emails that are due
        due_emails = db.query(ScheduledEmail).filter(
            ScheduledEmail.status == ScheduledEmailStatus.pending,
            ScheduledEmail.scheduled_at <= now,
        ).all()
        
        for scheduled_email in due_emails:
            try:
                # Extract profile info and clean body
                profile_key, clean_body = extract_profile_marker(scheduled_email.body)
                profile_config = resolve_profile(profile_key)
                
                # Send the email with profile-specific SMTP credentials
                send_email(
                    to_email=scheduled_email.to_email,
                    subject=scheduled_email.subject,
                    html_body=clean_body,
                    from_email=profile_config["from_email"],
                    from_name=profile_config["from_name"],
                    reply_to=profile_config["reply_to"],
                    smtp_username=profile_config["from_email"],  # Use profile email as SMTP username
                    smtp_password=profile_config.get("smtp_password") or None,  # Use profile password
                )
                
                # Mark as sent
                scheduled_email.status = ScheduledEmailStatus.sent
                scheduled_email.sent_at = datetime.now(timezone.utc)
                db.commit()
                
                # Create attempt record
                next_attempt_number = get_next_attempt_number(db, scheduled_email.lead_id)
                
                attempt = LeadAttempt(
                    lead_id=scheduled_email.lead_id,
                    contact_id=scheduled_email.contact_id,
                    channel=ContactChannel.email,
                    attempt_number=next_attempt_number,
                    outcome="Email sent (scheduled)",
                    notes=f"Scheduled for {scheduled_email.scheduled_at.isoformat()}. Subject: {scheduled_email.subject[:100]}",
                )
                db.add(attempt)
                db.commit()
                
                logger.info(f"Sent scheduled email {scheduled_email.id} to {scheduled_email.to_email}")
                
            except Exception as e:
                # Mark as failed
                scheduled_email.status = ScheduledEmailStatus.failed
                scheduled_email.error_message = str(e)[:500]  # Limit error message length
                db.commit()
                logger.error(f"Failed to send scheduled email {scheduled_email.id}: {e}")
                
    except Exception as e:
        logger.error(f"Error processing scheduled emails: {e}")
        db.rollback()
    finally:
        db.close()


def _check_missed_emails():
    """Check for emails that were scheduled but missed (app was down)."""
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        
        # Find pending emails that should have been sent more than 1 minute ago
        missed_emails = db.query(ScheduledEmail).filter(
            ScheduledEmail.status == ScheduledEmailStatus.pending,
            ScheduledEmail.scheduled_at < (now - timedelta(minutes=1)),
        ).all()
        
        for email in missed_emails:
            email.status = ScheduledEmailStatus.missed
            db.commit()
            logger.info(f"Marked scheduled email {email.id} as missed")
            
    except Exception as e:
        logger.error(f"Error checking missed emails: {e}")
        db.rollback()
    finally:
        db.close()


def start_scheduler():
    """Start the email scheduler."""
    if scheduler.running:
        return
    
    # Check for missed emails on startup
    _check_missed_emails()
    
    # Schedule job to run every minute
    scheduler.add_job(
        _process_scheduled_emails,
        trigger=CronTrigger(second=0),  # Run at the start of every minute
        id="process_scheduled_emails",
        name="Process scheduled emails",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info("Email scheduler started")


def stop_scheduler():
    """Stop the email scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Email scheduler stopped")

