"""
Platform-specific job board API integrations
Supports: Greenhouse, Lever, Ashby, Workable
"""

import logging
import requests
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class PlatformDetector:
    """Detect and fetch jobs from known job board platforms"""
    
    @staticmethod
    def detect_platform(website: str, career_url: str = None) -> Optional[str]:
        """
        Detect which job board platform a company uses
        
        Returns: 'greenhouse' | 'lever' | 'ashby' | 'workable' | None
        """
        check_url = career_url or website
        check_url_lower = check_url.lower()
        
        if 'greenhouse.io' in check_url_lower or 'boards.greenhouse.io' in check_url_lower:
            return 'greenhouse'
        elif 'lever.co' in check_url_lower or 'jobs.lever.co' in check_url_lower:
            return 'lever'
        elif 'ashbyhq.com' in check_url_lower or 'jobs.ashbyhq.com' in check_url_lower:
            return 'ashby'
        elif 'workable.com' in check_url_lower or 'apply.workable.com' in check_url_lower:
            return 'workable'
        
        return None
    
    @staticmethod
    def get_greenhouse_jobs(company_token: str) -> List[Dict]:
        """
        Fetch jobs from Greenhouse API
        
        Args:
            company_token: Company identifier (e.g., 'integrate' for integrate.greenhouse.io)
        
        Returns:
            List of job dicts with title, location, department
        """
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company_token}/jobs"
            
            logger.info(f"Fetching Greenhouse jobs: {url}")
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                jobs = data.get('jobs', [])
                
                results = []
                for job in jobs:
                    results.append({
                        'title': job.get('title'),
                        'location': job.get('location', {}).get('name'),
                        'department': job.get('departments', [{}])[0].get('name') if job.get('departments') else None,
                        'url': job.get('absolute_url'),
                        'platform': 'Greenhouse'
                    })
                
                logger.info(f"✅ Greenhouse: Found {len(results)} jobs")
                return results
            else:
                logger.warning(f"Greenhouse API returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Greenhouse API error: {e}")
            return []
    
    @staticmethod
    def get_lever_jobs(company_name: str) -> List[Dict]:
        """
        Fetch jobs from Lever API
        
        Args:
            company_name: Company slug (e.g., 'netflix')
        
        Returns:
            List of job dicts
        """
        try:
            url = f"https://api.lever.co/v0/postings/{company_name}"
            
            logger.info(f"Fetching Lever jobs: {url}")
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                jobs = response.json()
                
                results = []
                for job in jobs:
                    results.append({
                        'title': job.get('text'),
                        'location': job.get('categories', {}).get('location'),
                        'department': job.get('categories', {}).get('team'),
                        'url': job.get('hostedUrl'),
                        'platform': 'Lever'
                    })
                
                logger.info(f"✅ Lever: Found {len(results)} jobs")
                return results
            else:
                logger.warning(f"Lever API returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Lever API error: {e}")
            return []
    
    @staticmethod
    def get_ashby_jobs(company_name: str) -> List[Dict]:
        """
        Fetch jobs from Ashby (job board page scraping required)
        
        Args:
            company_name: Company slug
        
        Returns:
            List of job dicts
        """
        try:
            url = f"https://jobs.ashbyhq.com/{company_name}"
            
            logger.info(f"Checking Ashby: {url}")
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                # Ashby requires scraping - return URL for Playwright layer
                return [{'platform': 'Ashby', 'requires_scraping': True, 'url': url}]
            else:
                return []
                
        except Exception as e:
            logger.error(f"Ashby check error: {e}")
            return []
    
    @staticmethod
    def extract_company_token(website: str, career_url: str = None) -> Optional[str]:
        """
        Extract company token/slug from website or career URL
        
        Examples:
            - integrate.greenhouse.io → 'integrate'
            - jobs.lever.co/netflix → 'netflix'
            - www.company.com → 'company'
            - jobs.primary.vc → 'primary' (NOT 'jobs')
        """
        check_url = career_url or website
        
        try:
            parsed = urlparse(check_url)
            domain = parsed.netloc or parsed.path
            
            # Handle paths like /netflix in jobs.lever.co/netflix
            if parsed.path and len(parsed.path) > 1:
                path_parts = parsed.path.strip('/').split('/')
                if path_parts and path_parts[0] and path_parts[0] not in ['boards', 'postings', 'api', 'v0', 'v1']:
                    return path_parts[0]
            
            # Remove common prefixes
            domain = domain.replace('www.', '').replace('jobs.', '').replace('careers.', '')
            
            # Split by dots
            parts = domain.split('.')
            
            # For jobs.primary.vc → ['primary', 'vc']
            # For integrate.com → ['integrate', 'com']
            # For integrate.greenhouse.io → ['integrate', 'greenhouse', 'io']
            
            # Filter out common TLDs and platforms
            filtered = [p for p in parts if p not in ['com', 'co', 'io', 'net', 'org', 'ai', 'vc', 'greenhouse', 'lever', 'ashbyhq', 'workable']]
            
            if filtered:
                # Return first non-platform part
                company = filtered[0]
            else:
                # Fallback to first part
                company = parts[0] if parts else None
            
            logger.debug(f"Extracted token '{company}' from '{domain}'")
            return company
            
        except Exception as e:
            logger.error(f"Token extraction error: {e}")
            return None
    
    @classmethod
    def try_all_platforms(cls, website: str, career_url: str = None) -> List[Dict]:
        """
        Try all platform APIs to find jobs
        
        Returns:
            List of jobs from whichever platform works
        """
        company_token = cls.extract_company_token(website, career_url)
        
        if not company_token:
            logger.warning("Could not extract company token")
            return []
        
        # Try Greenhouse first (most popular)
        jobs = cls.get_greenhouse_jobs(company_token)
        if jobs:
            return jobs
        
        # Try Lever
        jobs = cls.get_lever_jobs(company_token)
        if jobs:
            return jobs
        
        # Try Ashby
        jobs = cls.get_ashby_jobs(company_token)
        if jobs:
            return jobs
        
        logger.info("No jobs found via platform APIs")
        return []
