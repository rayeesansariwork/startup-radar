"""
Base Scraper - Abstract class for all company data sources
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# from groq import RateLimitError # Removed Groq
from mistralai import Mistral

from utils.rate_limiter import rate_limiter
from config import settings

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all company scrapers"""
    
    def __init__(self, name: str):
        self.name = name
        self.last_scrape_time: Optional[datetime] = None
        self.last_scrape_count: int = 0
        # Initialize Mistral Client
        self.mistral_client = Mistral(api_key=settings.mistral_api_key)
    
    @abstractmethod
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """Scrape companies from this source"""
        pass
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=5, max=60)
    )
    def _call_mistral_with_retry(self, func, *args, **kwargs):
        """Wrapper for Mistral calls to handle rate limits"""
        # Acquire rate limit slot before making the call
        self.rate_limit()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Mistral might raise generic exceptions for rate limits, 
            # or specifically mistralai.exceptions.MistralAPIException
            # For now, we catch generic exception and log it.
            # In a robust implementation, we'd check for 429 status or specific exception.
            if "429" in str(e) or "Too Many Requests" in str(e):
                 logger.warning(f"⚠️ [{self.name}] Mistral Rate Limit Hit: {e}. Retrying...")
                 raise e
            raise e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def scrape_with_retry(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Wrapper that adds retry logic to scraping
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        try:
            logger.info(f"🔍 [{self.name}] Starting scrape...")
            start_time = datetime.now()
            
            companies = self.scrape(limit)
            
            scrape_time = (datetime.now() - start_time).total_seconds()
            self.last_scrape_time = datetime.now()
            self.last_scrape_count = len(companies)
            
            logger.info(f"✅ [{self.name}] Scraped {len(companies)} companies in {scrape_time:.2f}s")
            return companies
            
        except Exception as e:
            logger.error(f"❌ [{self.name}] Scrape failed: {e}", exc_info=True)
            raise
    
    def rate_limit(self, delay_seconds: float = None):
        """
        Enforce global rate limit for Groq API calls.
        
        Args:
            delay_seconds: Ignored, used for compatibility. 
                           Uses global config settings.
        """
        rate_limiter.acquire()
    
    def normalize_website(self, url: str) -> str:
        """
        Normalize website URL to consistent format
        
        Args:
            url: Raw URL string
        
        Returns:
            Normalized URL with https:// prefix
        """
        if not url:
            return ""
        
        url = url.strip()
        
        # Add https:// if no protocol
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'
        
        # Remove trailing slash
        url = url.rstrip('/')
        
        return url
    
    def extract_domain(self, url: str) -> str:
        """
        Extract clean domain from URL for deduplication
        
        Args:
            url: URL string
        
        Returns:
            Domain name (e.g., "example.com")
        """
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(self.normalize_website(url))
            domain = parsed.netloc or parsed.path
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain.lower()
        except:
            return url.lower()
