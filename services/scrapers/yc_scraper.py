"""
Y Combinator Scraper - Uses unofficial yc-oss API
"""

import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class YCombinatorScraper(BaseScraper):
    """Scraper for Y Combinator companies using yc-oss API"""
    
    API_URL = "https://yc-oss.github.io/api/companies/all.json"
    
    # Recent batches to prioritize (most recent first)
    # YC API uses full names like "Winter 2026", not "W26"
    RECENT_BATCHES = [
        'Winter 2026', 'Summer 2025',  # 2025-2026
        'Winter 2025', 'Summer 2024',  # 2024-2025  
        'Winter 2024', 'Summer 2023',  # 2023-2024
        'Fall 2024',   'Summer 2024'
    ]
    
    def __init__(self):
        super().__init__("Y Combinator")
    
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Scrape Y Combinator companies
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        start_time = datetime.now()
        try:
            # Fetch data from YC API
            logger.info(f"[YC] 🔍 Starting scrape (limit={limit or 'None'})")
            logger.debug(f"[YC] API URL: {self.API_URL}")
            logger.debug(f"[YC] Target batches: {', '.join(self.RECENT_BATCHES)}")
            
            api_start = datetime.now()
            response = requests.get(self.API_URL, timeout=30)
            api_duration = (datetime.now() - api_start).total_seconds()
            
            logger.info(f"[YC] 📡 API response received in {api_duration:.2f}s (status={response.status_code})")
            logger.debug(f"[YC] Response size: {len(response.content)} bytes")
            
            if response.status_code != 200:
                logger.error(f"[YC] ❌ API returned non-200 status: {response.status_code}")
                logger.debug(f"[YC] Response body: {response.text[:500]}")
                return []
            
            all_companies = response.json()
            logger.info(f"[YC] 📊 Total companies in API: {len(all_companies)}")
            
            # Filter for recent batches
            logger.debug(f"[YC] Filtering for batches: {self.RECENT_BATCHES}")
            recent_companies = []
            batch_counts = {}  # Track companies per batch
            
            for company in all_companies:
                batch = company.get('batch', '')
                
                # Count all batches for debugging
                batch_counts[batch] = batch_counts.get(batch, 0) + 1
                
                # Prioritize recent batches
                if batch in self.RECENT_BATCHES:
                    recent_companies.append(company)
            
            logger.info(f"[YC] 🎯 Filtered to {len(recent_companies)} companies from recent batches")
            # Log batch distribution
            for batch in self.RECENT_BATCHES:
                count = batch_counts.get(batch, 0)
                logger.debug(f"[YC]   - {batch}: {count} companies")
            
            # Sort by batch (most recent first)
            recent_companies.sort(
                key=lambda c: self.RECENT_BATCHES.index(c.get('batch', '')) 
                if c.get('batch', '') in self.RECENT_BATCHES else 999
            )
            
            # Apply limit if specified
            if limit:
                logger.debug(f"[YC] Applying limit: {limit}")
                recent_companies = recent_companies[:limit]
            
            # Normalize to our format
            normalized = []
            skipped = 0
            
            for company in recent_companies:
                # Extract company data
                company_name = company.get('name', '').strip()
                website = company.get('website', '').strip()
                batch = company.get('batch', '')
                description = company.get('description', '')
                status = company.get('status', '')
                
                if not company_name:
                    skipped += 1
                    logger.debug(f"[YC] Skipped company with no name: {company}")
                    continue
                
                # Create funding info from batch and status
                funding_info = f"Y Combinator {batch}"
                if status and status.lower() != 'active':
                    funding_info += f" ({status})"
                
                normalized.append({
                    'company_name': company_name,
                    'website': self.normalize_website(website) if website else f"https://{company_name.lower().replace(' ', '')}.com",
                    'funding_info': funding_info,
                    'source': 'Y Combinator',
                    'batch': batch,
                    'funding_round': 'Accelerator',
                    'description': description[:200] if description else None  # Truncate long descriptions
                })
            
            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[YC] ✅ Scrape complete: {len(normalized)} companies normalized (skipped={skipped}, duration={total_duration:.2f}s)")
            
            # Log sample companies for debugging
            if normalized:
                logger.debug(f"[YC] Sample companies: {[c['company_name'] for c in normalized[:3]]}")
            
            return normalized
            
        except requests.exceptions.Timeout:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[YC] ⏱️ API request timed out after {duration:.2f}s")
            return []
        except requests.exceptions.RequestException as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[YC] 🌐 Network error after {duration:.2f}s: {e}", exc_info=True)
            return []
        except ValueError as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[YC] 📄 JSON parse error after {duration:.2f}s: {e}")
            logger.debug(f"[YC] Response content: {response.text[:500] if 'response' in locals() else 'N/A'}")
            return []
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[YC] ❌ Unexpected error after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []
