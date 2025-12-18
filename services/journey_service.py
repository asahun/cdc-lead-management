"""
Journey tracking service - handles all journey and milestone business logic.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from models import (
    LeadJourney,
    JourneyMilestone,
    JourneyStatus,
    JourneyMilestoneType,
    MilestoneStatus,
    ContactChannel,
    LeadAttempt,
    LeadContact,
)

logger = logging.getLogger(__name__)


def initialize_lead_journey(db: Session, lead_id: int, primary_contact_id: int | None = None) -> LeadJourney | None:
    """Initialize a journey for a lead when a primary contact is set.
    
    Args:
        db: Database session
        lead_id: Lead ID
        primary_contact_id: Primary contact ID (if None, will find existing primary contact)
    
    Returns:
        LeadJourney if primary contact exists, None otherwise
    """
    # Find primary contact if not provided
    if primary_contact_id is None:
        primary_contact = db.query(LeadContact).filter(
            LeadContact.lead_id == lead_id,
            LeadContact.is_primary == True
        ).first()
        if not primary_contact:
            return None
        primary_contact_id = primary_contact.id
    else:
        # Verify the contact exists and belongs to this lead
        primary_contact = db.query(LeadContact).filter(
            LeadContact.id == primary_contact_id,
            LeadContact.lead_id == lead_id
        ).first()
        if not primary_contact:
            return None
    
    # Check if journey already exists
    existing_journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    
    # Determine journey start date (day 0)
    if existing_journey:
        # Switching primary contact - always reset day 0 to now (fresh start for new contact)
        journey_start_date = datetime.now(timezone.utc)
    else:
        # First time creating journey - use first attempt date if exists, otherwise now
        first_attempt_query = db.query(LeadAttempt).filter(
            LeadAttempt.lead_id == lead_id
        )
        if primary_contact_id:
            first_attempt_query = first_attempt_query.filter(LeadAttempt.contact_id == primary_contact_id)
        first_attempt = first_attempt_query.order_by(LeadAttempt.created_at.asc()).first()
        
        if first_attempt and first_attempt.created_at:
            started_at = first_attempt.created_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            # Only use first attempt date if it's in the past (within reason, not too far back)
            if started_at < now and (now - started_at).days <= 90:  # Allow up to 90 days back
                journey_start_date = started_at
            else:
                journey_start_date = now
        else:
            journey_start_date = datetime.now(timezone.utc)
    
    if existing_journey:
        # Update existing journey with new primary contact
        # Delete old milestones to start fresh
        db.query(JourneyMilestone).filter(
            JourneyMilestone.journey_id == existing_journey.id
        ).delete()
        
        # Update the journey with new primary contact and set start date
        existing_journey.primary_contact_id = primary_contact_id
        existing_journey.started_at = journey_start_date
        existing_journey.status = JourneyStatus.active
        existing_journey.updated_at = datetime.now(timezone.utc)
        db.flush()
        
        # Use existing journey for milestone creation
        journey = existing_journey
    else:
        # Create new journey
        journey = LeadJourney(
            lead_id=lead_id,
            primary_contact_id=primary_contact_id,
            started_at=journey_start_date,
            status=JourneyStatus.active
        )
        db.add(journey)
        db.flush()
    
    # Define all milestones
    milestones_config = [
        # Email milestones
        (JourneyMilestoneType.email_1, ContactChannel.email, 0, None, None),
        (JourneyMilestoneType.email_followup_1, ContactChannel.email, 4, None, None),
        (JourneyMilestoneType.email_followup_2, ContactChannel.email, 10, None, None),
        # LinkedIn milestones
        (JourneyMilestoneType.linkedin_connection, ContactChannel.linkedin, 0, None, None),
        (JourneyMilestoneType.linkedin_message_1, ContactChannel.linkedin, 3, JourneyMilestoneType.linkedin_connection, "if_connected"),
        (JourneyMilestoneType.linkedin_message_2, ContactChannel.linkedin, 7, JourneyMilestoneType.linkedin_connection, "if_connected"),
        (JourneyMilestoneType.linkedin_message_3, ContactChannel.linkedin, 14, JourneyMilestoneType.linkedin_connection, "if_connected"),
        (JourneyMilestoneType.linkedin_inmail, ContactChannel.linkedin, 18, JourneyMilestoneType.linkedin_connection, "if_not_connected"),
        # Mail milestones
        (JourneyMilestoneType.mail_1, ContactChannel.mail, 1, None, None),
        (JourneyMilestoneType.mail_2, ContactChannel.mail, 28, None, None),
        (JourneyMilestoneType.mail_3, ContactChannel.mail, 42, None, None),
    ]
    
    # Create all milestones first
    milestone_objects = {}
    milestones_to_create = []
    
    for milestone_type, channel, scheduled_day, parent_type, branch_condition in milestones_config:
        milestone = JourneyMilestone(
            journey_id=journey.id,
            lead_id=lead_id,
            milestone_type=milestone_type,
            channel=channel,
            scheduled_day=scheduled_day,
            status=MilestoneStatus.pending,
            parent_milestone_id=None,  # Will be set after all are created
            branch_condition=branch_condition
        )
        db.add(milestone)
        db.flush()
        milestone_objects[milestone_type] = milestone
        milestones_to_create.append((milestone, parent_type))
    
    # Now update parent references
    for milestone, parent_type in milestones_to_create:
        if parent_type:
            parent = milestone_objects.get(parent_type)
            if parent:
                milestone.parent_milestone_id = parent.id
                db.flush()
    
    # After creating milestones, try to match existing attempts BEFORE committing
    # This ensures we're working with the same session
    backfill_journey_milestones(db, lead_id)
    
    db.commit()
    db.refresh(journey)
    
    return journey


def backfill_journey_milestones(db: Session, lead_id: int):
    """Match existing attempts to milestones for a lead."""
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return
    
    # Clean up any invalid milestones before querying
    cleanup_invalid_milestones(db, journey.id)
    
    # Get all milestones for this journey that can be matched (pending or overdue, not already linked)
    milestones = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id,
        JourneyMilestone.status.in_([MilestoneStatus.pending, MilestoneStatus.overdue]),
        JourneyMilestone.attempt_id.is_(None)  # Not already linked
    ).all()
    
    # Get all attempts for primary contact, ordered by creation date
    attempts_query = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id
    )
    if journey.primary_contact_id:
        # Only get attempts that match the primary contact
        # Exclude attempts with None contact_id
        attempts_query = attempts_query.filter(
            LeadAttempt.contact_id == journey.primary_contact_id
        )
    else:
        # If no primary contact is set, can't backfill
        return
    
    attempts = attempts_query.order_by(LeadAttempt.created_at.asc()).all()
    
    # Get journey start date
    journey_start = journey.started_at
    
    # Group attempts by channel for sequence-based matching
    attempts_by_channel = {}
    for attempt in attempts:
        channel = attempt.channel
        if channel not in attempts_by_channel:
            attempts_by_channel[channel] = []
        attempts_by_channel[channel].append(attempt)
    
    # Match attempts to milestones using sequence position
    for channel, channel_attempts in attempts_by_channel.items():
        # Sort attempts chronologically
        channel_attempts.sort(key=lambda a: a.created_at or datetime.min)
        
        # For LinkedIn, separate connection attempts from message attempts
        if channel == ContactChannel.linkedin:
            # Filter connection attempts (for connection milestone)
            connection_attempts = [
                a for a in channel_attempts
                if "connection" in (a.outcome or "").lower()
            ]
            # Filter message attempts (for message milestones)
            message_attempts = [
                a for a in channel_attempts
                if "connection" not in (a.outcome or "").lower()
            ]
            
            # Match connection attempt (position 1 from all attempts)
            if connection_attempts:
                connection_attempt = connection_attempts[0]
                milestone = next(
                    (m for m in milestones 
                     if m.channel == channel 
                     and m.milestone_type == JourneyMilestoneType.linkedin_connection
                     and m.attempt_id is None
                     and m.status != MilestoneStatus.completed),
                    None
                )
                if milestone:
                    attempt_created_at = connection_attempt.created_at
                    if attempt_created_at and attempt_created_at.tzinfo is None:
                        attempt_created_at = attempt_created_at.replace(tzinfo=timezone.utc)
                    elif not attempt_created_at:
                        attempt_created_at = datetime.now(timezone.utc)
                    if attempt_created_at >= journey_start:
                        milestone.status = MilestoneStatus.completed
                        milestone.completed_at = attempt_created_at
                        milestone.attempt_id = connection_attempt.id
                        milestone.updated_at = datetime.now(timezone.utc)
                        db.flush()
            
            # Match message attempts (position from filtered list)
            message_position_to_milestone = {
                1: JourneyMilestoneType.linkedin_message_1,
                2: JourneyMilestoneType.linkedin_message_2,
                3: JourneyMilestoneType.linkedin_message_3,
            }
            for position, attempt in enumerate(message_attempts, 1):
                expected_milestone_type = message_position_to_milestone.get(position)
                if not expected_milestone_type:
                    continue
                milestone = next(
                    (m for m in milestones 
                     if m.channel == channel 
                     and m.milestone_type == expected_milestone_type
                     and m.attempt_id is None
                     and m.status != MilestoneStatus.completed),
                    None
                )
                if milestone:
                    attempt_created_at = attempt.created_at
                    if attempt_created_at and attempt_created_at.tzinfo is None:
                        attempt_created_at = attempt_created_at.replace(tzinfo=timezone.utc)
                    elif not attempt_created_at:
                        attempt_created_at = datetime.now(timezone.utc)
                    if attempt_created_at >= journey_start:
                        milestone.status = MilestoneStatus.completed
                        milestone.completed_at = attempt_created_at
                        milestone.attempt_id = attempt.id
                        milestone.updated_at = datetime.now(timezone.utc)
                        db.flush()
        else:
            # For email and mail, use simple position mapping
            position_to_milestone = {}
            if channel == ContactChannel.email:
                position_to_milestone = {
                    1: JourneyMilestoneType.email_1,
                    2: JourneyMilestoneType.email_followup_1,
                    3: JourneyMilestoneType.email_followup_2,
                }
            elif channel == ContactChannel.mail:
                position_to_milestone = {
                    1: JourneyMilestoneType.mail_1,
                    2: JourneyMilestoneType.mail_2,
                    3: JourneyMilestoneType.mail_3,
                }
            
            # Match each attempt by position
            for position, attempt in enumerate(channel_attempts, 1):
                expected_milestone_type = position_to_milestone.get(position)
                if not expected_milestone_type:
                    continue  # No milestone for this position
                
                # Find the matching milestone
                milestone = next(
                    (m for m in milestones 
                     if m.channel == channel 
                     and m.milestone_type == expected_milestone_type
                     and m.attempt_id is None
                     and m.status != MilestoneStatus.completed),
                    None
                )
                
                if milestone:
                    # Ensure attempt.created_at is timezone-aware
                    attempt_created_at = attempt.created_at
                    if attempt_created_at and attempt_created_at.tzinfo is None:
                        attempt_created_at = attempt_created_at.replace(tzinfo=timezone.utc)
                    elif not attempt_created_at:
                        attempt_created_at = datetime.now(timezone.utc)
                    
                    # Ensure attempt is after journey start
                    if attempt_created_at >= journey_start:
                        milestone.status = MilestoneStatus.completed
                        milestone.completed_at = attempt_created_at
                        milestone.attempt_id = attempt.id
                        milestone.updated_at = datetime.now(timezone.utc)
                        db.flush()
    
    # Update milestone statuses based on current date and LinkedIn connection status
    update_milestone_statuses(db, lead_id)
    
    # Note: Don't commit here - let the caller handle the commit
    # This allows backfill to be called before the main transaction commits


@dataclass
class MilestoneMatchingRule:
    """Configuration for matching attempts to milestones."""
    milestone_type: JourneyMilestoneType
    channel: ContactChannel
    outcome_patterns: List[str]  # Patterns to match in outcome text (case-insensitive substring match)
    sequence_matcher: Optional[Callable[[List[LeadAttempt], LeadAttempt], bool]] = None  # Function to check sequence position
    require_all_patterns: bool = False  # If True, all patterns must match; if False, any pattern matches
    
    def matches_outcome(self, outcome: str) -> bool:
        """Check if outcome text matches patterns."""
        if not outcome:
            return False
        outcome_lower = outcome.lower()
        
        if self.require_all_patterns:
            # All patterns must be present
            return all(pattern.lower() in outcome_lower for pattern in self.outcome_patterns)
        else:
            # For email followups, require "follow" AND one of the number patterns
            if self.milestone_type in (JourneyMilestoneType.email_followup_1, 
                                       JourneyMilestoneType.email_followup_2):
                has_follow = "follow" in outcome_lower
                number_patterns = [p for p in self.outcome_patterns if p.lower() != "follow"]
                has_number = any(pattern.lower() in outcome_lower for pattern in number_patterns)
                return has_follow and has_number
            # For mail, require "mail" AND one of the number patterns (or "letter mailed")
            elif self.milestone_type in (JourneyMilestoneType.mail_1,
                                         JourneyMilestoneType.mail_2,
                                         JourneyMilestoneType.mail_3):
                has_mail = "mail" in outcome_lower or "letter mailed" in outcome_lower
                number_patterns = [p for p in self.outcome_patterns if p.lower() not in ("mail", "letter mailed")]
                has_number = any(pattern.lower() in outcome_lower for pattern in number_patterns) if number_patterns else True
                return has_mail and (has_number or "letter mailed" in outcome_lower)
            else:
                # Any pattern matches
                return any(pattern.lower() in outcome_lower for pattern in self.outcome_patterns)


def is_nth_message_attempt(attempts: List[LeadAttempt], attempt: LeadAttempt, message_number: int) -> bool:
    """
    Check if attempt is the nth message attempt (excluding connection-related attempts).
    For LinkedIn, messages come after connection, so we count only message attempts.
    """
    # Filter out connection-related attempts
    message_attempts = [
        a for a in attempts
        if "connection" not in (a.outcome or "").lower()
    ]
    
    # Message 1 should be the 1st message attempt, Message 2 the 2nd, etc.
    return (
        len(message_attempts) == message_number and
        message_attempts[message_number - 1].id == attempt.id
    )


# ========== PATH-SPECIFIC SEQUENCE POSITION FUNCTIONS ==========

def get_all_linkedin_attempts_position(db: Session, lead_id: int, contact_id: int, attempt: LeadAttempt) -> int | None:
    """
    Get position of attempt in ALL LinkedIn attempts (no filtering).
    Used for connection milestone matching.
    """
    all_attempts = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id,
        LeadAttempt.contact_id == contact_id,
        LeadAttempt.channel == ContactChannel.linkedin
    ).order_by(LeadAttempt.created_at.asc()).all()
    
    for i, a in enumerate(all_attempts, 1):
        if a.id == attempt.id:
            return i
    return None


def get_connection_message_sequence_position(db: Session, lead_id: int, contact_id: int, attempt: LeadAttempt) -> int | None:
    """
    Get sequence position for connection→messages path ONLY.
    Filters out: connection attempts, InMail attempts.
    Returns: 1, 2, or 3 for Message 1, 2, 3.
    """
    all_attempts = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id,
        LeadAttempt.contact_id == contact_id,
        LeadAttempt.channel == ContactChannel.linkedin
    ).order_by(LeadAttempt.created_at.asc()).all()
    
    # Filter to ONLY message attempts (exclude connection and InMail)
    message_attempts = [
        a for a in all_attempts
        if "connection" not in (a.outcome or "").lower()
        and "inmail" not in (a.outcome or "").lower()
    ]
    
    for i, a in enumerate(message_attempts, 1):
        if a.id == attempt.id:
            return i
    return None


def get_email_sequence_position(db: Session, lead_id: int, contact_id: int, attempt: LeadAttempt) -> int | None:
    """
    Get sequence position for email path.
    Returns: 1, 2, or 3 for email_1, email_followup_1, email_followup_2.
    """
    all_attempts = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id,
        LeadAttempt.contact_id == contact_id,
        LeadAttempt.channel == ContactChannel.email
    ).order_by(LeadAttempt.created_at.asc()).all()
    
    for i, a in enumerate(all_attempts, 1):
        if a.id == attempt.id:
            return i
    return None


def get_mail_sequence_position(db: Session, lead_id: int, contact_id: int, attempt: LeadAttempt) -> int | None:
    """
    Get sequence position for mail path.
    Returns: 1, 2, or 3 for mail_1, mail_2, mail_3.
    """
    all_attempts = db.query(LeadAttempt).filter(
        LeadAttempt.lead_id == lead_id,
        LeadAttempt.contact_id == contact_id,
        LeadAttempt.channel == ContactChannel.mail
    ).order_by(LeadAttempt.created_at.asc()).all()
    
    for i, a in enumerate(all_attempts, 1):
        if a.id == attempt.id:
            return i
    return None


# Define matching rules for all milestones (not used in current implementation but kept for reference)
MILESTONE_MATCHING_RULES: dict[JourneyMilestoneType, MilestoneMatchingRule] = {
    # Email milestones
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
        require_all_patterns=False,  # "follow" AND ("1" OR "one" OR "first")
        sequence_matcher=None,  # Will be handled specially in link_attempt_to_milestone
    ),
    JourneyMilestoneType.email_followup_2: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.email_followup_2,
        channel=ContactChannel.email,
        outcome_patterns=["follow", "2", "two", "second", "final", "nudge"],
        require_all_patterns=False,
        sequence_matcher=None,  # Will be handled specially in link_attempt_to_milestone
    ),
    
    # LinkedIn milestones
    JourneyMilestoneType.linkedin_connection: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.linkedin_connection,
        channel=ContactChannel.linkedin,
        outcome_patterns=["connection request", "connection sent", "connection accepted", "connection"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) > 0 and attempts[0].id == attempt.id
        ),
    ),
    JourneyMilestoneType.linkedin_message_1: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.linkedin_message_1,
        channel=ContactChannel.linkedin,
        outcome_patterns=["message 1", "follow-up 1", "message #1", "first message", "linkedin message 1"],
        sequence_matcher=lambda attempts, attempt: is_nth_message_attempt(attempts, attempt, 1),
    ),
    JourneyMilestoneType.linkedin_message_2: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.linkedin_message_2,
        channel=ContactChannel.linkedin,
        outcome_patterns=["message 2", "follow-up 2", "message #2", "second message", "linkedin message 2"],
        sequence_matcher=lambda attempts, attempt: is_nth_message_attempt(attempts, attempt, 2),
    ),
    JourneyMilestoneType.linkedin_message_3: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.linkedin_message_3,
        channel=ContactChannel.linkedin,
        outcome_patterns=["message 3", "follow-up 3", "message #3", "third message", "linkedin message 3"],
        sequence_matcher=lambda attempts, attempt: is_nth_message_attempt(attempts, attempt, 3),
    ),
    JourneyMilestoneType.linkedin_inmail: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.linkedin_inmail,
        channel=ContactChannel.linkedin,
        outcome_patterns=["inmail", "in-mail"],
        sequence_matcher=None,  # No sequence matching for InMail
    ),
    
    # Mail milestones
    JourneyMilestoneType.mail_1: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.mail_1,
        channel=ContactChannel.mail,
        outcome_patterns=["mail", "1", "first", "letter mailed"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) > 0 and attempts[0].id == attempt.id
        ),
    ),
    JourneyMilestoneType.mail_2: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.mail_2,
        channel=ContactChannel.mail,
        outcome_patterns=["mail", "2", "second"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) == 2 and attempts[1].id == attempt.id
        ),
    ),
    JourneyMilestoneType.mail_3: MilestoneMatchingRule(
        milestone_type=JourneyMilestoneType.mail_3,
        channel=ContactChannel.mail,
        outcome_patterns=["mail", "3", "third", "final"],
        sequence_matcher=lambda attempts, attempt: (
            len(attempts) == 3 and attempts[2].id == attempt.id
        ),
    ),
}


def check_prerequisite_milestones(db: Session, journey_id: int, milestone_type: JourneyMilestoneType) -> bool:
    """Check if prerequisite milestones are completed before allowing a match.
    Returns True if prerequisites are met, False otherwise."""
    # Define prerequisite chain for email milestones
    email_prerequisites = {
        JourneyMilestoneType.email_followup_1: [JourneyMilestoneType.email_1],
        JourneyMilestoneType.email_followup_2: [JourneyMilestoneType.email_1, JourneyMilestoneType.email_followup_1],
    }
    
    # Define prerequisite chain for mail milestones
    mail_prerequisites = {
        JourneyMilestoneType.mail_2: [JourneyMilestoneType.mail_1],
        JourneyMilestoneType.mail_3: [JourneyMilestoneType.mail_1, JourneyMilestoneType.mail_2],
    }
    
    # Define prerequisite chain for LinkedIn milestones
    linkedin_prerequisites = {
        JourneyMilestoneType.linkedin_message_1: [JourneyMilestoneType.linkedin_connection],
        JourneyMilestoneType.linkedin_message_2: [JourneyMilestoneType.linkedin_connection, JourneyMilestoneType.linkedin_message_1],
        JourneyMilestoneType.linkedin_message_3: [JourneyMilestoneType.linkedin_connection, JourneyMilestoneType.linkedin_message_1, JourneyMilestoneType.linkedin_message_2],
        JourneyMilestoneType.linkedin_inmail: [JourneyMilestoneType.linkedin_connection],  # InMail requires connection attempt (but not acceptance)
    }
    
    # Check if this milestone has prerequisites
    prerequisites = (email_prerequisites.get(milestone_type) or 
                    mail_prerequisites.get(milestone_type) or 
                    linkedin_prerequisites.get(milestone_type))
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


# ========== PATH-SPECIFIC LINKING HANDLERS ==========

def link_attempt_to_connection_message_path(
    db: Session, attempt: LeadAttempt, milestone: JourneyMilestone, journey: LeadJourney
) -> bool:
    """
    Link attempt to connection→messages path milestones ONLY.
    Handles: linkedin_connection, linkedin_message_1, linkedin_message_2, linkedin_message_3
    Independent logic - doesn't affect InMail path.
    """
    if milestone.milestone_type == JourneyMilestoneType.linkedin_connection:
        # Connection milestone: check if this is the first LinkedIn attempt
        position = get_all_linkedin_attempts_position(db, attempt.lead_id, journey.primary_contact_id, attempt)
        if position == 1:
            logger.debug(f"link_attempt_to_connection_message_path: ✓ Matched connection attempt {attempt.id} to connection milestone")
            return True
        return False
    
    elif milestone.milestone_type in [
        JourneyMilestoneType.linkedin_message_1,
        JourneyMilestoneType.linkedin_message_2,
        JourneyMilestoneType.linkedin_message_3,
    ]:
        # Message milestone: use connection→messages sequence (excludes connection and InMail)
        position = get_connection_message_sequence_position(
            db, attempt.lead_id, journey.primary_contact_id, attempt
        )
        expected_positions = {
            JourneyMilestoneType.linkedin_message_1: 1,
            JourneyMilestoneType.linkedin_message_2: 2,
            JourneyMilestoneType.linkedin_message_3: 3,
        }
        expected_position = expected_positions.get(milestone.milestone_type)
        
        if position == expected_position:
            logger.debug(f"link_attempt_to_connection_message_path: ✓ Matched message attempt {attempt.id} (position {position}) to {milestone.milestone_type}")
            return True
        return False
    
    return False


def link_attempt_to_inmail_path(
    db: Session, attempt: LeadAttempt, milestone: JourneyMilestone, journey: LeadJourney
) -> bool:
    """
    Link attempt to InMail path milestone ONLY.
    Handles: linkedin_inmail
    Matches by outcome pattern, NOT sequence position.
    Independent logic - doesn't affect connection→messages path.
    """
    if milestone.milestone_type != JourneyMilestoneType.linkedin_inmail:
        return False
    
    # InMail is matched by outcome pattern, not sequence
    outcome = (attempt.outcome or "").lower()
    if "inmail" in outcome:
        logger.debug(f"link_attempt_to_inmail_path: ✓ Matched InMail attempt {attempt.id} to InMail milestone")
        return True
    return False


def link_attempt_to_email_path(
    db: Session, attempt: LeadAttempt, milestone: JourneyMilestone, journey: LeadJourney
) -> bool:
    """
    Link attempt to email path milestones ONLY.
    Handles: email_1, email_followup_1, email_followup_2
    Independent logic - doesn't affect other paths.
    """
    if milestone.milestone_type not in [
        JourneyMilestoneType.email_1,
        JourneyMilestoneType.email_followup_1,
        JourneyMilestoneType.email_followup_2,
    ]:
        return False
    
    position = get_email_sequence_position(db, attempt.lead_id, journey.primary_contact_id, attempt)
    expected_positions = {
        JourneyMilestoneType.email_1: 1,
        JourneyMilestoneType.email_followup_1: 2,
        JourneyMilestoneType.email_followup_2: 3,
    }
    expected_position = expected_positions.get(milestone.milestone_type)
    
    if position == expected_position:
        logger.debug(f"link_attempt_to_email_path: ✓ Matched email attempt {attempt.id} (position {position}) to {milestone.milestone_type}")
        return True
    return False


def link_attempt_to_mail_path(
    db: Session, attempt: LeadAttempt, milestone: JourneyMilestone, journey: LeadJourney
) -> bool:
    """
    Link attempt to mail path milestones ONLY.
    Handles: mail_1, mail_2, mail_3
    Independent logic - doesn't affect other paths.
    """
    if milestone.milestone_type not in [
        JourneyMilestoneType.mail_1,
        JourneyMilestoneType.mail_2,
        JourneyMilestoneType.mail_3,
    ]:
        return False
    
    position = get_mail_sequence_position(db, attempt.lead_id, journey.primary_contact_id, attempt)
    expected_positions = {
        JourneyMilestoneType.mail_1: 1,
        JourneyMilestoneType.mail_2: 2,
        JourneyMilestoneType.mail_3: 3,
    }
    expected_position = expected_positions.get(milestone.milestone_type)
    
    if position == expected_position:
        logger.debug(f"link_attempt_to_mail_path: ✓ Matched mail attempt {attempt.id} (position {position}) to {milestone.milestone_type}")
        return True
    return False


def link_attempt_to_milestone(db: Session, attempt: LeadAttempt):
    """
    Main linking function - routes to appropriate path handler.
    Each path handler is independent and doesn't affect others.
    """
    lead_id = attempt.lead_id
    
    # Check if lead has a journey
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        logger.debug(f"link_attempt_to_milestone: No journey found for lead {lead_id}")
        return
    
    logger.debug(f"link_attempt_to_milestone: Found journey {journey.id} for lead {lead_id}, primary_contact_id={journey.primary_contact_id}, attempt.contact_id={attempt.contact_id}, attempt.channel={attempt.channel}")
    
    # Update milestone statuses FIRST to un-skip any milestones that should be active
    # This is critical for LinkedIn milestones that may have been skipped before connection was accepted
    update_milestone_statuses(db, lead_id)
    db.flush()  # Ensure status changes are visible to subsequent query
    
    # Only count attempts for the primary contact
    if journey.primary_contact_id:
        if attempt.contact_id is None:
            logger.debug(f"link_attempt_to_milestone: Attempt {attempt.id} has no contact_id, skipping")
            return
        if attempt.contact_id != journey.primary_contact_id:
            logger.debug(f"link_attempt_to_milestone: Attempt {attempt.id} contact_id {attempt.contact_id} doesn't match primary_contact_id {journey.primary_contact_id}, skipping")
            return
    elif attempt.contact_id is not None:
        logger.debug(f"link_attempt_to_milestone: Journey has no primary_contact_id but attempt has contact_id, skipping")
        return
    
    if not journey.primary_contact_id:
        logger.debug(f"link_attempt_to_milestone: No primary contact set for journey")
        return
    
    # Get the NEXT milestone in sequence (first incomplete one for this channel)
    milestone = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id,
        JourneyMilestone.channel == attempt.channel,
        JourneyMilestone.status.in_([MilestoneStatus.pending, MilestoneStatus.overdue]),
        JourneyMilestone.attempt_id.is_(None)  # Not already linked
    ).order_by(JourneyMilestone.scheduled_day.asc()).first()
    
    if not milestone:
        logger.debug(f"link_attempt_to_milestone: No pending milestones found for channel {attempt.channel}, journey_id={journey.id}")
        return
    
    logger.debug(f"link_attempt_to_milestone: Checking next milestone {milestone.id} (type: {milestone.milestone_type}, scheduled_day: {milestone.scheduled_day}) for channel {attempt.channel}")
    
    # Check if prerequisite milestones are completed (must complete in order)
    if not check_prerequisite_milestones(db, journey.id, milestone.milestone_type):
        logger.debug(f"link_attempt_to_milestone: Prerequisites not met for milestone {milestone.id} (type: {milestone.milestone_type}) - cannot complete until previous milestones are done")
        return
    
    journey_start = journey.started_at
    # Ensure attempt_date is timezone-aware
    if attempt.created_at:
        attempt_date = attempt.created_at
        if attempt_date.tzinfo is None:
            attempt_date = attempt_date.replace(tzinfo=timezone.utc)
    else:
        attempt_date = datetime.now(timezone.utc)
    
    # Ensure attempt is after journey start
    if attempt_date < journey_start:
        logger.debug(f"link_attempt_to_milestone: Attempt {attempt.id} is before journey start, skipping")
        return
    
    # Route to appropriate path handler based on channel and milestone type
    linked = False
    if attempt.channel == ContactChannel.linkedin:
        if milestone.milestone_type in [
            JourneyMilestoneType.linkedin_connection,
            JourneyMilestoneType.linkedin_message_1,
            JourneyMilestoneType.linkedin_message_2,
            JourneyMilestoneType.linkedin_message_3,
        ]:
            # Route to connection→messages path handler
            linked = link_attempt_to_connection_message_path(db, attempt, milestone, journey)
        elif milestone.milestone_type == JourneyMilestoneType.linkedin_inmail:
            # Route to InMail path handler
            linked = link_attempt_to_inmail_path(db, attempt, milestone, journey)
    
    elif attempt.channel == ContactChannel.email:
        # Route to email path handler
        linked = link_attempt_to_email_path(db, attempt, milestone, journey)
    
    elif attempt.channel == ContactChannel.mail:
        # Route to mail path handler
        linked = link_attempt_to_mail_path(db, attempt, milestone, journey)
    
    if linked:
        logger.debug(f"link_attempt_to_milestone: ✓ Matched attempt {attempt.id} to milestone {milestone.id} (type: {milestone.milestone_type})")
        milestone.status = MilestoneStatus.completed
        milestone.completed_at = attempt_date
        milestone.attempt_id = attempt.id
        milestone.updated_at = datetime.now(timezone.utc)
        db.flush()
        
        # Update milestone statuses to handle any overdue/skipped logic
        update_milestone_statuses(db, lead_id)
    else:
        logger.debug(f"link_attempt_to_milestone: ✗ Attempt {attempt.id} did not match milestone {milestone.id} (type: {milestone.milestone_type})")


def cleanup_invalid_milestones(db: Session, journey_id: int):
    """Delete any milestones with invalid enum values (e.g., email_followup_3)."""
    try:
        # Delete milestones with email_followup_3 using raw SQL
        db.execute(
            text("DELETE FROM lead_journey_milestone WHERE journey_id = :journey_id AND milestone_type = 'email_followup_3'"),
            {"journey_id": journey_id}
        )
        db.flush()
    except Exception as e:
        # Log but don't fail - this is a cleanup operation
        logger.warning(f"Failed to cleanup invalid milestones: {e}")


def update_milestone_statuses(db: Session, lead_id: int):
    """Update milestone statuses based on current date and conditions."""
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return
    
    # Clean up any invalid milestones before querying
    cleanup_invalid_milestones(db, journey.id)
    
    milestones = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id
    ).all()
    
    now = datetime.now(timezone.utc)
    journey_start = journey.started_at
    
    # Get LinkedIn connection status - only check primary contact's attempts
    is_connected = False
    if journey.primary_contact_id:
        linkedin_attempts = db.query(LeadAttempt).filter(
            LeadAttempt.lead_id == lead_id,
            LeadAttempt.contact_id == journey.primary_contact_id,
            LeadAttempt.channel == ContactChannel.linkedin
        ).all()
        
        for attempt in linkedin_attempts:
            outcome = (attempt.outcome or "").lower()
            if "connection accepted" in outcome:
                is_connected = True
                break
    
    for milestone in milestones:
        # Calculate expected date
        expected_date = journey_start + timedelta(days=milestone.scheduled_day)
        days_elapsed = (now - journey_start).days
        
        # Handle LinkedIn branching
        if milestone.channel == ContactChannel.linkedin:
            # Don't modify completed milestones
            if milestone.status == MilestoneStatus.completed:
                continue
            
            # Handle branch conditions
            if milestone.branch_condition == "if_connected":
                if not is_connected:
                    # Connection not accepted - skip message milestones
                    if milestone.status != MilestoneStatus.skipped:
                        milestone.status = MilestoneStatus.skipped
                        milestone.updated_at = datetime.now(timezone.utc)
                else:
                    # Connection is accepted - un-skip message milestones if they were skipped
                    if milestone.status == MilestoneStatus.skipped:
                        # Reset to pending or overdue based on date
                        if days_elapsed >= milestone.scheduled_day:
                            milestone.status = MilestoneStatus.overdue
                        else:
                            milestone.status = MilestoneStatus.pending
                        milestone.updated_at = datetime.now(timezone.utc)
                    elif days_elapsed >= milestone.scheduled_day and milestone.status == MilestoneStatus.pending:
                        milestone.status = MilestoneStatus.overdue
                        milestone.updated_at = datetime.now(timezone.utc)
            elif milestone.branch_condition == "if_not_connected":
                if is_connected:
                    # Connection is accepted - skip InMail (but only if not already completed)
                    if milestone.status != MilestoneStatus.completed and milestone.status != MilestoneStatus.skipped:
                        milestone.status = MilestoneStatus.skipped
                        milestone.updated_at = datetime.now(timezone.utc)
                else:
                    # Connection not accepted - InMail can proceed
                    if milestone.status == MilestoneStatus.skipped:
                        # Un-skip if it was previously skipped
                        if days_elapsed >= milestone.scheduled_day:
                            milestone.status = MilestoneStatus.overdue
                        else:
                            milestone.status = MilestoneStatus.pending
                        milestone.updated_at = datetime.now(timezone.utc)
                    elif days_elapsed >= milestone.scheduled_day and milestone.status == MilestoneStatus.pending:
                        milestone.status = MilestoneStatus.overdue
                        milestone.updated_at = datetime.now(timezone.utc)
            else:
                # No branch condition (like linkedin_connection) - just check if overdue
                if days_elapsed >= milestone.scheduled_day and milestone.status == MilestoneStatus.pending:
                    milestone.status = MilestoneStatus.overdue
                    milestone.updated_at = datetime.now(timezone.utc)
        else:
            # For non-LinkedIn milestones, check if overdue
            if milestone.status == MilestoneStatus.completed:
                continue
            if days_elapsed >= milestone.scheduled_day and milestone.status == MilestoneStatus.pending:
                milestone.status = MilestoneStatus.overdue
                milestone.updated_at = datetime.now(timezone.utc)


def get_journey_status_summary(db: Session, lead_id: int) -> dict | None:
    """Get a summary of journey status for a lead (for list view indicators)."""
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return None
    
    # Clean up any invalid milestones before updating
    cleanup_invalid_milestones(db, journey.id)
    
    # Update statuses before checking
    update_milestone_statuses(db, lead_id)
    
    # Get all milestones
    milestones = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id
    ).all()
    
    now = datetime.now(timezone.utc)
    journey_start = journey.started_at
    
    overdue = []
    due_soon = []  # 0-2 days
    upcoming = []  # 3-7 days
    
    milestone_labels = {
        JourneyMilestoneType.email_1: "Email #1 Initial",
        JourneyMilestoneType.email_followup_1: "Follow-up #1",
        JourneyMilestoneType.email_followup_2: "Final Nudge",
        JourneyMilestoneType.linkedin_connection: "Connection Request",
        JourneyMilestoneType.linkedin_message_1: "Message #1",
        JourneyMilestoneType.linkedin_message_2: "Message #2",
        JourneyMilestoneType.linkedin_message_3: "Message #3",
        JourneyMilestoneType.linkedin_inmail: "InMail",
        JourneyMilestoneType.mail_1: "Mail #1",
        JourneyMilestoneType.mail_2: "Mail #2",
        JourneyMilestoneType.mail_3: "Mail #3",
    }
    
    channel_icons = {
        ContactChannel.email: "📧",
        ContactChannel.linkedin: "💼",
        ContactChannel.mail: "📮",
    }
    
    for milestone in milestones:
        # Skip completed and skipped milestones
        if milestone.status == MilestoneStatus.completed or milestone.status == MilestoneStatus.skipped:
            continue
        
        expected_date = journey_start + timedelta(days=milestone.scheduled_day)
        days_until = (expected_date - now).days
        
        milestone_data = {
            "label": milestone_labels.get(milestone.milestone_type, milestone.milestone_type.value),
            "channel": milestone.channel.value,
            "channel_icon": channel_icons.get(milestone.channel, "•"),
            "expected_date": expected_date.isoformat(),
            "days_until": days_until,
        }
        
        if milestone.status == MilestoneStatus.overdue or days_until < 0:
            overdue.append(milestone_data)
        elif days_until <= 2:  # 0-2 days
            due_soon.append(milestone_data)
        elif days_until <= 7:  # 3-7 days
            upcoming.append(milestone_data)
    
    # Determine priority status
    priority = None
    if overdue:
        priority = "overdue"
    elif due_soon:
        priority = "due_soon"
    elif upcoming:
        priority = "upcoming"
    else:
        priority = "none"
    
    return {
        "priority": priority,
        "overdue_count": len(overdue),
        "due_soon_count": len(due_soon),
        "upcoming_count": len(upcoming),
        "overdue": overdue,
        "due_soon": due_soon,
        "upcoming": upcoming,
    }


def get_journey_data(db: Session, lead_id: int) -> dict | None:
    """Get journey data for a lead, including all milestones."""
    from models import LeadContact
    
    journey = db.query(LeadJourney).filter(LeadJourney.lead_id == lead_id).first()
    if not journey:
        return None
    
    # Clean up any invalid milestones before updating
    cleanup_invalid_milestones(db, journey.id)
    
    # Update statuses before returning
    update_milestone_statuses(db, lead_id)
    db.refresh(journey)
    
    # Get all milestones grouped by channel
    milestones = db.query(JourneyMilestone).filter(
        JourneyMilestone.journey_id == journey.id
    ).order_by(JourneyMilestone.scheduled_day.asc()).all()
    
    now = datetime.now(timezone.utc)
    days_elapsed = (now - journey.started_at).days
    
    # Group milestones by channel
    email_milestones = []
    linkedin_milestones = []
    mail_milestones = []
    
    milestone_labels = {
        JourneyMilestoneType.email_1: "Email #1 Initial",
        JourneyMilestoneType.email_followup_1: "Follow-up #1",
        JourneyMilestoneType.email_followup_2: "Final Nudge",
        JourneyMilestoneType.linkedin_connection: "Connection Request",
        JourneyMilestoneType.linkedin_message_1: "Message #1",
        JourneyMilestoneType.linkedin_message_2: "Message #2",
        JourneyMilestoneType.linkedin_message_3: "Message #3",
        JourneyMilestoneType.linkedin_inmail: "InMail",
        JourneyMilestoneType.mail_1: "Mail #1",
        JourneyMilestoneType.mail_2: "Mail #2",
        JourneyMilestoneType.mail_3: "Mail #3",
    }
    
    for milestone in milestones:
        expected_date = journey.started_at + timedelta(days=milestone.scheduled_day)
        milestone_data = {
            "id": milestone.id,
            "type": milestone.milestone_type.value,
            "label": milestone_labels.get(milestone.milestone_type, milestone.milestone_type.value),
            "scheduled_day": milestone.scheduled_day,
            "status": milestone.status.value,
            "expected_date": expected_date.isoformat(),
            "completed_at": milestone.completed_at.isoformat() if milestone.completed_at else None,
            "attempt_id": milestone.attempt_id,
            "branch_condition": milestone.branch_condition,
        }
        
        if milestone.channel == ContactChannel.email:
            email_milestones.append(milestone_data)
        elif milestone.channel == ContactChannel.linkedin:
            linkedin_milestones.append(milestone_data)
        elif milestone.channel == ContactChannel.mail:
            mail_milestones.append(milestone_data)
    
    # Get primary contact info
    primary_contact = None
    if journey.primary_contact_id:
        primary_contact_obj = db.get(LeadContact, journey.primary_contact_id)
        if primary_contact_obj:
            primary_contact = {
                "id": primary_contact_obj.id,
                "name": primary_contact_obj.contact_name,
                "title": primary_contact_obj.title,
            }
    
    return {
        "journey_id": journey.id,
        "started_at": journey.started_at.isoformat(),
        "status": journey.status.value,
        "days_elapsed": days_elapsed,
        "primary_contact": primary_contact,
        "email": email_milestones,
        "linkedin": linkedin_milestones,
        "mail": mail_milestones,
    }

