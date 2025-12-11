"""
GPT integration helpers for successor research.
"""

import json
import os
from typing import Any, Dict, Iterable

from openai import OpenAI, OpenAIError


SYSTEM_PROMPT = """
You are a legal-entity and successor-analysis assistant for unclaimed property.

TASK:
Given a JSON input describing a business and an unclaimed property
(business_name, property_state, holder_name_on_record, last_activity_date, property_report_year),
you must:

1. Identify the ORIGINAL LEGAL ENTITY that matches the business/property name (if any).
2. Determine if that entity is:
   - active
   - dissolved / withdrawn / inactive
   - merged / converted / acquired into another entity.
3. Build a simple successor description:
   - A single successor_entity object (if there is a clear successor),
   - An optional successor_history array listing parent/owner changes over time.
4. Decide which CURRENT ENTITY has the cleanest legal right to claim the property today.
5. Provide contact info (business site + mailing + physical address) for THAT recommended claimant.

IMPORTANT RULES:
- Always reason in terms of LEGAL ENTITIES, not just brands.
- If there is a statutory merger: prefer the SURVIVING entity in that merger as successor.
- If there is a holding-company reorg: the surviving LLC/corp that stepped into the original’s shoes is the primary successor.
- If the business is still active and unchanged: the original entity is also the successor (relationship_to_original = "same_entity").
- If you cannot identify any plausible successor with reasonable confidence, set:
  - successor_entity.legal_name = null
  - legal_right_for_property.recommended_claimant.entity_name = null
  - confidence = "low"
- Do NOT include any extra commentary or text outside the JSON.
- If you are uncertain about addresses or website, return null for those fields instead of guessing.

OUTPUT FORMAT:
Return ONLY a single JSON object matching EXACTLY this schema (no extra fields, no extra text):

{
  "input": {
    "business_name": string,
    "property_state": string,
    "holder_name_on_record": string | null,
    "last_activity_date": string | null,
    "property_report_year": number | null
  },
  "original_entity": {
    "legal_name": string | null,
    "entity_type": string | null,
    "jurisdiction": string | null,
    "status": string | null,
    "status_detail": string | null
  },
  "successor_entity": {
    "legal_name": string | null,
    "entity_type": string | null,
    "jurisdiction": string | null,
    "status": string | null,
    "relationship_to_original": string | null,
    "effective_date": string | null,
    "confidence": "high" | "medium" | "low"
  },
  "successor_history": [
    {
      "period": string,
      "parent_or_owner": string,
      "note": string
    }
  ],
  "legal_right_for_property": {
    "holder_name_on_record": string | null,
    "as_of_last_activity_date": string | null,
    "recommended_claimant": {
      "entity_name": string | null,
      "reason": string,
      "confidence": "high" | "medium" | "low",
      "business_site": string | null,
      "mailing_address": {
        "addressee": string | null,
        "line1": string | null,
        "line2": string | null,
        "city": string | null,
        "state": string | null,
        "postal_code": string | null,
        "country": string | null
      },
      "physical_address": {
        "addressee": string | null,
        "line1": string | null,
        "line2": string | null,
        "city": string | null,
        "state": string | null,
        "postal_code": string | null,
        "country": string | null
      }
    }
  }
}
"""

RESPONSE_SCHEMA_NAME = "successor_finder_response"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "input": {
            "type": "object",
            "properties": {
                "business_name": {"type": "string"},
                "property_state": {"type": "string"},
                "holder_name_on_record": {"type": ["string", "null"]},
                "last_activity_date": {"type": ["string", "null"]},
                "property_report_year": {"type": ["number", "null"]},
            },
            "required": [
                "business_name",
                "property_state",
                "holder_name_on_record",
                "last_activity_date",
                "property_report_year",
            ],
            "additionalProperties": False,
        },
        "original_entity": {
            "type": "object",
            "properties": {
                "legal_name": {"type": ["string", "null"]},
                "entity_type": {"type": ["string", "null"]},
                "jurisdiction": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"]},
                "status_detail": {"type": ["string", "null"]},
            },
            "required": [
                "legal_name",
                "entity_type",
                "jurisdiction",
                "status",
                "status_detail",
            ],
            "additionalProperties": False,
        },
        "successor_entity": {
            "type": "object",
            "properties": {
                "legal_name": {"type": ["string", "null"]},
                "entity_type": {"type": ["string", "null"]},
                "jurisdiction": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"]},
                "relationship_to_original": {"type": ["string", "null"]},
                "effective_date": {"type": ["string", "null"]},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
            },
            "required": [
                "legal_name",
                "entity_type",
                "jurisdiction",
                "status",
                "relationship_to_original",
                "effective_date",
                "confidence",
            ],
            "additionalProperties": False,
        },
        "successor_history": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "parent_or_owner": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["period", "parent_or_owner", "note"],
                "additionalProperties": False,
            },
        },
        "legal_right_for_property": {
            "type": "object",
            "properties": {
                "holder_name_on_record": {"type": ["string", "null"]},
                "as_of_last_activity_date": {"type": ["string", "null"]},
                "recommended_claimant": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": ["string", "null"]},
                        "reason": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "business_site": {"type": ["string", "null"]},
                        "mailing_address": {
                            "type": "object",
                            "properties": {
                                "addressee": {"type": ["string", "null"]},
                                "line1": {"type": ["string", "null"]},
                                "line2": {"type": ["string", "null"]},
                                "city": {"type": ["string", "null"]},
                                "state": {"type": ["string", "null"]},
                                "postal_code": {"type": ["string", "null"]},
                                "country": {"type": ["string", "null"]},
                            },
                            "required": [
                                "addressee",
                                "line1",
                                "line2",
                                "city",
                                "state",
                                "postal_code",
                                "country",
                            ],
                            "additionalProperties": False,
                        },
                        "physical_address": {
                            "type": "object",
                            "properties": {
                                "addressee": {"type": ["string", "null"]},
                                "line1": {"type": ["string", "null"]},
                                "line2": {"type": ["string", "null"]},
                                "city": {"type": ["string", "null"]},
                                "state": {"type": ["string", "null"]},
                                "postal_code": {"type": ["string", "null"]},
                                "country": {"type": ["string", "null"]},
                            },
                            "required": [
                                "addressee",
                                "line1",
                                "line2",
                                "city",
                                "state",
                                "postal_code",
                                "country",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "entity_name",
                        "reason",
                        "confidence",
                        "business_site",
                        "mailing_address",
                        "physical_address",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "holder_name_on_record",
                "as_of_last_activity_date",
                "recommended_claimant",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "input",
        "original_entity",
        "successor_entity",
        "successor_history",
        "legal_right_for_property",
    ],
    "additionalProperties": False,
}


class GPTConfigError(RuntimeError):
    """Raised when OpenAI credentials are missing or invalid."""


class GPTServiceError(RuntimeError):
    """Raised when the GPT request fails or returns an unexpected payload."""


def _build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise GPTConfigError(
            "OPENAI_API_KEY is not set. Set it in your environment before requesting GPT insights."
        )

    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _iterate_output_text(response) -> Iterable[str]:
    for output_item in getattr(response, "output", []) or []:
        for block in getattr(output_item, "content", []) or []:
            if getattr(block, "type", None) == "output_text" and getattr(block, "text", None):
                yield block.text


def _extract_json_from_response(response) -> Dict[str, Any]:
    for text in _iterate_output_text(response):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise GPTServiceError("GPT returned no structured content.")


def fetch_entity_intelligence(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the GPT model with the provided payload and return the structured response.
    """

    client = _build_client()
    model = os.getenv("GPT_ENTITY_MODEL", "gpt-5.1")
    timeout = int(os.getenv("GPT_ENTITY_TIMEOUT_SECONDS", "45"))

    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": SYSTEM_PROMPT,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": json.dumps(input_payload),
                }
            ],
        },
    ]

    try:
        response = client.responses.parse(
            model=model,
            input=messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": RESPONSE_SCHEMA_NAME,
                    "schema": RESPONSE_SCHEMA,
                    "strict": True,
                }
            },
            timeout=timeout,
        )
    except OpenAIError as exc:
        raise GPTServiceError(f"OpenAI request failed: {exc}") from exc

    parsed = response.output_parsed
    if isinstance(parsed, dict):
        return parsed

    if isinstance(parsed, str):
        try:
            return json.loads(parsed)
        except json.JSONDecodeError:
            pass

    return _extract_json_from_response(response)


__all__ = [
    "fetch_entity_intelligence",
    "GPTConfigError",
    "GPTServiceError",
]
