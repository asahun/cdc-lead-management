"""SOS (Secretary of State) database service for business entity lookups."""

import re
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.exceptions import SOSDataError

logger = logging.getLogger(__name__)


class SOSService:
    """Service for querying Georgia Secretary of State business records."""
    
    def __init__(self, db: Session):
        """
        Initialize SOS service with database session.
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def normalize_business_name_for_search(self, business_name: str) -> str:
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
    
    def normalize_business_name(self, name: str) -> str:
        """
        Normalize business name for formatting only (lowercase, trim, collapse whitespace, remove punctuation).
        Does NOT remove business identifiers like LLC, Inc, Corp.
        
        Examples:
            "  Earthlink, LLC.  " -> "earthlink llc"
            "ABC   Corp" -> "abc corp"
            "XYZ, Inc." -> "xyz inc"
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
    
    def normalize_business_name_without_suffixes(self, name: str) -> str:
        """
        Normalize property owner name (removes suffixes).
        Delegates to property_service since this is for property owner names.
        """
        from services.property_service import normalize_property_owner_name
        return normalize_property_owner_name(name)
    
    def reorder_first_token_to_end(self, normalized: str) -> str:
        """
        Reorder tokens: move first token to end.
        Delegates to property_service since this is for property owner names.
        """
        from services.property_service import reorder_first_token_to_end
        return reorder_first_token_to_end(normalized)
    
    def search_by_normalized_name(self, normalized_name: str) -> List[Dict[str, Any]]:
        """
        Low-level SOS database search by normalized name.
        Performs the actual SQL query and returns records.
        
        Args:
            normalized_name: Already normalized business name (no business identifiers removed)
            
        Returns:
            List of business record dictionaries, or empty list if none found
            
        Raises:
            SOSDataError: If database query fails
        """
        if not normalized_name:
            return []
        
        import json
        
        # Build the SQL query with parameterized search
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
                        'foreign_state', b.foreign_state,
                        'foreign_country', b.foreign_country,
                        'foreign_date_of_organization', b.foreign_date_of_organization,
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
        logger.debug(f"search_by_normalized_name: Executing SQL query with search_pattern='{search_pattern}'")
        
        try:
            result = self.db.execute(sql_query, {"search_pattern": search_pattern})
            row = result.fetchone()
            
            if not row or not row[0]:
                logger.debug(f"search_by_normalized_name: No results for '{normalized_name}'")
                return []
            
            # row[0] contains the JSON array from json_agg
            sos_records = row[0]
            
            # If it's already a list, return it; otherwise parse JSON string
            if isinstance(sos_records, list):
                logger.debug(f"search_by_normalized_name: Found {len(sos_records)} SOS records for '{normalized_name}'")
                return sos_records
            elif isinstance(sos_records, str):
                parsed = json.loads(sos_records)
                logger.debug(f"search_by_normalized_name: Parsed JSON string, found {len(parsed) if isinstance(parsed, list) else 1} SOS records")
                return parsed if isinstance(parsed, list) else [parsed]
            else:
                if isinstance(sos_records, list):
                    logger.debug(f"search_by_normalized_name: Found {len(sos_records)} SOS records (from dict/object)")
                    return sos_records
                else:
                    logger.warning(f"search_by_normalized_name: Unexpected result type {type(sos_records)}, returning empty list")
                    return []
                
        except Exception as e:
            logger.error(f"search_by_normalized_name: Exception occurred: {e}", exc_info=True)
            raise SOSDataError(f"Failed to retrieve SOS records for '{normalized_name}': {e}") from e
    
    def find_records_with_fallbacks(self, owner_name_input: str) -> Dict[str, Any]:
        """
        Find GA SOS records using ordered fallback flow:
        1. Original normalized
        2. Reordered (first token to end)
        
        Note: GPT name-rescue has been removed per user request.
        
        Args:
            owner_name_input: Original owner/business name from property record
            
        Returns:
            Dictionary with:
            - sos_records: List of SOS records (may be empty)
            - sos_search_names_tried: List of normalized names tried
            - sos_match_found: Boolean indicating if match was found
            - sos_matched_name: String of the name that matched, or None
        """
        result = {
            "sos_records": [],
            "sos_search_names_tried": [],
            "sos_match_found": False,
            "sos_matched_name": None,
        }
        
        if not owner_name_input or not owner_name_input.strip():
            logger.debug("find_records_with_fallbacks: Empty owner_name_input")
            return result
        
        # Step 1: Original normalized
        q0 = self.normalize_business_name(owner_name_input)
        if not q0:
            logger.debug("find_records_with_fallbacks: Normalized name is empty")
            return result
        
        try:
            records0 = self.search_by_normalized_name(q0)
            result["sos_search_names_tried"].append(q0)
            
            if records0:
                logger.info(f"find_records_with_fallbacks: Match found on q0 (original normalized): '{q0}'")
                result["sos_records"] = records0
                result["sos_match_found"] = True
                result["sos_matched_name"] = q0
                return result
        except SOSDataError as e:
            logger.warning(f"find_records_with_fallbacks: SOS search failed for q0 '{q0}': {e}")
            # Continue to next step
        
        # Step 2: Reordered (first token to end)
        q1 = self.reorder_first_token_to_end(q0)
        if q1 != q0:
            try:
                records1 = self.search_by_normalized_name(q1)
                result["sos_search_names_tried"].append(q1)
                
                if records1:
                    logger.info(f"find_records_with_fallbacks: Match found on q1 (reordered): '{q1}'")
                    result["sos_records"] = records1
                    result["sos_match_found"] = True
                    result["sos_matched_name"] = q1
                    return result
            except SOSDataError as e:
                logger.warning(f"find_records_with_fallbacks: SOS search failed for q1 '{q1}': {e}")
                # Continue
        
        logger.info(f"find_records_with_fallbacks: No match found after trying {len(result['sos_search_names_tried'])} names")
        
        # No match found
        return result
    
    def redact_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a redacted copy of an SOS record for GPT (remove registered_agent and officers).
        """
        if not record:
            return {}
        redacted = dict(record)
        redacted.pop("registered_agent", None)
        redacted.pop("officers", None)
        return redacted
    
    def select_best_name_for_web_search(
        self,
        owner_name_input: str,
        sos_result: Dict[str, Any],
    ) -> str:
        """
        Select the best business name for web scraping and Places lookup.
        
        Priority:
        1. If SOS match found: use the legal name from the matched SOS record
        2. Else: use original owner_name_input
        
        Args:
            owner_name_input: Original owner/business name from property record
            sos_result: Result dict from find_records_with_fallbacks()
            
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
                    logger.info(f"select_best_name_for_web_search: Using SOS record business_name: '{best_name}' (not search query)")
                    return best_name
        
        # Priority 2: Fallback to original
        logger.info(f"select_best_name_for_web_search: Using original owner name: '{owner_name_input}'")
        return owner_name_input

