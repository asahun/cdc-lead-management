"""Entity Intelligence Orchestrator - coordinates all services for entity analysis."""

import logging
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session

from services.sos_service import SOSService
from services.google_search_service import GoogleSearchService
from services.google_places_service import GooglePlacesService
from services.entity_intelligence_service import EntityIntelligenceService
from services.exceptions import SOSDataError, GoogleSearchError

logger = logging.getLogger(__name__)


class EntityIntelligenceOrchestrator:
    """Orchestrates the full entity intelligence pipeline."""
    
    def __init__(
        self,
        sos_service: Optional[SOSService] = None,
        web_search_service: Optional[GoogleSearchService] = None,
        places_service: Optional[GooglePlacesService] = None,
        ai_service: Optional[EntityIntelligenceService] = None,
    ):
        """
        Initialize orchestrator with service instances.
        
        Args:
            sos_service: SOS service instance (optional, will create if not provided)
            web_search_service: Google Search service instance (optional, will create if not provided)
            places_service: Google Places service instance (optional, will create if not provided)
            ai_service: Entity Intelligence service instance (optional, will create if not provided)
        """
        self.sos_service = sos_service
        self.web_search_service = web_search_service or GoogleSearchService()
        self.places_service = places_service or GooglePlacesService()
        self.ai_service = ai_service or EntityIntelligenceService()
    
    def analyze_entity(
        self,
        business_name: str,
        property_state: str,
        last_activity_date: Optional[str] = None,
        property_report_year: Optional[int] = None,
        db: Optional[Session] = None,
        selected_sos_record: Optional[Dict[str, Any]] = None,
        sos_search_name_used: Optional[str] = None,
        skip_sos_lookup: bool = False,
        city: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Orchestrate the full entity intelligence analysis pipeline.
        
        Flow:
        1. SOS lookup (if not skipped and db provided)
        2. Select best name for web search
        3. Parallel: Web scraping + Google Places lookup
        4. GPT analysis (if web pages found) or no-web-presence response
        
        Args:
            business_name: Original business name
            property_state: State where property is located
            last_activity_date: Last activity date (optional)
            property_report_year: Property report year (optional)
            db: Database session (optional, required for SOS lookup)
            selected_sos_record: Pre-selected SOS record (optional)
            sos_search_name_used: Name used for SOS search (optional)
            skip_sos_lookup: Skip SOS lookup (default: False)
            
        Returns:
            Complete analysis response dictionary
        """
        # STEP 1: SOS lookup (unless skipped or preselected)
        sos_records = []
        sos_search_names_tried = []
        sos_matched_name = None
        
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
            }
        elif db:
            # Initialize SOS service with db if not already initialized
            if self.sos_service is None:
                self.sos_service = SOSService(db)
            elif not hasattr(self.sos_service, 'db') or self.sos_service.db is None:
                # Reinitialize with new db session
                self.sos_service = SOSService(db)
            
            logger.debug(f"analyze_entity: Database session provided, fetching SOS records with fallbacks for '{business_name}'")
            try:
                sos_result = self.sos_service.find_records_with_fallbacks(business_name)
                sos_records = sos_result["sos_records"]
                sos_search_names_tried = sos_result["sos_search_names_tried"]
                sos_matched_name = sos_result["sos_matched_name"]
                
                if sos_result["sos_match_found"]:
                    logger.info(f"analyze_entity: Successfully found {len(sos_records)} SOS records using fallback flow (matched on: '{sos_matched_name}')")
                else:
                    logger.info(f"analyze_entity: No SOS records found after trying {len(sos_search_names_tried)} names: {sos_search_names_tried}")
            except SOSDataError as e:
                logger.warning(f"analyze_entity: Could not fetch SOS records: {e}")
                sos_records = []
                sos_result = {
                    "sos_records": [],
                    "sos_search_names_tried": [],
                    "sos_match_found": False,
                    "sos_matched_name": None,
                }
        else:
            logger.debug("analyze_entity: No database session provided, skipping SOS records")
            sos_result = {
                "sos_records": [],
                "sos_search_names_tried": [],
                "sos_match_found": False,
                "sos_matched_name": None,
            }
        
        # STEP 2: Determine which SOS record to use (only if selected or exactly 1 record)
        sos_record_for_analysis = None
        if selected_sos_record:
            # User explicitly selected a record
            sos_record_for_analysis = selected_sos_record
            logger.debug(f"analyze_entity: Using user-selected SOS record")
        elif len(sos_records) == 1:
            # Only one match - safe to use
            sos_record_for_analysis = sos_records[0]
            logger.debug(f"analyze_entity: Using single SOS record (only one match found)")
        elif len(sos_records) > 1:
            # Multiple records but no selection - don't assume
            logger.warning(f"analyze_entity: Multiple SOS records found ({len(sos_records)}) but none selected - treating as no SOS record")
            sos_record_for_analysis = None
        
        # STEP 3: Select best name for web search
        if sos_record_for_analysis:
            # Use the actual business name from the SOS record
            best_name_for_web_search = sos_record_for_analysis.get("business_name") or sos_result.get("sos_matched_name") or business_name
        else:
            # Use normalized name without suffixes (from property owner name)
            from services.property_service import normalize_property_owner_name
            best_name_for_web_search = normalize_property_owner_name(business_name) or business_name
        
        logger.info(f"analyze_entity: Selected best name for web search: '{best_name_for_web_search}'")
        
        # STEP 3 & 4: Run web scraping and Google Places in parallel
        pages = []
        google_places_profile = None
        
        def fetch_web_pages():
            """Helper to fetch web pages, returns empty list on error instead of raising"""
            try:
                return self.web_search_service.collect_pages_for_business(
                    best_name_for_web_search,
                    property_state,
                    sos_record=sos_record_for_analysis,
                    city=city,
                )
            except GoogleSearchError as e:
                logger.info(f"analyze_entity: No web pages found for '{best_name_for_web_search}': {e}")
                return []
            except Exception as e:
                logger.warning(f"analyze_entity: Web scraping failed: {e}")
                return []
        
        def fetch_places():
            """Helper to fetch Google Places profile"""
            try:
                # Use best name for Places search
                places_name = best_name_for_web_search
                if sos_record_for_analysis:
                    places_name = self.places_service.get_best_business_name_for_places(
                        best_name_for_web_search,
                        [sos_record_for_analysis] if sos_record_for_analysis else []
                    )
                
                profile = self.places_service.get_places_profile(places_name)
                if profile:
                    logger.info(f"analyze_entity: Successfully retrieved Google Places profile")
                else:
                    logger.debug(f"analyze_entity: No Google Places profile found")
                return profile
            except Exception as e:
                logger.warning(f"analyze_entity: Could not fetch Google Places profile: {e}")
                return None
        
        # Run both in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            web_future = executor.submit(fetch_web_pages)
            places_future = executor.submit(fetch_places)
            
            # Wait for both to complete
            pages = web_future.result()
            google_places_profile = places_future.result()
        
        logger.info(f"analyze_entity: Web pages: {len(pages)}, Google Places: {'found' if google_places_profile else 'not found'}")
        
        # STEP 5: Check if we should skip GPT (no web pages means no data to analyze)
        if len(pages) == 0:
            logger.info("analyze_entity: No web pages found - skipping GPT call (small local business may not have internet history)")
            
            # Build response using schema-driven defaults
            # Only include SOS record if we have one selected/single record
            sos_records_for_response = [sos_record_for_analysis] if sos_record_for_analysis else []
            return self.ai_service.build_no_web_presence_response(
                business_name=business_name,
                property_state=property_state,
                sos_records=sos_records_for_response,
                sos_search_names_tried=sos_search_names_tried,
                google_places_profile=google_places_profile,
            )
        
        # STEP 6: Build redacted SOS data for GPT
        redacted_sos_records = []
        if sos_record_for_analysis and self.sos_service:
            # Only include the selected/single record for GPT (redacted)
            redacted_sos_records = [self.sos_service.redact_record(sos_record_for_analysis)]
        
        # STEP 7: Main GPT call
        return self.ai_service.analyze_entity(
            business_name=business_name,
            property_state=property_state,
            last_activity_date=last_activity_date,
            property_report_year=property_report_year,
            ga_sos_records=redacted_sos_records,
            sos_search_names_tried=sos_search_names_tried,
            sos_matched_name=sos_matched_name,
            web_pages=pages,
            google_places_profile=google_places_profile,
        )

