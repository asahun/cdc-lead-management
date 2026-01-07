import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from ai_agent.settings import Settings

logger = logging.getLogger(__name__)


def _load_prompt_and_schema() -> tuple[str, dict[str, Any]]:
    from importlib import resources

    prompt_text = resources.files("ai_agent.prompts").joinpath("gpt_system_prompt.txt").read_text()
    schema_text = resources.files("ai_agent.prompts").joinpath("gpt_response_schema.json").read_text()
    return prompt_text.strip(), json.loads(schema_text)


def _generate_default_from_schema(schema_def: dict[str, Any]) -> Any:
    type_value = schema_def.get("type")
    if isinstance(type_value, list):
        non_null_types = [t for t in type_value if t != "null"]
        type_value = non_null_types[0] if non_null_types else "null"

    if "enum" in schema_def:
        enum_values = schema_def["enum"]
        non_null_enums = [e for e in enum_values if e is not None]
        return non_null_enums[0] if non_null_enums else (enum_values[0] if enum_values else None)

    if type_value == "string":
        return ""
    if type_value == "boolean":
        return False
    if type_value == "integer":
        return 0
    if type_value == "number":
        return 0.0
    if type_value == "array":
        return []
    if type_value == "object":
        props = schema_def.get("properties", {})
        return {key: _generate_default_from_schema(val) for key, val in props.items()}
    if type_value == "null":
        return None
    return None


def _generate_schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties", {})
    return {key: _generate_default_from_schema(val) for key, val in props.items()}


def build_fallback_response(
    business_name: str,
    state: str,
    ga_sos_record: dict[str, Any] | None,
    sos_search_names_tried: list[str],
    google_places_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    _, response_schema = _load_prompt_and_schema()
    response = _generate_schema_defaults(response_schema)

    response["query_context"] = {
        "owner_name_input": business_name,
        "state_focus": state,
        "phase1_ga_sos_found": bool(ga_sos_record),
        "phase1_variants_checked": sos_search_names_tried,
        "phase1_note": "No web evidence available; review SOS and official records.",
    }
    response["context_inputs"] = {
        "ga_sos_selected_record": ga_sos_record,
        "google_places_context": google_places_profile,
    }

    response["hypotheses"] = [
        {
            "rank": 1,
            "hypothesis_type": "unknown",
            "candidate_entitled_name": business_name,
            "operating_status_web": "unknown",
            "website": None,
            "primary_contact_page": None,
            "mailing_address_web": None,
            "phones": [],
            "emails": [],
            "named_contacts": [],
            "relationship_notes": [],
            "evidence": [
                {
                    "source_url": "n/a",
                    "source_type": "other",
                    "what_it_supports": "No web evidence available.",
                    "quote_or_extract": None,
                }
            ],
            "confidence": "low",
            "gaps_or_next_checks": ["Find official website or filing records."],
        }
    ]

    response["selected_entitled_entity"] = {
        "selected_rank": 1,
        "entitled_business_name": business_name,
        "operating_status_web": "unknown",
        "website": None,
        "mailing_address_web": None,
        "best_outreach_channel": "unknown",
        "outreach_contacts": {
            "phones": [],
            "emails": [],
            "contact_forms": [],
            "named_contacts": [],
        },
        "why_selected": "Insufficient evidence; requires verification.",
        "source_urls": [],
        "note_on_context_only_sources": "GA SOS and Google Places are context only.",
    }

    response["meta"] = {
        "model_notes": "Fallback response generated without GPT due to missing data.",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    return response


def run_research(
    settings: Settings,
    business_name: str,
    state: str,
    holder_name_on_record: str | None,
    last_activity_date: str | None,
    property_report_year: int | None,
    city: str | None,
    ownerrelation: str | None,
    propertytypedescription: str | None,
    holder_known_address: dict[str, Any] | None,
    ga_sos_record: dict[str, Any] | None,
    sos_search_names_tried: list[str],
    sos_matched_name: str | None,
    web_pages: list[dict[str, Any]],
    google_places_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not settings.openai_api_key:
        return None

    system_prompt, response_schema = _load_prompt_and_schema()
    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout)

    user_payload = {
        "owner_name_input": business_name,
        "business": {
            "business_name": business_name,
            "property_state": state,
            "last_activity_date": last_activity_date,
            "property_report_year": property_report_year,
        },
        "holder_name_on_record": holder_name_on_record,
        "city": city,
        "ownerrelation": ownerrelation,
        "propertytypedescription": propertytypedescription,
        "holder_known_address": holder_known_address,
        "ga_sos_records": [ga_sos_record] if ga_sos_record else [],
        "sos_search_names_tried": sos_search_names_tried,
        "sos_matched_name": sos_matched_name,
        "web_pages": web_pages,
        "google_places_profile": google_places_profile,
    }

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.get("name", "entitled_entity_response_v12"),
                    "schema": response_schema,
                    "strict": True,
                },
            },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as exc:
        logger.warning("LLM research failed: %s", exc)
        return None
