from typing import Any
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    business_id: str | int | None = None
    business_name: str = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2)
    property_ids: list[str] | None = None
    holder_name_on_record: str | None = None
    last_activity_date: str | None = None
    property_report_year: int | None = None
    city: str | None = None
    ownerrelation: str | None = None
    propertytypedescription: str | None = None
    holder_known_address: dict[str, Any] | None = None
    address_source: str | None = None


class EvidenceItem(BaseModel):
    source: str
    title: str
    url: str
    snippet: str
    confidence: float


class AuditStep(BaseModel):
    name: str
    started_at: str
    ended_at: str | None
    notes: str | None = None


class AuditTrail(BaseModel):
    steps: list[AuditStep] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    input: RunRequest
    analysis: dict[str, Any] = Field(default_factory=dict)
    resolution: dict[str, Any] = Field(default_factory=dict)
    audit: AuditTrail
