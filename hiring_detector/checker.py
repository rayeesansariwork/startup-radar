"""
Main Enhanced Hiring Checker - 4-Layer Fallback System

Layer 1: Platform APIs (Greenhouse, Lever, Ashby) - FASTEST
Layer 2: Smart Career Page Detection
Layer 3: Playwright Browser Scraping - For dynamic pages
Layer 4: Mistral AI Analysis - Last resort
"""

import logging
import os
import requests
from typing import Dict, List, Optional
from urllib.parse import urlparse

from .platforms import PlatformDetector
from .scraper import scrape_page_sync, PlaywrightScraper
from .analyzer import JobAnalyzer
from .triangulator import HiringTriangulator

logger = logging.getLogger(__name__)


class EnhancedHiringChecker:
    """
    Multi-layer hiring detection system with fallbacks
    
    Usage:
        checker = EnhancedHiringChecker(mistral_api_key="your_key")
        result = checker.check_hiring("Acme Corp", "https://acme.com")
    """
    
    def __init__(self, mistral_api_key: str = None):
        self.mistral_key = mistral_api_key or os.getenv('MISTRAL_API_KEY')
        self.analyzer = JobAnalyzer(self.mistral_key) if self.mistral_key else None
        
    def check_hiring(self, company_name: str, website: str) -> Dict:
        """
        Check if company is hiring using multi-layer approach
        
        Args:
            company_name: Company name
            website: Company website URL
        
        Returns:
            {
                'is_hiring': bool,
                'career_page_url': str,
                'job_roles': list,
                'job_count': int,
                'hiring_summary': str,
                'detection_method': str  # How we found the jobs
            }
        """
        logger.info(f"🔍 Checking hiring for: {company_name}")
        
        # LAYER 1: Try Platform APIs (fastest, most reliable)
        result = self._try_platform_apis(company_name, website)
        if result and result.get('is_hiring'):
            logger.info(f"✅ Layer 1 success: {result.get('detection_method')}")
            return result
        
        # LAYER 2: Find career page
        career_url = self._find_career_page(website)
        if not career_url:
            logger.warning(f"No career page found for {company_name}")
            return {
                'is_hiring': False,
                'career_page_url': None,
                'job_roles': [],
                'job_count': 0,
                'hiring_summary': 'No career page found',
                'detection_method': 'none'
            }
        
        logger.info(f"Found career page: {career_url}")
        
        # LAYER 3: Try Playwright scraping (for dynamic pages)
        result = self._try_playwright_scraping(company_name, career_url)
        if result and result.get('is_hiring'):
            logger.info(f"✅ Layer 3 success: Playwright scraping")
            return result
        
        # LAYER 4: Mistral AI analysis (last resort)
        result = self._try_mistral_analysis(company_name, career_url)
        logger.info(f"Layer 4: Mistral analysis - found {result.get('job_count', 0)} jobs")
        return result
    
    def _try_platform_apis(self, company_name: str, website: str) -> Optional[Dict]:
        """Layer 1: Try platform-specific APIs"""
        try:
            jobs = PlatformDetector.try_all_platforms(website)
            
            if not jobs:
                return None
            
            # Check if requires scraping (Ashby case)
            if jobs and jobs[0].get('requires_scraping'):
                return None
            
            job_titles = [job['title'] for job in jobs if job.get('title')]
            platform = jobs[0].get('platform', 'API') if jobs else 'Unknown'
            
            return {
                'is_hiring': len(job_titles) > 0,
                'career_page_url': jobs[0].get('url') if jobs else None,
                'job_roles': job_titles,
                'job_count': len(job_titles),
                'hiring_summary': f"Found {len(job_titles)} positions via {platform}",
                'detection_method': f'{platform} API'
            }
            
        except Exception as e:
            logger.error(f"Platform API failed: {e}")
            return None
    
    def _find_career_page(self, website: str) -> Optional[str]:
        """Layer 2: Smart career page detection (triangulation-first)"""
        try:
            parsed = urlparse(website)
            domain = parsed.netloc or website
            domain = domain.replace('www.', '')

            # --- TRIANGULATION FIRST (Serper ATS → Sitemap → Organic) ---
            try:
                triangulator = HiringTriangulator()
                tri_url, tri_method = triangulator.triangulate(domain)
                if tri_url:
                    logger.info(f"✅ Triangulation ({tri_method}): {tri_url}")
                    return tri_url
            except Exception as tri_err:
                logger.warning(f"Triangulation error (falling back): {tri_err}")
            # --- END TRIANGULATION ---
            
            # Get base URL
            base_url = f"https://{domain}" if not website.startswith('http') else website
            base_url = base_url.rstrip('/')
            
            # Extract root domain (e.g., primary.vc from jobs.primary.vc)
            domain_parts = domain.split('.')
            if len(domain_parts) > 2 and domain_parts[0] in ['jobs', 'careers', 'www']:
                root_domain = '.'.join(domain_parts[1:])
                root_url = f"https://{root_domain}"
            else:
                root_domain = domain
                root_url = base_url
            
            # Common career page patterns
            patterns = [
                # Try original URL patterns first
                f'{base_url}/careers',
                f'{base_url}/jobs',
                f'{base_url}/company/careers',
                f'{base_url}/about/careers',
                f'{base_url}/join-us',
                f'{base_url}/work-with-us',
                f'{base_url}/team',
                # Try root domain if different
                f'{root_url}/careers',
                f'{root_url}/jobs',
                f'{root_url}/company/careers',
                # Try subdomain patterns
                f'https://careers.{root_domain}',
                f'https://jobs.{root_domain}',
            ]
            
            # Remove duplicates while preserving order
            seen = set()
            unique_patterns = []
            for p in patterns:
                if p not in seen:
                    seen.add(p)
                    unique_patterns.append(p)
            
            for url in unique_patterns:
                try:
                    logger.debug(f"Trying: {url}")
                    response = requests.head(url, timeout=5, allow_redirects=True)
                    if response.status_code == 200:
                        logger.info(f"✅ Found career page: {url}")
                        return url
                except:
                    continue
            
            logger.warning(f"No career page found via patterns for {website}")
            return None
            
        except Exception as e:
            logger.error(f"Career page search failed: {e}")
            return None
    
    def _try_playwright_scraping(self, company_name: str, career_url: str) -> Optional[Dict]:
        """Layer 3: Playwright browser scraping"""
        try:
            html = scrape_page_sync(career_url)
            
            if not html:
                return None
            
            # Extract jobs from HTML
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            
            # Quick check - does it mention jobs?
            text_lower = text.lower()
            if 'no open position' in text_lower or 'no current opening' in text_lower:
                return {
                    'is_hiring': False,
                    'career_page_url': career_url,
                    'job_roles': [],
                    'job_count': 0,
                    'hiring_summary': 'No open positions',
                    'detection_method': 'Playwright'
                }
            
            # Use Groq to analyze scraped content
            if self.analyzer:
                analysis = self.analyzer.analyze_career_page(text[:15000], company_name)
                analysis['career_page_url'] = career_url
                analysis['job_count'] = len(analysis.get('job_roles', []))
                analysis['detection_method'] = 'Playwright + Mistral AI'
                return analysis
            
            return None
            
        except Exception as e:
            logger.error(f"Playwright scraping failed: {e}")
            return None
    
    def _try_mistral_analysis(self, company_name: str, career_url: str) -> Dict:
        """Layer 4: Mistral AI analysis (fallback)"""
        try:
            # If career_url is an ATS page, try the platform API directly
            # (plain HTTP GET on SPA shells returns no job content)
            platform = PlatformDetector.detect_platform("", career_url)
            if platform:
                token = PlatformDetector.extract_company_token("", career_url)
                if token:
                    if platform == 'ashby':
                        jobs = PlatformDetector.get_ashby_jobs(token)
                    elif platform == 'greenhouse':
                        jobs = PlatformDetector.get_greenhouse_jobs(token)
                    elif platform == 'lever':
                        jobs = PlatformDetector.get_lever_jobs(token)
                    else:
                        jobs = []
                    # Only use results that have real job data (not requires_scraping stubs)
                    if jobs and not jobs[0].get('requires_scraping'):
                        job_titles = [j['title'] for j in jobs if j.get('title')]
                        if job_titles:
                            logger.info(
                                f"✅ Layer 4 ATS recovery: {len(job_titles)} jobs via {platform} API"
                            )
                            return {
                                'is_hiring': True,
                                'career_page_url': career_url,
                                'job_roles': job_titles,
                                'job_count': len(job_titles),
                                'hiring_summary': f"Found {len(job_titles)} positions via {platform} API",
                                'detection_method': f'{platform} API (Layer 4 recovery)',
                            }

            # Try simple HTTP request
            response = requests.get(career_url, timeout=10)
            
            if response.status_code != 200:
                return {
                    'is_hiring': False,
                    'career_page_url': career_url,
                    'job_roles': [],
                    'job_count': 0,
                    'hiring_summary': 'Could not access career page',
                    'detection_method': 'failed'
                }
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            
            if self.analyzer:
                analysis = self.analyzer.analyze_career_page(text[:15000], company_name)
                analysis['career_page_url'] = career_url
                analysis['job_count'] = len(analysis.get('job_roles', []))
                analysis['detection_method'] = 'Mistral AI (basic HTTP)'
                return analysis
            
            return {
                'is_hiring': False,
                'career_page_url': career_url,
                'job_roles': [],
                'job_count': 0,
                'hiring_summary': 'Mistral API key not configured',
                'detection_method': 'failed'
            }
            
        except Exception as e:
            logger.error(f"Mistral analysis failed: {e}")
            return {
                'is_hiring': False,
                'career_page_url': career_url,
                'job_roles': [],
                'job_count': 0,
                'hiring_summary': f'Error: {str(e)}',
                'detection_method': 'failed'
            }
