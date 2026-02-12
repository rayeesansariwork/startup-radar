"""
Playwright-based web scraper for dynamic career pages
Handles JavaScript-heavy pages that require browser rendering
"""

import logging
import asyncio
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Playwright is optional - graceful degradation
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed - dynamic page scraping disabled")


class PlaywrightScraper:
    """Scrape career pages using headless browser"""
    
    @staticmethod
    async def scrape_page(url: str, wait_for_selector: str = None) -> Optional[str]:
        """
        Scrape a page using Playwright headless browser
        
        Args:
            url: URL to scrape
            wait_for_selector: Optional CSS selector to wait for
        
        Returns:
            HTML content as string
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available")
            return None
        
        try:
            async with async_playwright() as p:
                logger.info(f"Launching browser for: {url}")
                
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Set a realistic user agent
                await page.set_extra_http_headers({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Wait for specific selector if provided
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=5000)
                    except:
                        logger.warning(f"Selector {wait_for_selector} not found")
                
                # Get page content
                content = await page.content()
                
                await browser.close()
                
                logger.info(f"✅ Scraped {len(content)} characters")
                return content
                
        except Exception as e:
            logger.error(f"Playwright scraping failed: {e}")
            return None
    
    @staticmethod
    def extract_job_listings(html: str) -> list:
        """
        Extract potential job listings from HTML
        
        Args:
            html: HTML content
        
        Returns:
            List of job title strings
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            jobs = []
            
            # Common patterns for job listings
            job_selectors = [
                # Class-based
                {'class_': 'job-title'},
                {'class_': 'job-listing'},
                {'class_': 'position-title'},
                {'class_': 'opening-title'},
                {'class_': 'career-title'},
                # Data attributes
                {'attrs': {'data-job-title': True}},
                {'attrs': {'data-position': True}},
            ]
            
            # Try each selector
            for selector in job_selectors:
                elements = soup.find_all(['h2', 'h3', 'h4', 'a', 'div', 'li'], **selector)
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if text and len(text) > 5 and len(text) < 100:
                        jobs.append(text)
            
            # Deduplicate
            jobs = list(set(jobs))
            
            logger.info(f"Extracted {len(jobs)} potential job titles from HTML")
            return jobs
            
        except Exception as e:
            logger.error(f"Job extraction error: {e}")
            return []
    
    @classmethod
    async def scrape_and_extract(cls, url: str) -> list:
        """
        Scrape a page and extract job listings
        
        Returns:
            List of job titles
        """
        html = await cls.scrape_page(url)
        
        if not html:
            return []
        
        return cls.extract_job_listings(html)


# Synchronous wrapper for Django views
def scrape_page_sync(url: str) -> Optional[str]:
    """Synchronous wrapper for async scraping"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(PlaywrightScraper.scrape_page(url))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Sync scrape error: {e}")
        return None


def scrape_and_extract_sync(url: str) -> list:
    """Synchronous wrapper for scrape and extract"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(PlaywrightScraper.scrape_and_extract(url))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Sync scrape and extract error: {e}")
        return []
