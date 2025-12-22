"""Google Custom Search and web scraping service."""

import os
import logging
from typing import List, Dict, Any, Optional
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from services.exceptions import GoogleSearchError
from services.cse_query_selector import CSEQuerySelector

logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfReader
    PDF_EXTRACTION_AVAILABLE = True
except ImportError:
    PDF_EXTRACTION_AVAILABLE = False

# Configuration
GOOGLE_CUSTOM_SEARCH_API_KEY = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
GOOGLE_CUSTOM_SEARCH_ENGINE_ID = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")
MAX_RESULTS_PER_QUERY = 3
MAX_CONTENT_CHARS_PER_PAGE = 12000
SCRAPE_TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "30"))


class GoogleSearchService:
    """Service for Google Custom Search and web scraping."""
    
    def __init__(self):
        """Initialize Google Search service."""
        if not GOOGLE_CUSTOM_SEARCH_API_KEY:
            logger.warning("GoogleSearchService: GOOGLE_CUSTOM_SEARCH_API_KEY not set")
        if not GOOGLE_CUSTOM_SEARCH_ENGINE_ID:
            logger.warning("GoogleSearchService: GOOGLE_CUSTOM_SEARCH_ENGINE_ID not set")
        self.query_selector = CSEQuerySelector()
    
    def search(self, query: str, num: int = MAX_RESULTS_PER_QUERY) -> List[Dict[str, Any]]:
        """
        Perform a Google Custom Search.
        
        Args:
            query: Search query string
            num: Number of results to return (default: MAX_RESULTS_PER_QUERY)
            
        Returns:
            List of search result items with 'link' and 'title' keys
            
        Raises:
            GoogleSearchError: If search fails
        """
        if not GOOGLE_CUSTOM_SEARCH_API_KEY or not GOOGLE_CUSTOM_SEARCH_ENGINE_ID:
            raise GoogleSearchError("Google Custom Search API key or engine ID not configured")
        
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
    
    def scrape_url(self, url: str) -> str:
        """
        Scrape content from a URL (HTML or PDF).
        
        Args:
            url: URL to scrape
            
        Returns:
            Extracted text content
            
        Raises:
            GoogleSearchError: If scraping fails
        """
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
    
    def collect_pages_for_business(
        self,
        business_name: str,
        property_state: str,
        sos_record: Optional[Dict[str, Any]] = None,
        city: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Collect web pages for a business using scenario-based Google search queries.
        
        Args:
            business_name: Business name to search for
            property_state: State where property is located (full name)
            sos_record: Optional SOS record dict (for status-based query selection)
            city: Optional city name (for local footprint queries)
            
        Returns:
            List of page dictionaries with 'id', 'url', 'title', 'type', 'content' keys
            
        Raises:
            GoogleSearchError: If no pages are collected
        """
        # Get query pack from selector based on SOS status
        query_pack = self.query_selector.get_cse_queries(
            sos=sos_record,
            business_name=business_name,
            state_full=property_state,
            city=city,
        )
        
        logger.info(f"collect_pages_for_business: Selected scenario '{query_pack.scenario}' with {len(query_pack.queries)} queries")
        
        pages = []
        min_results_required = 1
        
        def execute_and_scrape_query(query_name: str, query_string: str) -> int:
            """Execute a single query and scrape results, returns number of successful pages."""
            successful = 0
            try:
                results = self.search(query_string)
                if not results:
                    return 0
                
                for idx, item in enumerate(results, start=1):
                    url = item.get("link")
                    title = item.get("title") or ""
                    if not url:
                        continue
                    
                    # Classify result type based on title/content
                    lower_title = title.lower()
                    if any(keyword in lower_title for keyword in ["secretary of state", "corporation division", "business search", "corp search", "business entity"]):
                        kind = "sos_like"
                    elif any(keyword in lower_title for keyword in ["opencorporates", "company register", "registry"]):
                        kind = "registry"
                    elif "successor" in query_name or "acquisition" in query_name or "merged" in query_name:
                        kind = "news"
                    else:
                        kind = "web"
                    
                    try:
                        content = self.scrape_url(url)
                        pages.append({
                            "id": f"{query_name}_{idx}",
                            "url": url,
                            "title": title,
                            "type": kind,
                            "content": content,
                        })
                        successful += 1
                    except GoogleSearchError as e:
                        # If it's a PDF skip error or forbidden error, log and continue to next result
                        error_msg = str(e).lower()
                        if "pdf" in error_msg or "skipping" in error_msg or "forbidden" in error_msg or "403" in error_msg:
                            logger.debug(f"Skipping: {url} - {e}")
                            continue
                        # For other errors, log but don't fail the whole query
                        logger.warning(f"Failed to scrape {query_name} URL {url}: {e}")
                    except Exception as e:
                        logger.warning(f"Unexpected error scraping {query_name} URL {url}: {e}")
                
                return successful
            except requests.RequestException as e:
                logger.warning(f"Query '{query_name}' failed: {e}")
                return 0
            except GoogleSearchError as e:
                logger.warning(f"Query '{query_name}' had issues: {e}")
                return 0
            except Exception as e:
                logger.warning(f"Unexpected error executing query '{query_name}': {e}")
                return 0
        
        # Execute all queries in parallel
        with ThreadPoolExecutor(max_workers=len(query_pack.queries)) as executor:
            futures = {
                executor.submit(execute_and_scrape_query, query_name, query_string): query_name
                for query_name, query_string in query_pack.queries.items()
            }
            
            # Wait for all queries to complete
            for future in as_completed(futures):
                query_name = futures[future]
                try:
                    successful = future.result()
                    logger.debug(f"Query '{query_name}': {successful} pages collected")
                except Exception as e:
                    logger.warning(f"Query '{query_name}' raised exception: {e}")
        
        if len(pages) == 0:
            raise GoogleSearchError(f"No pages collected from any query for {business_name} (scenario: {query_pack.scenario})")
        
        logger.info(f"collect_pages_for_business: Collected {len(pages)} total pages from {len(query_pack.queries)} queries")
        return pages

