"""Entity Intelligence AI service for GPT-based analysis."""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from openai import OpenAI

from services.exceptions import GPTConfigError, GPTServiceError

logger = logging.getLogger(__name__)

# Configuration
OPENAI_MODEL = os.getenv("GPT_CORP_HISTORY_MODEL", "gpt-5.1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def _generate_default_from_schema(schema_def: Dict[str, Any]) -> Any:
    """
    Recursively generate default values from a JSON schema definition.
    
    Args:
        schema_def: A property definition from the JSON schema
        
    Returns:
        Default value based on the schema type
    """
    # Handle union types (e.g., ["string", "null"])
    type_value = schema_def.get("type")
    if isinstance(type_value, list):
        # For union types, prefer non-null types, but allow null
        non_null_types = [t for t in type_value if t != "null"]
        if non_null_types:
            type_value = non_null_types[0]
        else:
            type_value = "null"
    
    # Handle enum - pick first value
    if "enum" in schema_def:
        enum_values = schema_def["enum"]
        non_null_enums = [e for e in enum_values if e is not None]
        if non_null_enums:
            return non_null_enums[0]
        elif enum_values:
            return enum_values[0]
    
    # Generate defaults based on type
    if type_value == "string":
        return ""
    elif type_value == "boolean":
        return False
    elif type_value == "integer":
        return 0
    elif type_value == "number":
        return 0.0
    elif type_value == "array":
        return []
    elif type_value == "object":
        properties = schema_def.get("properties", {})
        result = {}
        for prop_name, prop_schema in properties.items():
            result[prop_name] = _generate_default_from_schema(prop_schema)
        return result
    elif type_value == "null":
        return None
    else:
        return None


def _generate_schema_defaults(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate default values for all top-level properties in the response schema.
    
    Args:
        schema: The full JSON schema object
        
    Returns:
        Dictionary with default values for all required and optional properties
    """
    defaults = {}
    properties = schema.get("properties", {})
    
    for prop_name, prop_schema in properties.items():
        defaults[prop_name] = _generate_default_from_schema(prop_schema)
    
    return defaults


def _load_gpt_prompt_and_schema():
    """Load GPT system prompt and response schema from files."""
    service_dir = Path(__file__).parent
    prompts_dir = service_dir / "prompts"
    
    # Load system prompt
    prompt_file = prompts_dir / "gpt_system_prompt.txt"
    with open(prompt_file, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()
    
    # Load response schema
    schema_file = prompts_dir / "gpt_response_schema.json"
    with open(schema_file, "r", encoding="utf-8") as f:
        response_schema = json.load(f)
    
    return system_prompt, response_schema


# Load prompt and schema once at module import time
GPT_SYSTEM_PROMPT, GPT_RESPONSE_SCHEMA = _load_gpt_prompt_and_schema()

GPT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": GPT_RESPONSE_SCHEMA.get("name", "entitled_entity_response_v12"),
        "schema": GPT_RESPONSE_SCHEMA,
        "strict": True,
    },
}


class EntityIntelligenceService:
    """Service for GPT-based entity intelligence analysis."""
    
    def __init__(self):
        """Initialize Entity Intelligence service."""
        if not OPENAI_API_KEY:
            raise GPTConfigError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = OPENAI_MODEL
    
    def build_no_web_presence_response(
        self,
        business_name: str,
        property_state: str,
        sos_records: List[Dict[str, Any]],
        sos_search_names_tried: List[str],
        google_places_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a minimal response structure when no web presence is found.
        Uses schema-driven defaults to ensure structure matches the schema.
        
        Args:
            business_name: Original business name input
            property_state: State where property is located
            sos_records: List of SOS records found (if any)
            sos_search_names_tried: List of names tried in SOS search
            google_places_profile: Google Places profile data (if any)
            
        Returns:
            Complete response structure matching the schema with appropriate defaults
        """
        # Start with schema-driven defaults
        response = _generate_schema_defaults(GPT_RESPONSE_SCHEMA)
        
        # Extract SOS data if available (only if exactly 1 record, otherwise None)
        sos_record = sos_records[0] if len(sos_records) == 1 else None
        
        # Update query_context with actual data
        if "query_context" in response:
            query_ctx = response["query_context"]
            if "owner_name_input" in query_ctx:
                query_ctx["owner_name_input"] = business_name
            if "state_focus" in query_ctx:
                query_ctx["state_focus"] = property_state
            if "phase1_ga_sos_found" in query_ctx:
                query_ctx["phase1_ga_sos_found"] = bool(sos_records)
            if "phase1_variants_checked" in query_ctx:
                query_ctx["phase1_variants_checked"] = sos_search_names_tried
            if "phase1_note" in query_ctx:
                query_ctx["phase1_note"] = "No web presence found - small local business may not have internet history"
        
        # Update context_inputs
        if "context_inputs" in response:
            ctx_inputs = response["context_inputs"]
            if "ga_sos_selected_record" in ctx_inputs:
                ctx_inputs["ga_sos_selected_record"] = sos_record
            if "google_places_context" in ctx_inputs:
                ctx_inputs["google_places_context"] = google_places_profile
        
        # Build a minimal hypothesis when no web presence
        if "hypotheses" in response and isinstance(response["hypotheses"], list):
            hypothesis = {
                "rank": 1,
                "hypothesis_type": "unknown" if not sos_records else "same_entity",
                "candidate_entitled_name": sos_record.get("business_name") if sos_records else business_name,
                "operating_status_web": "unknown",
                "website": None,
                "primary_contact_page": None,
                "mailing_address_web": None,
                "phones": [],
                "emails": [],
                "named_contacts": [],
                "relationship_notes": [],
                "evidence": [],
                "confidence": "low",
                "gaps_or_next_checks": ["No web presence found - small local business may not have internet history"]
            }
            
            # Add SOS address if available
            if sos_records and sos_record.get("addresses"):
                addr = sos_record["addresses"][0]
                addr_parts = []
                if addr.get("street_address1"):
                    addr_parts.append(addr["street_address1"])
                if addr.get("street_address2"):
                    addr_parts.append(addr["street_address2"])
                city_state_zip = []
                if addr.get("city"):
                    city_state_zip.append(addr["city"])
                if addr.get("state"):
                    city_state_zip.append(addr["state"])
                if addr.get("zip"):
                    city_state_zip.append(addr["zip"])
                if city_state_zip:
                    addr_parts.append(", ".join(city_state_zip))
                if addr_parts:
                    hypothesis["mailing_address_web"] = " ".join(addr_parts)
            
            # Add Google Places data if available
            if google_places_profile:
                if google_places_profile.get("website_uri"):
                    hypothesis["website"] = google_places_profile["website_uri"]
                if google_places_profile.get("national_phone"):
                    hypothesis["phones"] = [google_places_profile["national_phone"]]
            
            response["hypotheses"] = [hypothesis]
        
        # Update selected_entitled_entity
        if "selected_entitled_entity" in response:
            selected = response["selected_entitled_entity"]
            if "selected_rank" in selected:
                selected["selected_rank"] = 1
            if "entitled_business_name" in selected:
                selected["entitled_business_name"] = sos_record.get("business_name") if sos_records else business_name
            if "operating_status_web" in selected:
                selected["operating_status_web"] = "unknown"
            if "best_outreach_channel" in selected:
                selected["best_outreach_channel"] = "mail"
            if "why_selected" in selected:
                selected["why_selected"] = "No web presence found. Using SOS data if available, otherwise using input name."
            if "source_urls" in selected:
                selected["source_urls"] = []
            if "outreach_contacts" in selected:
                contacts = selected["outreach_contacts"]
                if isinstance(contacts, dict):
                    contacts["phones"] = []
                    contacts["emails"] = []
                    contacts["contact_forms"] = []
                    contacts["named_contacts"] = []
                    if google_places_profile and google_places_profile.get("national_phone"):
                        contacts["phones"] = [google_places_profile["national_phone"]]
        
        # Update meta timestamp
        if "meta" in response:
            meta = response["meta"]
            if "timestamp_utc" in meta:
                meta["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
            if "model_notes" in meta:
                meta["model_notes"] = "No web presence found - response generated without GPT analysis"
        
        # Add custom flag for UI
        response["no_web_presence"] = True
        
        return response
    
    def analyze_entity(
        self,
        business_name: str,
        property_state: str,
        last_activity_date: Optional[str] = None,
        property_report_year: Optional[int] = None,
        ga_sos_records: Optional[List[Dict[str, Any]]] = None,
        sos_search_names_tried: Optional[List[str]] = None,
        sos_matched_name: Optional[str] = None,
        web_pages: Optional[List[Dict[str, Any]]] = None,
        google_places_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform GPT analysis on entity intelligence data.
        
        Args:
            business_name: Original business name
            property_state: State where property is located
            last_activity_date: Last activity date (optional)
            property_report_year: Property report year (optional)
            ga_sos_records: Redacted SOS records (optional)
            sos_search_names_tried: List of SOS search names tried (optional)
            sos_matched_name: SOS matched name (optional)
            web_pages: Scraped web pages (optional)
            google_places_profile: Google Places profile (optional)
            
        Returns:
            GPT analysis response dictionary
            
        Raises:
            GPTServiceError: If GPT API call fails
        """
        # Build user payload
        user_payload = {
            "owner_name_input": business_name,
            "business": {
                "business_name": business_name,
                "property_state": property_state,
                "last_activity_date": last_activity_date,
                "property_report_year": property_report_year,
            },
            "ga_sos_records": ga_sos_records or [],
            "sos_search_names_tried": sos_search_names_tried or [],
            "sos_matched_name": sos_matched_name,
            "web_pages": [
                {
                    "id": p["id"],
                    "url": p["url"],
                    "title": p["title"],
                    "type": p["type"],
                    "content": p["content"],
                }
                for p in (web_pages or [])
            ],
            "google_places_profile": google_places_profile,
        }
        
        logger.info(f"analyze_entity: Building GPT payload with {len(ga_sos_records or [])} redacted SOS records and {len(web_pages or [])} web pages")
        
        try:
            logger.debug(f"analyze_entity: Calling GPT API with model={self.model}")
            response = self.client.chat.completions.create(
                model=self.model,
                response_format=GPT_RESPONSE_FORMAT,
                messages=[
                    {"role": "system", "content": GPT_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
            )
            
            # Extract response content
            raw_text = response.choices[0].message.content
            logger.debug(f"analyze_entity: GPT response received, length={len(raw_text)}")
            data = json.loads(raw_text)
            
            # Debug: Log all keys in the response
            response_keys = list(data.keys())
            logger.info(f"analyze_entity: GPT response keys: {response_keys}")
            
            # Check for missing required fields
            schema_required = GPT_RESPONSE_SCHEMA.get("required", [])
            missing_fields = [f for f in schema_required if f not in data]
            if missing_fields:
                logger.warning(f"analyze_entity: Missing required fields: {missing_fields}")
            
            # Log selected entity for summary
            selected_entity_name = "N/A"
            if "selected_entitled_entity" in data:
                selected = data["selected_entitled_entity"]
                selected_entity_name = selected.get("entitled_business_name", "N/A")
            elif "hypotheses" in data and isinstance(data["hypotheses"], list) and len(data["hypotheses"]) > 0:
                selected_entity_name = data["hypotheses"][0].get("candidate_entitled_name", "N/A")
            
            logger.info(f"analyze_entity: GPT analysis complete - selected_entity={selected_entity_name}")
            return data
            
        except Exception as e:
            logger.error(f"analyze_entity: GPT API call failed: {e}", exc_info=True)
            raise GPTServiceError(f"GPT API call failed: {e}") from e

