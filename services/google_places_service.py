"""Google Places API service for business profile lookups."""

import os
import time
import logging
from typing import Optional, Dict, Any, List

import requests

logger = logging.getLogger(__name__)

# Configuration
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
PLACES_API_TIMEOUT = int(os.getenv("PLACES_API_TIMEOUT", "10"))


class GooglePlacesService:
    """Service for Google Places API lookups."""
    
    def __init__(self):
        """Initialize Google Places service."""
        if not GOOGLE_PLACES_API_KEY:
            logger.warning("GooglePlacesService: GOOGLE_PLACES_API_KEY not set")
    
    def get_places_profile(self, business_name: str) -> Optional[Dict[str, Any]]:
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
    
    def get_best_business_name_for_places(
        self,
        original_business_name: str,
        sos_records: List[Dict[str, Any]]
    ) -> str:
        """
        Determine the best business name to use for Google Places search.
        
        Priority:
        1. If exactly 1 SOS record exists, use the business_name from that record
        2. Otherwise, use the original business name
        
        Args:
            original_business_name: Original business name from property record
            sos_records: List of SOS records (if any)
            
        Returns:
            Best business name to use for Places search
        """
        # Only use SOS name if exactly 1 record (avoid false assumptions)
        if len(sos_records) == 1:
            sos_name = sos_records[0].get("business_name")
            if sos_name:
                logger.debug(f"get_best_business_name_for_places: Using SOS business_name: '{sos_name}' (original: '{original_business_name}')")
                return sos_name
        
        logger.debug(f"get_best_business_name_for_places: Using original business name: '{original_business_name}'")
        return original_business_name

