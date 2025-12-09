"""
Email scheduler using APScheduler to send scheduled emails.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Callable
from dataclasses import dataclass

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from db import SessionLocal
from models import (
    ScheduledEmail, ScheduledEmailStatus, LeadAttempt, ContactChannel,
    LeadJourney, JourneyMilestone, MilestoneStatus, JourneyMilestoneType
)
from email_service import send_email, resolve_profile, extract_profile_marker
from utils import get_next_attempt_number
from datetime import timedelta

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=timezone.utc)


@dataclass
class MilestoneMatchingRule:
    """Configuration for matching attempts to milestones."""
    milestone_type: JourneyMilestoneType
    channel: ContactChannel
    outcome_patterns: List[str]  # Patterns to match in outcome text (case-insensitive substring match)
    sequence_matcher: Optional[Callable[[List[LeadAttempt], LeadAttempt], bool]] = None  # Function to check sequence position
    
    def matches_outcome(self, outcome: str) -> bool:
        """Check if outcome text matches patterns."""
        if not outcome:
            return False
        outcome_lower = outcome.lower()
        
        # For email followups, require "follow" AND one of the number patterns
        if self.milestone_type in (JourneyMilestoneType.email_followup_1, 
                                   JourneyMilestoneType.email_followup_2, 
                                   JourneyMilestoneType.email_followup_3):
            has_follow = "follow" in outcome_lower
            number_patterns = [p for p in self.outcome_patterns if p.lower() != "follow"]
            has_number = any(pattern.lower() in outcome_lower for pattern in number_patterns)
            return has_follow and has_number
        else:
            # Any pattern matches
            return any(pattern.lower() in outcome_lower for pattern in self.outcome_patterns)


# Define matching rules for email milestones (only emails are handled by scheduler)
EMAIL_MILESTONE_RULES: dict[JourneyMilestoneType, MilestoneMatchingRule] = {
    JourneyMilestoneType.email_1: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.email_1,
        channel=ContactChannel.email,
        outcome_patterns=["initial", "email #1", "email 1"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) > 0 and attempts[0].id == attempt.id
        ),
    ),
    JourneyMilestoneType.email_followup_1: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.email_followup_1,
        channel=ContactChannel.email,
        outcome_patterns=["follow", "1", "one", "first"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) == 2 and attempts[1].id == attempt.id
        ),
    ),
    JourneyMilestoneType.email_followup_2: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.email_followup_2,
        channel=ContactChannel.email,
        outcome_patterns=["follow", "2", "two", "second"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) == 3 and attempts[2].id == attempt.id
        ),
    ),
    JourneyMilestoneType.email_followup_3: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.email_followup_3,
        channel=ContactChannel.email,
        outcome_patterns=["follow", "3", "three", "third", "final", "nudge"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) == 4 and attempts[3].id == attempt.id
        ),
    ),
}


def _check_prerequisite_milestones_scheduler(db: Session, journey_id: int, milestone_type: JourneyMilestoneType) -> bool:
    """Check if prerequisite milestones are completed before allowing a match.
    Duplicate of function in main.py to avoid circular imports."""
    from models import JourneyMilestone, MilestoneStatus, JourneyMilestoneType
    
    # Define prerequisite chain for email milestones
    email_prerequisites = {
        JourneyMilestoneType.email_followup_1: [JourneyMilestoneType.email_1],
        JourneyMilestoneType.email_followup_2: [JourneyMilestoneType.email_1, JourneyMilestoneType.email_followup_1],
        JourneyMilestoneType.email_followup_3: [JourneyMilestoneType.email_1, JourneyMilestoneType.email_followup_1, JourneyMilestoneType.email_followup_2],
    }
    
    # Define prerequisite chain for mail milestones
    mail_prerequisites = {
        JourneyMilestoneType.mail_2: [JourneyMilestoneType.mail_1],
        JourneyMilestoneType.mail_3: [JourneyMilestoneType.mail_1, JourneyMilestoneType.mail_2],
    }
    
    # Check if this milestone has prerequisites
    prerequisites = email_prerequisites.get(milestone_type) or mail_prerequisites.get(milestone_type)
    if not prerequisites:
        return True  # No prerequisites, always allow
    
    # Check if all prerequisites are completed
    for prereq_type in prerequisites:
        prereq = db.query(JourneyMilestone).filter(
            JourneyMilestone.journey_id == journey_id,
            JourneyMilestone.milestone_type == prereq_type,
            JourneyMilestone.status == MilestoneStatus.completed
        ).first()
        if not prereq:
            return False  # Prerequisite not completed
    
    return True  # All prerequisites completed


def _link_attempt_to_milestone_scheduler(db: Session, attempt: LeadAttempt):
    """Link a newly created attempt to a matching journey milestone and mark it as completed.
    This is a duplicate of the function in main.py to avoid circular imports.
    Only attempts for the primary contact count toward milestones."""
    from models import LeadJourney, JourneyMilestone, MilestoneStatus, JourneyMilestoneType, ContactChannel
    from datetime import timezone, datetime
    
    lead_id = attempt.lead_id
    
    # Check if lead has a journey
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return
    
    # Only count attempts for the primary contact
    if journey.primary_contact_id:
        if attempt.contact_id is None or attempt.contact_id != journey.primary_contact_id:
            return
    elif attempt.contact_id is not None:
        return
    
    # Get the NEXT milestone in sequence (first incomplete one for this channel)
    milestone = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id,
        JourneyMilestone.channel == attempt.channel,
        JourneyMilestone.status.in_([MilestoneStatus.pending, MilestoneStatus.overdue]),
        JourneyMilestone.attempt_id.is_(None)  # Not already linked
    ).order_by(JourneyMilestone.scheduled_day.asc()).first()
    
    if not milestone:
        return
    
    journey_start = journey.started_at
    # Ensure attempt_date is timezone-aware
    if attempt.created_at:
        attempt_date = attempt.created_at
        if attempt_date.tzinfo is None:
            attempt_date = attempt_date.replace(tzinfo=timezone.utc)
    else:
        attempt_date = datetime.now(timezone.utc)
    
    # Get matching rule for this milestone type
    rule = EMAIL_MILESTONE_RULES.get(milestone.milestone_type)
    if not rule:
        return  # Not an email milestone or no rule found
    
    # Check if prerequisite milestones are completed (must complete in order)
    if not _check_prerequisite_milestones_scheduler(db, journey.id, milestone.milestone_type):
        return
    
    # Try to match using outcome text
    matched = rule.matches_outcome(attempt.outcome or "")
    is_sequence_match = False
    
    # Try sequence-based matching if rule has a sequence matcher and outcome didn't match
    if not matched and rule.sequence_matcher and journey.primary_contact_id:
        # Get all attempts for this channel and primary contact
        attempts_query = db.query(LeadAttempt).filter(
            LeadAttempt.lead_id == lead_id,
            LeadAttempt.channel == attempt.channel,
            LeadAttempt.contact_id == journey.primary_contact_id
        )
        attempts = attempts_query.order_by(LeadAttempt.created_at.asc()).all()
        
        if rule.sequence_matcher(attempts, attempt):
            matched = True
            is_sequence_match = True
    
    if matched:
        # For sequence-based matches, only require that attempt is after journey start
        if is_sequence_match:
            if attempt_date < journey_start:
                return
        milestone.status = MilestoneStatus.completed
        milestone.completed_at = attempt_date
        milestone.attempt_id = attempt.id
        milestone.updated_at = datetime.now(timezone.utc)
        db.flush()


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
                db.flush()  # Flush to get attempt.id
                
                # Link attempt to milestone if applicable
                _link_attempt_to_milestone_scheduler(db, attempt)
                
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

