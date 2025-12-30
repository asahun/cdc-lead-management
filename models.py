# models.py
from sqlalchemy import (
    Column,
    BigInteger,
    Text,
    Numeric,
    Enum,
    ForeignKey,
    Integer,
    DateTime,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from db import Base
import enum

class PropertyView(Base):
    __tablename__ = "property"

    raw_hash = Column("row_hash", Text, primary_key=True)
    propertyid = Column(Text)
    ownername = Column(Text)
    propertyamount = Column(Numeric(18, 2))
    last_seen = Column(DateTime(timezone=True))
    assigned_to_lead = Column(Boolean, nullable=False, default=False)
    owneraddress1 = Column(Text)
    owneraddress2 = Column(Text)
    owneraddress3 = Column(Text)
    ownercity = Column(Text)
    ownerstate = Column(Text)
    ownerzipcode = Column(Text)
    ownerrelation = Column(Text)
    lastactivitydate = Column(Text)
    reportyear = Column(Text)
    holdername = Column(Text)
    propertytypedescription = Column(Text)


class PropertyOwnershipType(Base):
    __tablename__ = "property_ownership_type"

    code = Column("Code", Text, primary_key=True)
    Claim_Authority = Column("Claim_Authority", Text)


class LeadStatus(str, enum.Enum):
    new = "new"
    researching = "researching"
    contact_in_progress = "contact_in_progress"
    response_received = "response_received"
    claim_created = "claim_created"
    won = "won"
    lost = "lost"
    no_response = "no_response"
    invalid = "invalid"
    competitor_claimed = "competitor_claimed"
    ready = "ready"


class OwnerType(str, enum.Enum):
    business = "business"
    individual = "individual"


class BusinessOwnerStatus(str, enum.Enum):
    acquired_or_merged = "acquired_or_merged"
    active = "active"
    active_renamed = "active_renamed"
    dissolved = "dissolved"


class OwnerSize(str, enum.Enum):
    individual = "individual"
    corporate = "corporate"


class IndividualOwnerStatus(str, enum.Enum):
    alive = "alive"
    deceased = "deceased"


class ContactChannel(str, enum.Enum):
    email = "email"
    phone = "phone"
    mail = "mail"
    linkedin = "linkedin"
    text = "text"
    other = "other"


class ContactType(str, enum.Enum):
    employee = "employee"
    owner = "owner"
    agent = "agent"
    agent_company = "agent_company"
    heir = "heir"


class JourneyStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    paused = "paused"


class JourneyMilestoneType(str, enum.Enum):
    # Email milestones
    email_1 = "email_1"
    email_followup_1 = "email_followup_1"
    email_followup_2 = "email_followup_2"
    # LinkedIn milestones
    linkedin_connection = "linkedin_connection"
    linkedin_message_1 = "linkedin_message_1"
    linkedin_message_2 = "linkedin_message_2"
    linkedin_message_3 = "linkedin_message_3"
    linkedin_inmail = "linkedin_inmail"
    # Mail milestones
    mail_1 = "mail_1"
    mail_2 = "mail_2"
    mail_3 = "mail_3"


class MilestoneStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    skipped = "skipped"
    overdue = "overdue"


class LeadProperty(Base):
    __tablename__ = "lead_property"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Text, nullable=False)
    property_raw_hash = Column(Text, nullable=False)
    property_amount = Column(Numeric(18, 2))
    is_primary = Column(Boolean, nullable=False, default=False)
    added_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="properties")
    
    __table_args__ = (
        # Unique constraint: a property can only be assigned to one lead
        UniqueConstraint('property_raw_hash', name='uq_lead_property_raw_hash'),
    )


class Lead(Base):
    __tablename__ = "lead"

    id = Column(BigInteger, primary_key=True)
    owner_name = Column(Text, nullable=False)

    status = Column(Enum(LeadStatus, name="lead_status"), nullable=False, default=LeadStatus.new)
    notes = Column(Text)
    owner_type = Column(Enum(OwnerType, name="owner_type"), nullable=False, default=OwnerType.business)
    business_owner_status = Column(Enum(BusinessOwnerStatus, name="business_owner_status"), nullable=True)
    owner_size = Column(Enum(OwnerSize, name="owner_size"), nullable=True)
    new_business_name = Column(Text)
    individual_owner_status = Column(Enum(IndividualOwnerStatus, name="individual_owner_status"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    properties = relationship("LeadProperty", back_populates="lead", cascade="all, delete-orphan", order_by="LeadProperty.is_primary.desc(), LeadProperty.added_at")
    contacts = relationship("LeadContact", back_populates="lead", cascade="all, delete-orphan")
    attempts = relationship("LeadAttempt", back_populates="lead", cascade="all, delete-orphan")
    comments = relationship("LeadComment", back_populates="lead", cascade="all, delete-orphan")
    print_logs = relationship("PrintLog", back_populates="lead", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="lead", cascade="all, delete-orphan")
    journey = relationship("LeadJourney", back_populates="lead", uselist=False, cascade="all, delete-orphan")


class LeadContact(Base):
    __tablename__ = "lead_contact"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)

    contact_name = Column(Text, nullable=False)
    title = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    linkedin_url = Column(Text)
    address_street = Column(Text)
    address_city = Column(Text)
    address_state = Column(Text)
    address_zipcode = Column(Text)
    contact_type = Column(Enum(ContactType, name="lead_contact_type"), nullable=False, default=ContactType.employee)
    is_primary = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="contacts")


class LeadAttempt(Base):
    __tablename__ = "lead_attempt"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("lead_contact.id", ondelete="SET NULL"), nullable=True)

    channel = Column(Enum(ContactChannel, name="contact_channel"), nullable=False)
    attempt_number = Column(Integer, nullable=False, default=1)
    outcome = Column(Text)
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="attempts")
    # if you want contact relationship:
    contact = relationship("LeadContact", foreign_keys=[contact_id])


class LeadComment(Base):
    __tablename__ = "lead_comment"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    author = Column(Text)
    body = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="comments")


class ScheduledEmailStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"
    missed = "missed"


class ScheduledEmail(Base):
    __tablename__ = "lead_scheduled_email"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("lead_contact.id", ondelete="SET NULL"), nullable=True)
    
    to_email = Column(Text, nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(ScheduledEmailStatus, name="scheduled_email_status"), nullable=False, default=ScheduledEmailStatus.pending)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    lead = relationship("Lead")
    contact = relationship("LeadContact", foreign_keys=[contact_id])


class PrintLog(Base):
    __tablename__ = "lead_print_log"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("lead_contact.id", ondelete="SET NULL"), nullable=True)
    filename = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    printed_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    mailed = Column(Boolean, nullable=False, default=False)
    mailed_at = Column(DateTime(timezone=True), nullable=True)
    attempt_id = Column(BigInteger, ForeignKey("lead_attempt.id", ondelete="SET NULL"), nullable=True)

    lead = relationship("Lead", back_populates="print_logs")
    contact = relationship("LeadContact", foreign_keys=[contact_id])
    attempt = relationship("LeadAttempt", foreign_keys=[attempt_id])


class LeadJourney(Base):
    __tablename__ = "lead_journey"

    id = Column(BigInteger, primary_key=True)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False, unique=True)
    primary_contact_id = Column(BigInteger, ForeignKey("lead_contact.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    status = Column(Enum(JourneyStatus, name="journey_status"), nullable=False, default=JourneyStatus.active)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="journey")
    primary_contact = relationship("LeadContact", foreign_keys=[primary_contact_id])
    milestones = relationship("JourneyMilestone", back_populates="journey", cascade="all, delete-orphan", order_by="JourneyMilestone.scheduled_day")


class JourneyMilestone(Base):
    __tablename__ = "lead_journey_milestone"

    id = Column(BigInteger, primary_key=True)
    journey_id = Column(BigInteger, ForeignKey("lead_journey.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    
    milestone_type = Column(Enum(JourneyMilestoneType, name="journey_milestone_type"), nullable=False)
    channel = Column(Enum(ContactChannel, name="contact_channel"), nullable=False)
    scheduled_day = Column(Integer, nullable=False)  # Day 0, 1, 3, 4, 7, etc.
    status = Column(Enum(MilestoneStatus, name="milestone_status"), nullable=False, default=MilestoneStatus.pending)
    
    completed_at = Column(DateTime(timezone=True), nullable=True)
    attempt_id = Column(BigInteger, ForeignKey("lead_attempt.id", ondelete="SET NULL"), nullable=True)
    
    parent_milestone_id = Column(BigInteger, ForeignKey("lead_journey_milestone.id", ondelete="SET NULL"), nullable=True)
    branch_condition = Column(Text, nullable=True)  # "if_connected", "if_not_connected", or None
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    journey = relationship("LeadJourney", back_populates="milestones")
    attempt = relationship("LeadAttempt", foreign_keys=[attempt_id])
    parent_milestone = relationship("JourneyMilestone", remote_side=[id], foreign_keys=[parent_milestone_id])

# Agreement/Client models

class SignerType(str, enum.Enum):
    primary = "primary"
    secondary = "secondary"


class Client(Base):
    __tablename__ = "client"

    id = Column(Integer, primary_key=True, index=True)
    entitled_business_name = Column(Text, nullable=False)
    formation_state = Column(Text, nullable=True)
    control_no = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    contacts = relationship("ClientContact", back_populates="client", cascade="all, delete-orphan")
    mailing_addresses = relationship("ClientMailingAddress", back_populates="client", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="client", cascade="all, delete-orphan")


class ClientContact(Base):
    __tablename__ = "client_contact"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    lead_contact_id = Column(BigInteger, ForeignKey("lead_contact.id", ondelete="SET NULL"), nullable=True)
    signer_type = Column(Enum(SignerType, name="signer_type_enum"), nullable=False)
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="contacts")
    lead_contact = relationship("LeadContact", foreign_keys=[lead_contact_id])


class ClientMailingAddress(Base):
    __tablename__ = "client_mailing_address"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    street = Column(Text, nullable=False)
    line2 = Column(Text, nullable=True)
    city = Column(Text, nullable=False)
    state = Column(Text, nullable=False)
    zip = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="mailing_addresses")
    claims = relationship("Claim", back_populates="check_mailing_address", foreign_keys="Claim.check_mailing_address_id")


class Claim(Base):
    __tablename__ = "claim"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("client.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(BigInteger, ForeignKey("lead.id", ondelete="CASCADE"), nullable=False)
    claim_slug = Column(Text, unique=True, nullable=False)

    # Business name snapshot (duplicated from client for historical record)
    entitled_business_name = Column(Text, nullable=False)
    entitled_business_same_as_owner = Column(Boolean, default=True)

    # Fee structure (one of fee_pct or fee_flat must be set)
    fee_pct = Column(Numeric(5, 2), nullable=True)  # Percentage (e.g., 10.50 for 10.5%), NULL if using flat fee
    fee_flat = Column(Numeric(18, 2), nullable=True)  # Flat dollar amount, NULL if using percentage
    cdr_fee = Column(Numeric(18, 2), nullable=True)  # Calculated fee amount

    # Claim-specific data
    addendum_yes = Column(Boolean, default=False)
    total_properties = Column(Integer, nullable=True)
    total_amount = Column(Numeric(18, 2), nullable=True)
    state_claim_id = Column(Text, nullable=True)
    check_mailing_address_id = Column(Integer, ForeignKey("client_mailing_address.id", ondelete="SET NULL"), nullable=True)
    output_dir = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="claims")
    lead = relationship("Lead", back_populates="claims")
    check_mailing_address = relationship("ClientMailingAddress", foreign_keys=[check_mailing_address_id])
    events = relationship("ClaimEvent", back_populates="claim", cascade="all, delete-orphan")
    documents = relationship("ClaimDocument", back_populates="claim", cascade="all, delete-orphan")


class ClaimEvent(Base):
    __tablename__ = "claim_event"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claim.id", ondelete="CASCADE"), nullable=False)
    state = Column(Text, nullable=False)
    payload = Column(Text)  # JSON string
    created_by = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="events")


class ClaimDocument(Base):
    __tablename__ = "claim_document"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claim.id", ondelete="CASCADE"), nullable=False)
    doc_type = Column(Text, nullable=False)  # agreement_signed, authorization_signed, addendum, non_disclosure, fein_document, id_verification, address_verification, b2b_relationship, other
    original_name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)  # required when doc_type == 'other'
    created_by = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    claim = relationship("Claim", back_populates="documents")
