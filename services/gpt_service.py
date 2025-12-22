import os
import json
import textwrap
import re
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfReader
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False


# ---------- CONFIG ----------

OPENAI_MODEL = os.getenv("GPT_CORP_HISTORY_MODEL", "gpt-5.1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_CUSTOM_SEARCH_API_KEY = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
GOOGLE_CUSTOM_SEARCH_ENGINE_ID = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")  # custom search engine ID (cx)
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

MAX_RESULTS_PER_QUERY = 3
MAX_CONTENT_CHARS_PER_PAGE = 12000  # trim long pages before sending to GPT
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "30"))  # Increased to 30 seconds
PLACES_API_TIMEOUT = int(os.getenv("PLACES_API_TIMEOUT", "10"))  # Timeout for Places API calls


# ---------- EXCEPTIONS ----------
# Import exceptions from centralized location for backward compatibility
from services.exceptions import (
    GPTConfigError,
    GPTServiceError,
    GoogleSearchError,
    SOSDataError,
)


# ---------- GPT PROMPT & SCHEMA ----------

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
        # Pick the first non-null type, or null if that's the only option
        non_null_types = [t for t in type_value if t != "null"]
        if non_null_types:
            type_value = non_null_types[0]
        else:
            type_value = "null"
    
    # Handle enum - pick first value
    if "enum" in schema_def:
        enum_values = schema_def["enum"]
        # Filter out null if we want a non-null default
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
        items_schema = schema_def.get("items", {})
        # For arrays, return empty list
        return []
    elif type_value == "object":
        # For objects, recursively build from properties
        properties = schema_def.get("properties", {})
        result = {}
        for prop_name, prop_schema in properties.items():
            result[prop_name] = _generate_default_from_schema(prop_schema)
        return result
    elif type_value == "null":
        return None
    else:
        # Unknown type, default to None
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


def build_no_web_presence_response(
    business_name: str,
    property_state: str,
    sos_records: List[Dict[str, Any]],
    sos_search_names_tried: List[str],
    google_places_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for EntityIntelligenceService.build_no_web_presence_response.
    """
    from services.entity_intelligence_service import EntityIntelligenceService
    ai_service = EntityIntelligenceService()
    return ai_service.build_no_web_presence_response(
        business_name=business_name,
        property_state=property_state,
        sos_records=sos_records,
        sos_search_names_tried=sos_search_names_tried,
        google_places_profile=google_places_profile,
    )


def _load_gpt_prompt_and_schema():
    """Load GPT system prompt and response schema from files.
    
    Files are loaded once at module import time and cached in module-level constants.
    This ensures no performance impact - files are read only once when the module is imported.
    """
    # Get the directory containing this file (services/)
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


# ---------- SOS DATABASE HELPERS ----------

def normalize_business_name_for_search(business_name: str) -> str:
    """
    Strip common business identifiers (Corp, LLC, Inc, etc.) from business name
    for database search. Returns the base name that will be used with LIKE '%name%'.
    
    Examples:
        "Earthlink, LLC" -> "earthlink"
        "EARTHLINK, INC." -> "earthlink"
        "ABC Corp" -> "abc"
    """
    if not business_name:
        logger.debug("normalize_business_name_for_search: Empty business name")
        return ""
    
    # Common business identifiers to remove (case-insensitive)
    identifiers = [
        r'\b(inc|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b',
        r'[,\.]',  # Remove commas and periods
    ]
    
    # Start with the original name, lowercased
    normalized = business_name.lower().strip()
    logger.debug(f"normalize_business_name_for_search: Original='{business_name}', Lowercased='{normalized}'")
    
    # Remove identifiers
    for pattern in identifiers:
        before = normalized
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
        if before != normalized:
            logger.debug(f"normalize_business_name_for_search: After pattern '{pattern}': '{normalized}'")
    
    # Clean up extra whitespace
    normalized = ' '.join(normalized.split())
    logger.debug(f"normalize_business_name_for_search: Final normalized='{normalized}'")
    
    return normalized


def normalize_business_name(name: str) -> str:
    """
    Normalize business name for formatting only (lowercase, trim, collapse whitespace, remove punctuation).
    Does NOT remove business identifiers like LLC, Inc, Corp.
    
    Examples:
        "  Earthlink, LLC.  " -> "earthlink llc"
        "ABC   Corp" -> "abc corp"
        "XYZ, Inc." -> "xyz inc"
    
    Args:
        name: Business name to normalize
        
    Returns:
        Normalized name string
    """
    if not name:
        return ""
    
    # Lowercase and trim
    normalized = name.lower().strip()
    
    # Remove punctuation (commas, periods, etc.)
    normalized = re.sub(r'[,\.;:!?]', '', normalized)
    
    # Collapse whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized


# ---------- BACKWARD COMPATIBILITY WRAPPERS ----------

def normalize_business_name_without_suffixes(name: str) -> str:
    """
    Backward-compatible wrapper for SOSService.normalize_business_name_without_suffixes.
    """
    from services.sos_service import SOSService
    from sqlalchemy.orm import Session
    # Create a temporary service instance with a dummy db (no db needed for this function)
    # We'll use a minimal implementation that doesn't require db
    if not name:
        return ""
    normalized = name.lower().strip()
    normalized = re.sub(r'[,\.;:!?]', '', normalized)
    normalized = re.sub(
        r'\b(inc|incorporated|corp|corporation|llc|l\.l\.c\.|ltd|limited|co|company|lp|l\.p\.|llp|l\.l\.p\.)\b',
        '',
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = ' '.join(normalized.split())
    return normalized


def redact_sos_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for SOSService.redact_record.
    """
    from services.sos_service import SOSService
    from sqlalchemy.orm import Session
    # Create a temporary service instance (no db needed for this function)
    # Use a dummy None db since redact_record doesn't use db
    class DummyDB:
        pass
    sos_service = SOSService(DummyDB())
    return sos_service.redact_record(record) if record else {}


def reorder_first_token_to_end(normalized: str) -> str:
    """
    Backward-compatible wrapper for SOSService.reorder_first_token_to_end.
    """
    from services.sos_service import SOSService
    # Create a temporary service instance (no db needed for this function)
    class DummyDB:
        pass
    sos_service = SOSService(DummyDB())
    return sos_service.reorder_first_token_to_end(normalized)


def _sos_search_by_normalized_name(
    db: Session,
    normalized_name: str,
) -> List[Dict[str, Any]]:
    """
    Backward-compatible wrapper for SOSService.search_by_normalized_name.
    """
    from services.sos_service import SOSService
    sos_service = SOSService(db)
    return sos_service.search_by_normalized_name(normalized_name)


def find_ga_sos_records_with_fallbacks(
    db: Session,
    owner_name_input: str,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for SOSService.find_records_with_fallbacks.
    
    Note: GPT name-rescue has been removed per user request.
    """
    from services.sos_service import SOSService
    sos_service = SOSService(db)
    return sos_service.find_records_with_fallbacks(owner_name_input)


def _select_best_name_for_web_search(
    owner_name_input: str,
    sos_result: Dict[str, Any],
) -> str:
    """
    Select the best business name for web scraping and Places lookup.
    
    Priority:
    1. If SOS match found: use the legal name from the matched SOS record
    2. Else if GPT rescue provided names: use first GPT-provided alternate name
    3. Else: use original owner_name_input
    
    Args:
        owner_name_input: Original owner/business name from property record
        sos_result: Result dict from find_ga_sos_records_with_fallbacks()
        
    Returns:
        Best business name to use for web search
    """
    # Priority 1: SOS matched - use the actual business_name field from the chosen SOS record
    if sos_result.get("sos_match_found") and sos_result.get("sos_records"):
        sos_records = sos_result["sos_records"]
        if sos_records and len(sos_records) > 0:
            # Use the actual business_name field from the SOS record (not the search query string)
            best_name = sos_records[0].get("business_name")
            if best_name:
                logger.info(f"_select_best_name_for_web_search: Using SOS record business_name: '{best_name}' (not search query)")
                return best_name
    
    # Priority 2: GPT rescue provided names - use first one
    gpt_rescue_names = sos_result.get("gpt_rescue_names", [])
    if gpt_rescue_names and len(gpt_rescue_names) > 0:
        best_name = gpt_rescue_names[0]
        logger.info(f"_select_best_name_for_web_search: Using first GPT rescue name: '{best_name}'")
        return best_name
    
    # Priority 3: Fallback to original
    logger.info(f"_select_best_name_for_web_search: Using original owner name: '{owner_name_input}'")
    return owner_name_input


def fetch_sos_records_for_business(
    db: Session,
    business_name: str,
) -> List[Dict[str, Any]]:
    """
    Retrieve Georgia SOS (Secretary of State) business records from the database
    for a given business name.
    
    Strips common business identifiers (Corp, LLC, Inc, etc.) and searches for
    businesses that start with the normalized name.
    
    Args:
        db: SQLAlchemy database session
        business_name: Business name to search for (e.g., "Earthlink, LLC")
    
    Returns:
        List of business record dictionaries, each containing:
        - business_id, control_number, business_name, business_type_desc
        - commencement_date, effective_date, end_date
        - entity_status, entity_status_date
        - addresses[] (array of address objects)
        - filing_history[] (array of filing objects, ordered by filed_date DESC)
        - officers[] (array of officer objects, deduplicated)
        - stock[] (array of stock objects)
        - registered_agent (object or null)
    
    Raises:
        SOSDataError: If database query fails
    """
    if not business_name:
        return []
    
    # Normalize the business name (strip identifiers)
    normalized_name = normalize_business_name_for_search(business_name)
    logger.debug(f"fetch_sos_records_for_business: business_name='{business_name}', normalized='{normalized_name}'")
    
    if not normalized_name:
        logger.debug("fetch_sos_records_for_business: Normalized name is empty, returning empty list")
        return []
    
    # Build the SQL query with parameterized search
    # Using LIKE with % to match names that start with the normalized name
    sql_query = text("""
        SELECT json_agg(business_data) as result
        FROM (
            SELECT 
                json_build_object(
                    'business_id', b.business_id,
                    'control_number', b.control_number,
                    'business_name', b.business_name,
                    'business_type_desc', b.business_type_desc,
                    'commencement_date', b.commencement_date,
                    'effective_date', b.effective_date,
                    'is_perpetual', b.is_perpetual,
                    'end_date', b.end_date,
                    'entity_status', b.entity_status,
                    'entity_status_date', b.entity_status_date,
                    'phone_number', b.phone_number,
                    'email_address', b.email_address,
                    'naicscode', b.naicscode,
                    'naics_sub_code', b.naics_sub_code,
                    'good_standing', b.good_standing,
                    'addresses', (
                        SELECT COALESCE(json_agg(row_to_json(a.*)), '[]'::json)
                        FROM biz_entity_address a
                        WHERE a.business_id = b.business_id
                    ),
                    'filing_history', (
                        SELECT COALESCE(json_agg(row_to_json(f.*) ORDER BY f.filed_date DESC), '[]'::json)
                        FROM biz_entity_filing_history f
                        WHERE f.business_id = b.business_id
                    ),
                    'officers', (
                        SELECT COALESCE(json_agg(
                            json_build_object(
                                'control_number', control_number,
                                'description', description,
                                'first_name', first_name,
                                'middle_name', middle_name,
                                'last_name', last_name,
                                'company_name', company_name,
                                'line1', line1,
                                'line2', line2,
                                'city', city,
                                'state', state,
                                'zip', zip,
                                'business_id', business_id
                            )
                        ), '[]'::json)
                        FROM (
                            SELECT DISTINCT ON (
                                COALESCE(control_number, ''),
                                COALESCE(description, ''),
                                COALESCE(first_name, ''),
                                COALESCE(middle_name, ''),
                                COALESCE(last_name, ''),
                                COALESCE(company_name, ''),
                                COALESCE(line1, ''),
                                COALESCE(line2, ''),
                                COALESCE(city, ''),
                                COALESCE(state, ''),
                                COALESCE(zip, ''),
                                business_id
                            )
                            control_number, description, first_name, middle_name, last_name,
                            company_name, line1, line2, city, state, zip, business_id
                            FROM biz_entity_officers
                            WHERE business_id = b.business_id
                            ORDER BY 
                                COALESCE(control_number, ''),
                                COALESCE(description, ''),
                                COALESCE(first_name, ''),
                                COALESCE(middle_name, ''),
                                COALESCE(last_name, ''),
                                COALESCE(company_name, ''),
                                COALESCE(line1, ''),
                                COALESCE(line2, ''),
                                COALESCE(city, ''),
                                COALESCE(state, ''),
                                COALESCE(zip, ''),
                                business_id
                        ) o
                    ),
                    'stock', (
                        SELECT COALESCE(json_agg(row_to_json(s.*)), '[]'::json)
                        FROM biz_entity_stock s
                        WHERE s.business_id = b.business_id
                    ),
                    'registered_agent', (
                        SELECT row_to_json(ra.*)
                        FROM biz_entity_registered_agents ra
                        WHERE ra.registered_agent_id = b.registered_agent_id
                    )
                ) as business_data
            FROM biz_entity b
            WHERE LOWER(b.business_name) LIKE LOWER(:search_pattern)
            ORDER BY b.business_name
        ) sub;
    """)
    
    # Build search pattern: normalized_name + '%' for LIKE matching
    search_pattern = f"{normalized_name}%"
    logger.debug(f"fetch_sos_records_for_business: Executing SQL query with search_pattern='{search_pattern}'")
    
    try:
        result = db.execute(sql_query, {"search_pattern": search_pattern})
        row = result.fetchone()
        logger.debug(f"fetch_sos_records_for_business: Query executed, row fetched: {row is not None}")
        
        if not row or not row[0]:
            logger.debug("fetch_sos_records_for_business: No results from query, returning empty list")
            return []
        
        # row[0] contains the JSON array from json_agg
        sos_records = row[0]
        logger.debug(f"fetch_sos_records_for_business: Raw result type: {type(sos_records)}, value preview: {str(sos_records)[:200] if sos_records else 'None'}")
        
        # If it's already a list, return it; otherwise parse JSON string
        if isinstance(sos_records, list):
            logger.info(f"fetch_sos_records_for_business: Found {len(sos_records)} SOS records for '{business_name}'")
            return sos_records
        elif isinstance(sos_records, str):
            parsed = json.loads(sos_records)
            logger.info(f"fetch_sos_records_for_business: Parsed JSON string, found {len(parsed) if isinstance(parsed, list) else 1} SOS records")
            return parsed
        else:
            # Should be a dict/object already parsed by psycopg2
            if isinstance(sos_records, list):
                logger.info(f"fetch_sos_records_for_business: Found {len(sos_records)} SOS records (from dict/object)")
                return sos_records
            else:
                logger.warning(f"fetch_sos_records_for_business: Unexpected result type {type(sos_records)}, returning empty list")
                return []
            
    except Exception as e:
        logger.error(f"fetch_sos_records_for_business: Exception occurred: {e}", exc_info=True)
        raise SOSDataError(f"Failed to retrieve SOS records for '{business_name}': {e}") from e


# ---------- OLD IMPLEMENTATION (DEPRECATED) ----------
# The following functions are part of the old implementation that has been replaced
# by EntityIntelligenceOrchestrator and the new service classes.
# They are kept for reference only and should not be used.

def google_search(query: str, num: int = MAX_RESULTS_PER_QUERY) -> List[Dict[str, Any]]:
    """DEPRECATED: Use GoogleSearchService.search() instead."""
    params = {
        "key": GOOGLE_CUSTOM_SEARCH_API_KEY,
        "cx": GOOGLE_CUSTOM_SEARCH_ENGINE_ID,
        "q": query,
        "num": num,
    }
    resp = requests.get("https://customsearch.googleapis.com/customsearch/v1", params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("items", [])


def scrape_url(url: str) -> str:
    """DEPRECATED: Use GoogleSearchService.scrape_url() instead."""
    try:
        # Check if it's a PDF first
        is_pdf = url.lower().endswith('.pdf') or '/pdf' in url.lower()
        
        r = requests.get(url, timeout=SCRAPE_TIMEOUT, stream=True)
        r.raise_for_status()
        
        # Check content-type
        content_type = r.headers.get('content-type', '').lower()
        is_pdf_content = 'application/pdf' in content_type
        
        # Handle PDF files
        if is_pdf or is_pdf_content:
            if not PDF_EXTRACTION_AVAILABLE:
                raise GoogleSearchError(f"PDF extraction not available, skipping: {url}")
            
            try:
                # Read PDF content
                pdf_bytes = BytesIO(r.content)
                reader = PdfReader(pdf_bytes)
                
                # Extract text from all pages
                text_parts = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                
                text = "\n".join(text_parts)
                text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
                
                if not text or len(text.strip()) < 50:  # Too little text extracted
                    raise GoogleSearchError(f"PDF contained too little extractable text: {url}")
                
                if len(text) > MAX_CONTENT_CHARS_PER_PAGE:
                    text = text[:MAX_CONTENT_CHARS_PER_PAGE]
                
                return text
            except Exception as e:
                raise GoogleSearchError(f"Failed to extract text from PDF {url}: {e}") from e
        
        # Handle HTML content
        soup = BeautifulSoup(r.text, "html.parser")
        # Remove script/style
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) > MAX_CONTENT_CHARS_PER_PAGE:
            text = text[:MAX_CONTENT_CHARS_PER_PAGE]
        return text
        
    except requests.HTTPError as e:
        # Check for 403 Forbidden specifically
        if e.response and e.response.status_code == 403:
            raise GoogleSearchError(f"Forbidden (403), skipping: {url}")
        raise GoogleSearchError(f"Failed to scrape {url}: {e}") from e
    except requests.RequestException as e:
        # Check for 403 in the exception message as fallback
        error_str = str(e).lower()
        if "403" in error_str or "forbidden" in error_str:
            raise GoogleSearchError(f"Forbidden (403), skipping: {url}")
        raise GoogleSearchError(f"Failed to scrape {url}: {e}") from e
    except Exception as e:
        raise GoogleSearchError(f"Unexpected error scraping {url}: {e}") from e


# ---------- PIPELINE ----------

# DEPRECATED: Old query builders - replaced by CSEQuerySelector
# These functions are no longer used. The JSON file has been removed.
# Use CSEQuerySelector and GoogleSearchService instead.

def build_official_identity_query(business_name: str, state_full: str = None) -> str:
    """DEPRECATED: Use CSEQuerySelector instead."""
    raise NotImplementedError("This function is deprecated. Use CSEQuerySelector instead.")


def build_hq_contact_query(business_name: str, state_full: str) -> str:
    """DEPRECATED: Use CSEQuerySelector instead."""
    raise NotImplementedError("This function is deprecated. Use CSEQuerySelector instead.")


def build_successor_query(business_name: str, state_full: str) -> str:
    """DEPRECATED: Use CSEQuerySelector instead."""
    raise NotImplementedError("This function is deprecated. Use CSEQuerySelector instead.")


def build_ga_local_query(business_name: str, city: str, state_full: str) -> str:
    """DEPRECATED: Use CSEQuerySelector instead."""
    raise NotImplementedError("This function is deprecated. Use CSEQuerySelector instead.")


def collect_pages_for_business(
    business_name: str,
    property_state: str,
) -> List[Dict[str, Any]]:
    # You can map state code to full name yourself; for now assume property_state is full.
    state_full = property_state

    pages = []
    min_results_required = 1  # Lower threshold since we have more queries now

    def scrape_and_add_results(query_results, query_id_prefix, query_type="web", required=True):
        """Helper to scrape results and add to pages list"""
        successful = 0
        for idx, item in enumerate(query_results, start=1):
            url = item.get("link")
            title = item.get("title") or ""
            if not url:
                continue
        
            try:
                content = scrape_url(url)
                pages.append({
                    "id": f"{query_id_prefix}_{idx}",
                    "url": url,
                    "title": title,
                    "type": query_type,
                    "content": content,
                })
                successful += 1
            except GoogleSearchError as e:
                # If it's a PDF skip error or forbidden error, log and continue to next result
                error_msg = str(e).lower()
                if "pdf" in error_msg or "skipping" in error_msg or "forbidden" in error_msg or "403" in error_msg:
                    print(f"Skipping: {url} - {e}")
                    continue
                # For other errors, re-raise if we don't have enough results yet and it's required
                if required and successful < min_results_required:
                    raise
            except Exception as e:
                # For unexpected errors, re-raise if we don't have enough results yet and it's required
                if required and successful < min_results_required:
                    raise GoogleSearchError(f"Failed to scrape {query_id_prefix} URL {url}: {e}") from e
        
        if required and successful < min_results_required:
            raise GoogleSearchError(f"Not enough successful {query_id_prefix} results (got {successful}, need {min_results_required})")
        
        return successful

    # Query 1a: Official identity with state
    try:
        query1a = build_official_identity_query(business_name, state_full)
        results1a = google_search(query1a)
        if results1a:
            scrape_and_add_results(results1a, "identity_with_state", "web", required=True)
    except requests.RequestException as e:
        logger.warning(f"Official identity query (with state) failed: {e}")
    except GoogleSearchError as e:
        logger.warning(f"Official identity query (with state) had issues: {e}")

    # Query 1b: Official identity without state (recommended tweak)
    try:
        query1b = build_official_identity_query(business_name)
        results1b = google_search(query1b)
        if results1b:
            scrape_and_add_results(results1b, "identity_no_state", "web", required=False)
    except requests.RequestException as e:
        logger.warning(f"Official identity query (no state) failed: {e}")
    except GoogleSearchError as e:
        logger.warning(f"Official identity query (no state) had issues: {e}")

    # Query 2: HQ / corporate contact
    try:
        query2 = build_hq_contact_query(business_name, state_full)
        results2 = google_search(query2)
        if results2:
            scrape_and_add_results(results2, "hq_contact", "web", required=True)
    except requests.RequestException as e:
        raise GoogleSearchError(f"HQ contact search failed: {e}") from e
    except GoogleSearchError as e:
        raise

    # Query 3: Successor / rename / acquisition
    try:
        query3 = build_successor_query(business_name, state_full)
        results3 = google_search(query3)
        if results3:
            # Classify results
            for idx, item in enumerate(results3, start=1):
                url = item.get("link")
                title = item.get("title") or ""
                if not url:
                    continue
                
                lower_title = title.lower()
                if any(keyword in lower_title for keyword in ["secretary of state", "corporation division", "business search", "corp search", "business entity"]):
                    kind = "sos_like"
                elif any(keyword in lower_title for keyword in ["opencorporates", "company register", "registry"]):
                    kind = "registry"
                else:
                    kind = "news"

                try:
                    content = scrape_url(url)
                    pages.append({
                        "id": f"successor_{idx}",
                        "url": url,
                        "title": title,
                        "type": kind,
                        "content": content,
                    })
                except GoogleSearchError as e:
                    error_msg = str(e).lower()
                    if "pdf" in error_msg or "skipping" in error_msg or "forbidden" in error_msg or "403" in error_msg:
                        print(f"Skipping: {url} - {e}")
                        continue
    except requests.RequestException as e:
        logger.warning(f"Successor query failed: {e}")
    except GoogleSearchError as e:
        logger.warning(f"Successor query had issues: {e}")

    # Query 4: GA local footprint (optional - only when needed)
    # For now, we'll skip this as it requires city information which we may not have
    # This can be added later when we have city data from addresses or other sources
    # try:
    #     if city:  # Would need city parameter
    #         query4 = build_ga_local_query(business_name, city, state_full)
    #         results4 = google_search(query4)
    #         if results4:
    #             scrape_and_add_results(results4, "ga_local", "web", required=False)
    # except Exception as e:
    #     logger.warning(f"GA local query failed: {e}")

    if len(pages) == 0:
        raise GoogleSearchError(f"No pages collected from any query for {business_name}")

    return pages


def get_places_profile(business_name: str) -> Optional[Dict[str, Any]]:
    """
    Get Google Places profile for a business using Places API (New).
    
    Uses Text Search to find a place, then Place Details to get full information.
    Returns normalized object with place_id, display_name, formatted_address,
    business_status, national_phone, website_uri, or None if not found.
    
    Handles timeouts and 429 rate limits with exponential backoff (max 3 retries).
    
    Args:
        business_name: Business name to search for
        
    Returns:
        Dictionary with normalized place data, or None if not found
    """
    if not GOOGLE_PLACES_API_KEY:
        logger.debug("get_places_profile: GOOGLE_PLACES_API_KEY not set, skipping Places API lookup")
        return None
    
    if not business_name or not business_name.strip():
        logger.debug("get_places_profile: Empty business name, skipping")
        return None
    
    text_search_url = "https://places.googleapis.com/v1/places:searchText"
    place_details_base_url = "https://places.googleapis.com/v1/places"
    
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
    }
    
    # Step 1: Text Search
    text_search_payload = {
        "textQuery": business_name.strip(),
        "pageSize": 1
    }
    
    text_search_headers = {
        **headers,
        "X-Goog-FieldMask": "places.id"
    }
    
    place_id = None
    max_retries = 3
    retry_delay = 1  # Start with 1 second
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"get_places_profile: Text search attempt {attempt + 1} for '{business_name}'")
            response = requests.post(
                text_search_url,
                headers=text_search_headers,
                json=text_search_payload,
                timeout=PLACES_API_TIMEOUT
            )
            
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"get_places_profile: Rate limited (429), retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error("get_places_profile: Rate limited (429) after max retries")
                    return None
            
            response.raise_for_status()
            data = response.json()
            
            places = data.get("places", [])
            if not places:
                logger.debug(f"get_places_profile: No places found for '{business_name}'")
                return None
            
            place_id = places[0].get("id")
            if not place_id:
                logger.debug(f"get_places_profile: Place found but no ID")
                return None
            
            logger.debug(f"get_places_profile: Found place_id: {place_id}")
            break  # Success, exit retry loop
            
        except requests.Timeout:
            logger.warning(f"get_places_profile: Text search timeout for '{business_name}'")
            return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logger.warning(f"get_places_profile: Request error (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"get_places_profile: Text search failed after max retries: {e}")
                return None
    
    if not place_id:
        return None
    
    # Step 2: Place Details
    place_details_url = f"{place_details_base_url}/{place_id}"
    place_details_headers = {
        **headers,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,businessStatus,nationalPhoneNumber,websiteUri"
    }
    
    retry_delay = 1  # Reset for place details
    for attempt in range(max_retries):
        try:
            logger.debug(f"get_places_profile: Place details attempt {attempt + 1} for place_id: {place_id}")
            response = requests.get(
                place_details_url,
                headers=place_details_headers,
                timeout=PLACES_API_TIMEOUT
            )
            
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"get_places_profile: Rate limited (429) on place details, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error("get_places_profile: Rate limited (429) on place details after max retries")
                    return None
            
            response.raise_for_status()
            data = response.json()
            
            # Normalize output
            result = {
                "place_id": data.get("id"),
                "display_name": data.get("displayName", {}).get("text") if isinstance(data.get("displayName"), dict) else data.get("displayName"),
                "formatted_address": data.get("formattedAddress"),
                "business_status": data.get("businessStatus"),
                "national_phone": data.get("nationalPhoneNumber"),
                "website_uri": data.get("websiteUri"),
            }
            
            # Set missing fields to None explicitly
            for key in result:
                if result[key] is None:
                    result[key] = None
            
            logger.debug(f"get_places_profile: Successfully retrieved place details for '{business_name}'")
            return result
            
        except requests.Timeout:
            logger.warning(f"get_places_profile: Place details timeout for place_id: {place_id}")
            return None
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logger.warning(f"get_places_profile: Place details request error (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"get_places_profile: Place details failed after max retries: {e}")
                return None
    
    return None


def _get_best_business_name_for_places(
    original_business_name: str,
    sos_records: List[Dict[str, Any]]
) -> str:
    """
    Determine the best business name to use for Google Places search.
    
    If SOS records exist, find the closest match (normalized comparison).
    If a match is found, use that SOS record's business_name (legal name).
    Otherwise, use the normalized original business_name.
    
    Args:
        original_business_name: Original business name from property record
        sos_records: List of SOS records
        
    Returns:
        Best business name to use for Places search
    """
    if not sos_records:
        # No SOS records, normalize the original name
        normalized = normalize_business_name_for_search(original_business_name)
        return normalized if normalized else original_business_name.strip()
    
    # Normalize the original name for comparison
    original_normalized = normalize_business_name_for_search(original_business_name)
    
    # Find the closest match in SOS records
    best_match = None
    best_score = 0
    
    for record in sos_records:
        sos_name = record.get("business_name", "")
        if not sos_name:
            continue
        
        sos_normalized = normalize_business_name_for_search(sos_name)
        
        # Calculate similarity score (simple: exact match = 100, starts with = 50, contains = 25)
        if sos_normalized == original_normalized:
            # Exact match - use this one
            best_match = sos_name
            break
        elif original_normalized and sos_normalized.startswith(original_normalized):
            # SOS name starts with original (e.g., "earthlink" -> "earthlink llc")
            if not best_match or best_score < 50:
                best_match = sos_name
                best_score = 50
        elif original_normalized and original_normalized in sos_normalized:
            # Original is contained in SOS name
            if not best_match or best_score < 25:
                best_match = sos_name
                best_score = 25
    
    if best_match:
        logger.debug(f"_get_best_business_name_for_places: Using SOS legal name: '{best_match}' (original: '{original_business_name}')")
        return best_match
    
    # No good match found, use normalized original
    normalized = normalize_business_name_for_search(original_business_name)
    result = normalized if normalized else original_business_name.strip()
    logger.debug(f"_get_best_business_name_for_places: Using normalized original: '{result}' (original: '{original_business_name}')")
    return result


def call_gpt_corporate_history(
    business_name: str,
    property_state: str,
    last_activity_date: str | None = None,
    property_report_year: int | None = None,
    db: Optional[Session] = None,
    selected_sos_record: Optional[Dict[str, Any]] = None,
    sos_search_name_used: Optional[str] = None,
    skip_sos_lookup: bool = False,
) -> Dict[str, Any]:
    """
    Backward-compatible wrapper for call_gpt_corporate_history.
    
    This function now delegates to EntityIntelligenceOrchestrator.
    It is kept for backward compatibility with existing code.
    """
    from services.entity_intelligence_orchestrator import EntityIntelligenceOrchestrator
    from services.sos_service import SOSService
    
    # Create orchestrator with SOS service if db is provided
    sos_service = SOSService(db) if db else None
    orchestrator = EntityIntelligenceOrchestrator(sos_service=sos_service)
    
    return orchestrator.analyze_entity(
        business_name=business_name,
        property_state=property_state,
        last_activity_date=last_activity_date,
        property_report_year=property_report_year,
        db=db,
        selected_sos_record=selected_sos_record,
        sos_search_name_used=sos_search_name_used,
        skip_sos_lookup=skip_sos_lookup,
    )


def _call_gpt_corporate_history_old_implementation(
    business_name: str,
    property_state: str,
    last_activity_date: str | None = None,
    property_report_year: int | None = None,
    db: Optional[Session] = None,
    selected_sos_record: Optional[Dict[str, Any]] = None,
    sos_search_name_used: Optional[str] = None,
    skip_sos_lookup: bool = False,
) -> Dict[str, Any]:
    """
    OLD IMPLEMENTATION - kept for reference only.
    This function has been replaced by EntityIntelligenceOrchestrator.
    """
    if not OPENAI_API_KEY:
        raise GPTConfigError("OPENAI_API_KEY not set")
    if not GOOGLE_CUSTOM_SEARCH_API_KEY:
        raise GPTConfigError("GOOGLE_CUSTOM_SEARCH_API_KEY not set")
    if not GOOGLE_CUSTOM_SEARCH_ENGINE_ID:
        raise GPTConfigError("GOOGLE_CUSTOM_SEARCH_ENGINE_ID not set")

    openai_client = OpenAI(api_key=OPENAI_API_KEY)

    # STEP 1: SOS fallback flow (BEFORE web scraping) unless preselected
    sos_records = []
    sos_search_names_tried = []
    sos_matched_name = None
    gpt_rescue_names = []
    if skip_sos_lookup or selected_sos_record is not None:
        if selected_sos_record:
            sos_records = [selected_sos_record]
            sos_matched_name = sos_search_name_used or business_name
            if sos_matched_name:
                sos_search_names_tried = [sos_matched_name]
        else:
            sos_records = []
            sos_search_names_tried = [sos_search_name_used] if sos_search_name_used else []
        sos_result = {
            "sos_records": sos_records,
            "sos_search_names_tried": sos_search_names_tried,
            "sos_match_found": bool(sos_records),
            "sos_matched_name": sos_matched_name,
            "gpt_rescue_names": [],
        }
    elif db:
        logger.debug(f"call_gpt_corporate_history: Database session provided, fetching SOS records with fallbacks for '{business_name}'")
        try:
            sos_result = find_ga_sos_records_with_fallbacks(db, business_name)
            sos_records = sos_result["sos_records"]
            sos_search_names_tried = sos_result["sos_search_names_tried"]
            sos_matched_name = sos_result["sos_matched_name"]
            gpt_rescue_names = sos_result.get("gpt_rescue_names", [])
            
            if sos_result["sos_match_found"]:
                logger.info(f"call_gpt_corporate_history: Successfully found {len(sos_records)} SOS records using fallback flow (matched on: '{sos_matched_name}')")
            else:
                logger.info(f"call_gpt_corporate_history: No SOS records found after trying {len(sos_search_names_tried)} names: {sos_search_names_tried}")
        except (SOSDataError, GPTServiceError) as e:
            # Log but don't fail - continue without SOS records
            logger.warning(f"call_gpt_corporate_history: Could not fetch SOS records: {e}")
            sos_records = []
            sos_result = {
                "sos_records": [],
                "sos_search_names_tried": [],
                "sos_match_found": False,
                "sos_matched_name": None,
                "gpt_rescue_names": [],
            }
    else:
        logger.debug("call_gpt_corporate_history: No database session provided, skipping SOS records")
        sos_result = {
            "sos_records": [],
            "sos_search_names_tried": [],
            "sos_match_found": False,
            "sos_matched_name": None,
            "gpt_rescue_names": [],
        }

    # STEP 2: Select best name for web search
    if sos_result.get("sos_match_found") and sos_records:
        # Use the actual business name from the SOS record, not the search query
        best_name_for_web_search = sos_records[0].get("business_name") or sos_result.get("sos_matched_name") or business_name
    elif gpt_rescue_names:
        best_name_for_web_search = gpt_rescue_names[0]
    else:
        best_name_for_web_search = normalize_business_name_without_suffixes(business_name) or business_name
    logger.info(f"call_gpt_corporate_history: Selected best name for web search: '{best_name_for_web_search}'")

    # STEP 3 & 4: Run web scraping and Google Places in parallel (no dependency between them)
    pages = []
    google_places_profile = None
    
    def fetch_web_pages():
        """Helper to fetch web pages, returns empty list on error instead of raising"""
        try:
            return collect_pages_for_business(best_name_for_web_search, property_state)
        except GoogleSearchError as e:
            logger.info(f"call_gpt_corporate_history: No web pages found for '{best_name_for_web_search}': {e}")
            return []
        except Exception as e:
            logger.warning(f"call_gpt_corporate_history: Web scraping failed: {e}")
            return []
    
    def fetch_places():
        """Helper to fetch Google Places profile"""
        try:
            profile = get_places_profile(best_name_for_web_search)
            if profile:
                logger.info(f"call_gpt_corporate_history: Successfully retrieved Google Places profile")
            else:
                logger.debug(f"call_gpt_corporate_history: No Google Places profile found")
            return profile
        except Exception as e:
            logger.warning(f"call_gpt_corporate_history: Could not fetch Google Places profile: {e}")
            return None
    
    # Run both in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        web_future = executor.submit(fetch_web_pages)
        places_future = executor.submit(fetch_places)
        
        # Wait for both to complete
        pages = web_future.result()
        google_places_profile = places_future.result()
    
    logger.info(f"call_gpt_corporate_history: Web pages: {len(pages)}, Google Places: {'found' if google_places_profile else 'not found'}")

    # STEP 5: Check if we should skip GPT (no web pages means no data to analyze)
    if len(pages) == 0:
        logger.info("call_gpt_corporate_history: No web pages found - skipping GPT call (small local business may not have internet history)")
        
        # Build response using schema-driven defaults
        return build_no_web_presence_response(
            business_name=business_name,
            property_state=property_state,
            sos_records=sos_records,
            sos_search_names_tried=sos_search_names_tried,
            google_places_profile=google_places_profile,
        )

    # STEP 6: Build redacted SOS data for GPT
    redacted_sos_records = []
    if sos_records:
        # Only include one selected record for GPT (redacted)
        redacted_sos_records = [redact_sos_record(sos_records[0])]

    # STEP 7: Main GPT call with assembled payload
    user_payload = {
        "owner_name_input": business_name,  # Original input for trace
        "business": {
            "business_name": business_name,
            "property_state": property_state,
            "last_activity_date": last_activity_date,
            "property_report_year": property_report_year,
        },
        # Provide only redacted SOS data to GPT
        "ga_sos_records": redacted_sos_records,
        "sos_search_names_tried": sos_search_names_tried,  # Always included: array of names tried (empty if no lookup)
        "sos_matched_name": sos_matched_name,  # Always included: which name matched (null if no match)
        "web_pages": [
            {
                "id": p["id"],
                "url": p["url"],
                "title": p["title"],
                "type": p["type"],
                "content": p["content"],
            }
            for p in pages
        ],
        "google_places_profile": google_places_profile,  # Add Google Places profile (or null)
    }
    logger.info(f"call_gpt_corporate_history: Building GPT payload with {len(redacted_sos_records)} redacted SOS records and {len(pages)} web pages")
    logger.debug(f"call_gpt_corporate_history: SOS records preview: {[r.get('business_name', 'N/A') for r in sos_records[:3]] if sos_records else 'None'}")

    try:
        logger.debug(f"call_gpt_corporate_history: Calling GPT API with model={OPENAI_MODEL}")
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            response_format=GPT_RESPONSE_FORMAT,
    messages=[
                {"role": "system", "content": GPT_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        )

        # Extract response content from chat completion format
        raw_text = response.choices[0].message.content
        logger.debug(f"call_gpt_corporate_history: GPT response received, length={len(raw_text)}")
        data = json.loads(raw_text)
        
        # Debug: Log all keys in the response
        response_keys = list(data.keys())
        logger.info(f"call_gpt_corporate_history: GPT response keys: {response_keys}")
        
        # Check for missing required fields (schema-driven - extracts from schema automatically)
        schema_required = GPT_RESPONSE_SCHEMA.get("required", [])
        missing_fields = [f for f in schema_required if f not in data]
        if missing_fields:
            logger.warning(f"call_gpt_corporate_history: Missing required fields: {missing_fields}")
        
        # Log structure of each field (type and whether it's empty) - flexible to schema changes
        field_structure = {}
        for key in schema_required:
            if key in data:
                value = data[key]
                if isinstance(value, dict):
                    field_structure[key] = f"dict with {len(value)} keys: {list(value.keys())}"
                elif isinstance(value, list):
                    field_structure[key] = f"list with {len(value)} items"
                elif value is None:
                    field_structure[key] = "null"
                else:
                    field_structure[key] = f"{type(value).__name__}: {str(value)[:50]}"
            else:
                field_structure[key] = "MISSING"
        
        logger.debug(f"call_gpt_corporate_history: Field structure: {json.dumps(field_structure, indent=2)}")
        
        # Log a sample of key fields (flexible - adapts to schema structure)
        key_fields_to_log = ["hypotheses", "selected_entitled_entity", "query_context"]
        for field in key_fields_to_log:
            if field in data:
                field_data = data[field]
                if isinstance(field_data, dict):
                    logger.debug(f"call_gpt_corporate_history: {field} content: {json.dumps(field_data, indent=2, default=str)[:500]}")
                elif isinstance(field_data, list):
                    logger.debug(f"call_gpt_corporate_history: {field} is list with {len(field_data)} items")
                    if len(field_data) > 0 and isinstance(field_data[0], dict):
                        logger.debug(f"call_gpt_corporate_history: {field}[0] sample: {json.dumps(field_data[0], indent=2, default=str)[:500]}")
                else:
                    logger.debug(f"call_gpt_corporate_history: {field} = {field_data}")
            else:
                logger.debug(f"call_gpt_corporate_history: {field} is MISSING from response")
        
        # Log selected entity for summary (flexible - adapts to schema changes)
        selected_entity_name = "N/A"
        if "selected_entitled_entity" in data:
            selected = data["selected_entitled_entity"]
            selected_entity_name = selected.get("entitled_business_name", "N/A")
        elif "hypotheses" in data and isinstance(data["hypotheses"], list) and len(data["hypotheses"]) > 0:
            # Fallback to first hypothesis if selected_entitled_entity not available
            selected_entity_name = data["hypotheses"][0].get("candidate_entitled_name", "N/A")
        
        logger.info(f"call_gpt_corporate_history: GPT analysis complete - selected_entity={selected_entity_name}")
        return data
    except Exception as e:
        logger.error(f"call_gpt_corporate_history: GPT API call failed: {e}", exc_info=True)
        raise GPTServiceError(f"GPT API call failed: {e}") from e


def fetch_entity_intelligence(
    payload: Dict[str, Any],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Fetch entity intelligence using GPT corporate history analysis.
    
    Backward-compatible wrapper that uses the new EntityIntelligenceOrchestrator.
    
    Args:
        payload: Dictionary with business_name, property_state, last_activity_date, property_report_year, city
        db: Optional database session for fetching SOS records
    
    Returns:
        Dictionary containing the GPT analysis response
    """
    from services.entity_intelligence_orchestrator import EntityIntelligenceOrchestrator
    from services.sos_service import SOSService
    
    business_name = payload.get("business_name", "")
    property_state = payload.get("property_state", "")
    last_activity_date = payload.get("last_activity_date") or None
    property_report_year = payload.get("property_report_year")
    city = payload.get("city")
    
    logger.info(f"fetch_entity_intelligence: Starting analysis for business_name='{business_name}', property_state='{property_state}', city='{city}', db_provided={db is not None}")
    
    # Create orchestrator with SOS service if db is provided
    sos_service = SOSService(db) if db else None
    orchestrator = EntityIntelligenceOrchestrator(sos_service=sos_service)
    
    result = orchestrator.analyze_entity(
        business_name=business_name,
        property_state=property_state,
        last_activity_date=last_activity_date,
        property_report_year=property_report_year,
        db=db,
        selected_sos_record=payload.get("selected_sos_record"),
        sos_search_name_used=payload.get("sos_search_name_used"),
        skip_sos_lookup=payload.get("skip_sos_lookup", False),
        city=city,
    )
    
    logger.debug(f"fetch_entity_intelligence: Analysis complete, response keys: {list(result.keys()) if result else 'None'}")
    return result


if __name__ == "__main__":
    # Simple manual test
    result = call_gpt_corporate_history(
        business_name="EARTHLINK, INC.",
        property_state="Georgia",
        last_activity_date="2013-01-09",
        property_report_year=2015,
    )
    print(json.dumps(result, indent=2))
