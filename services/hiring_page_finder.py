import logging
import requests
import json
import os
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from hiring_detector.scraper import scrape_page_sync

logger = logging.getLogger(__name__)

class HiringPageFinderService:
    """
    Service to find, scrape, and analyze hiring pages.
    """

    def __init__(self):
        self.serper_api_key = "d9e9dd4fe917dc1af2b05ab33efe2a0537a33349"
        self.mistral_api_key = "9zAFjlgJmd4LdgO3v7w57roYjSxiw10A"
        
        if not self.serper_api_key:
            logger.warning("SERPER_API_KEY not found in environment variables")
        if not self.mistral_api_key:
            logger.warning("MISTRAL_API_KEY not found in environment variables")
            
        try:
            from mistralai import Mistral
            self.mistral_client = Mistral(api_key=self.mistral_api_key) if self.mistral_api_key else None
        except ImportError:
            logger.error("mistralai package not installed")
            self.mistral_client = None

    def find_hiring_page(self, company_url: str) -> Dict:
        """
        Orchestrates the process: Find -> Scrape -> Extract.
        Strategy:
        1. Serper Search (most reliable for specific pages)
        2. Homepage "Hunt" (look for links on homepage)
        3. Common Pattern Check (guess URLs)
        """
        # Ensure company_url has schema
        if not company_url.startswith(('http://', 'https://')):
            company_url = 'https://' + company_url

        career_url = None
        method = None

        # 1. Try Serper Search
        logger.info(f"Strategy 1: Serper Search for {company_url}")
        career_url = self._search_career_page_url(company_url)
        if career_url:
            method = "Serper Search"
        
        # 2. Try Homepage Hunt
        if not career_url:
            logger.info(f"Strategy 2: Homepage Hunt for {company_url}")
            career_url = self._find_link_on_homepage(company_url)
            if career_url:
                method = "Homepage Link"

        # 3. Try Common Patterns
        if not career_url:
            logger.info(f"Strategy 3: Common Patterns for {company_url}")
            career_url = self._check_common_patterns(company_url)
            if career_url:
                method = "Common Pattern"

        if not career_url:
            return {"error": "No hiring page detected after all strategies"}

        logger.info(f"✅ Found career page: {career_url} (Method: {method})")

        # 2. Scrape the content
        content = self._scrape_page_content(career_url)
        if not content:
            return {"error": "Scraping failed", "career_page_url": career_url}

        # 3. Extract job openings using Mistral
        jobs = self._extract_jobs_with_mistral(content)
        
        return {
            "career_page_url": career_url,
            "jobs": jobs,
            "detection_method": method
        }

    def _search_career_page_url(self, company_url: str) -> Optional[str]:
        """
        Uses Serper.dev API to find the career page.
        Query: "site:{domain} careers" or "site:{domain} jobs"
        """
        if not self.serper_api_key:
            logger.error("Cannot search without SERPER_API_KEY")
            return None

        domain = self._extract_domain(company_url)
        if not domain:
            logger.error(f"Could not extract domain from {company_url}")
            return None

        # Search query
        query = f"site:{domain} careers jobs"
        
        url = "https://google.serper.dev/search"
        payload = json.dumps({
            "q": query,
            "num": 3
        })
        headers = {
            'X-API-KEY': self.serper_api_key,
            'Content-Type': 'application/json'
        }

        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()
            results = response.json()
            
            if "organic" in results and len(results["organic"]) > 0:
                # Return the first organic result link
                return results["organic"][0]["link"]
            
            logger.info(f"No results found for {query}")
            return None
            
        except Exception as e:
            logger.error(f"Serper API search failed: {e}")
            return None

    def _find_link_on_homepage(self, company_url: str) -> Optional[str]:
        """
        Scrapes the homepage and looks for links to career pages.
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(company_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return None
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            keywords = ['career', 'careers', 'job', 'jobs', 'hiring', 'join us', 'work with us', 'openings', 'positions']
            
            # Find all links
            links = soup.find_all('a', href=True)
            
            for link in links:
                href = link['href']
                text = link.get_text(strip=True).lower()
                
                # Check text for keywords
                if any(k in text for k in keywords):
                    logger.info(f"Found candidate link by text '{text}': {href}")
                    return self._normalize_url(company_url, href)
                    
                # Check href for keywords
                if any(k in href.lower() for k in keywords):
                    logger.info(f"Found candidate link by href: {href}")
                    return self._normalize_url(company_url, href)
                    
            return None
            
        except Exception as e:
            logger.warning(f"Homepage hunt failed: {e}")
            return None

    def _check_common_patterns(self, company_url: str) -> Optional[str]:
        """
        Checks common career page URL patterns.
        """
        base_url = company_url.rstrip('/')
        patterns = [
            '/careers',
            '/jobs',
            '/about/careers',
            '/company/careers',
            '/join-us',
            '/work-with-us',
            '/openings'
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        for p in patterns:
            url = f"{base_url}{p}"
            try:
                response = requests.head(url, headers=headers, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    # Double check it's not a soft 404/redirect to homepage
                    final_url = response.url
                    if len(final_url) > len(base_url) + 2: # heuristic
                        logger.info(f"Found common pattern: {url}")
                        return url
            except Exception:
                continue
                
        return None

    def _normalize_url(self, base_url: str, href: str) -> str:
        """Joins relative URLs with base URL."""
        if href.startswith(('http://', 'https://')):
            return href
        
        from urllib.parse import urljoin
        return urljoin(base_url, href)

    def _scrape_page_content(self, url: str) -> Optional[str]:
        """
        Scrapes the full content of the page. 
        Tries simple requests first, then falls back to Playwright if available/needed.
        Returns cleaned text content.
        """
        text_content = ""
        
        # Try simple requests first (faster)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Remove scripts and styles
                for script in soup(["script", "style"]):
                    script.extract()
                text_content = soup.get_text(separator=' ', strip=True)
        except Exception as e:
            logger.warning(f"Simple scraping failed for {url}: {e}")

        # If simple scraping returned very little content (< 500 chars), try Playwright
        if len(text_content) < 500:
            logger.info(f"Content too short ({len(text_content)} chars), trying Playwright...")
            html_content = scrape_page_sync(url)
            if html_content:
                soup = BeautifulSoup(html_content, 'html.parser')
                for script in soup(["script", "style"]):
                    script.extract()
                text_content = soup.get_text(separator=' ', strip=True)
        
        if not text_content:
             logger.error(f"Failed to scrape content from {url}")
             return None
             
        return text_content

    def _extract_jobs_with_mistral(self, page_text: str) -> List[Dict]:
        """
        Sends content to Mistral AI to extract job openings.
        """
        if not self.mistral_client:
            logger.error("Mistral client not initialized")
            return []

        # Truncate text if too long (approx 20k chars to be safe with tokens)
        truncated_text = page_text[:20000]
        
        logger.info(f"Sending {len(truncated_text)} chars to Mistral. Preview: {truncated_text[:200]}...")

        prompt = f"""Extract all job openings from this page text. 
Return ONLY a JSON array with this structure: 
[{{ "title": "string", "department": "string", "location": "string", "description": "string", "apply_url": "string" }}]

If a field is missing, use "N/A" or empty string. 
If no jobs are found, return an empty array [].
Do NOT return any markdown formatting, just the raw JSON string.

Page Text:
{truncated_text}
"""

        try:
            chat_response = self.mistral_client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.1,
            )
            
            content = chat_response.choices[0].message.content
            
            # Clean up potential markdown code blocks if Mistral ignores instructions
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "")
            elif content.startswith("```"):
                content = content.replace("```", "")
            
            content = content.strip()
            
            try:
                jobs = json.loads(content)
                if isinstance(jobs, list):
                    return jobs
                else:
                    logger.warning("Mistral did not return a list")
                    return []
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from Mistral: {content[:100]}...")
                return []

        except Exception as e:
            logger.error(f"Mistral extraction failed: {e}")
            return []

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extracts domain from a URL."""
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            parsed = urlparse(url)
            return parsed.netloc.replace('www.', '')
        except Exception:
            return None
