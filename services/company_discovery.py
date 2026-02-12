"""
Company Discovery Service - Multi-source orchestrator
"""

import logging
from typing import List, Dict, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .scrapers import (YCombinatorScraper, TechCrunchScraper, ProductHuntScraper, 
                       NewsAPIScraper, GoogleNewsScraper, 
                       VentureBeatScraper)

logger = logging.getLogger(__name__)


class CompanyDiscoveryService:
    """Orchestrates multiple data sources for company discovery"""
    
    def __init__(self, enable_yc: bool = True, enable_techcrunch: bool = True, 
                 enable_producthunt: bool = False, enable_newsapi: bool = True,
                 enable_google_news: bool = True,
                 enable_venturebeat: bool = True):
        """
        Initialize discovery service with desired sources
        
        Args:
            enable_yc: Enable Y Combinator scraper
            enable_techcrunch: Enable TechCrunch scraper
            enable_producthunt: Enable ProductHunt scraper (placeholder)
            enable_newsapi: Enable News API scraper
            enable_google_news: Enable Google News RSS scraper
            enable_venturebeat: Enable VentureBeat RSS scraper
        """
        self.scrapers = []
        
        logger.info("[Discovery] Initializing CompanyDiscoveryService")
        
        if enable_yc:
            self.scrapers.append(YCombinatorScraper())
            logger.info("[Discovery] ✅ Y Combinator scraper enabled")
        
        if enable_techcrunch:
            self.scrapers.append(TechCrunchScraper())
            logger.info("[Discovery] ✅ TechCrunch scraper enabled")
        
        if not self.scrapers:
            logger.warning("[Discovery] ⚠️ No scrapers enabled!")
        else:
            logger.info(f"[Discovery] Total scrapers enabled: {len(self.scrapers)}")
        
        if enable_producthunt:
            self.scrapers.append(ProductHuntScraper())
            logger.info("[Discovery] ✅ ProductHunt scraper enabled (placeholder)")
        
        if enable_newsapi:
            self.scrapers.append(NewsAPIScraper())
            logger.info("[Discovery] ✅ News API scraper enabled")
        
        if enable_google_news:
            self.scrapers.append(GoogleNewsScraper())
            logger.info("[Discovery] ✅ Google News RSS scraper enabled")
        
        if enable_venturebeat:
            self.scrapers.append(VentureBeatScraper())
            logger.info("[Discovery] ✅ VentureBeat RSS scraper enabled")
    
    def discover_companies(self, limit: Optional[int] = None) -> Dict:
        """
        Discover companies from all enabled sources
        
        Args:
            limit: Optional total limit on companies to return
        
        Returns:
            {
                'success': bool,
                'companies': List[Dict],
                'sources_used': List[str],
                'total_before_dedup': int,
                'total_after_dedup': int
            }
        """
        start_time = datetime.now()
        
        try:
            logger.info("="*60)
            logger.info(f"[Discovery] 🚀 STARTING MULTI-SOURCE DISCOVERY")
            logger.info(f"[Discovery] Enabled sources: {len(self.scrapers)}")
            logger.info(f"[Discovery] Requested limit: {limit or 'None'}")
            logger.info("="*60)
            
            if not self.scrapers:
                logger.error("[Discovery] ❌ No scrapers configured")
                return {
                    'success': False,
                    'error': 'No scrapers configured',
                    'companies': []
                }
            
            # Scrape from all sources in parallel
            all_companies = []
            sources_used = []
            source_stats = {}  # Track stats per source
            
            # Calculate per-source limit
            per_source_limit = None
            if limit:
                per_source_limit = (limit // len(self.scrapers)) + (limit % len(self.scrapers))
                logger.debug(f"[Discovery] Per-source limit: {per_source_limit}")
            
            logger.info(f"[Discovery] 🛠️ Starting parallel scraping with {len(self.scrapers)} workers")
            parallel_start = datetime.now()
            
            with ThreadPoolExecutor(max_workers=len(self.scrapers)) as executor:
                # Submit all scraper tasks
                future_to_scraper = {
                    executor.submit(scraper.scrape_with_retry, per_source_limit): scraper
                    for scraper in self.scrapers
                }
                
                logger.debug(f"[Discovery] Submitted {len(future_to_scraper)} scraper tasks")
                
                # Collect results as they complete
                completed = 0
                for future in as_completed(future_to_scraper):
                    scraper = future_to_scraper[future]
                    completed += 1
                    
                    try:
                        scrape_start = datetime.now()
                        companies = future.result()
                        scrape_duration = (datetime.now() - scrape_start).total_seconds()
                        
                        if companies:
                            all_companies.extend(companies)
                            sources_used.append(scraper.name)
                            source_stats[scraper.name] = {
                                'count': len(companies),
                                'duration': scrape_duration
                            }
                            logger.info(f"[Discovery] ✅ [{completed}/{len(self.scrapers)}] {scraper.name}: {len(companies)} companies in {scrape_duration:.2f}s")
                        else:
                            source_stats[scraper.name] = {
                                'count': 0,
                                'duration': scrape_duration
                            }
                            logger.warning(f"[Discovery] ⚠️ [{completed}/{len(self.scrapers)}] {scraper.name}: 0 companies in {scrape_duration:.2f}s")
                    except Exception as e:
                        source_stats[scraper.name] = {
                            'count': 0,
                            'error': str(e)
                        }
                        logger.error(f"[Discovery] ❌ [{completed}/{len(self.scrapers)}] {scraper.name} failed: {type(e).__name__}: {e}")
            
            parallel_duration = (datetime.now() - parallel_start).total_seconds()
            logger.info(f"[Discovery] 🔥 Parallel scraping complete in {parallel_duration:.2f}s")
            
            total_before_dedup = len(all_companies)
            logger.info(f"[Discovery] 📦 Total companies collected: {total_before_dedup}")
            
            # Log per-source breakdown
            logger.debug(f"[Discovery] Source breakdown:")
            for source, stats in source_stats.items():
                if 'error' in stats:
                    logger.debug(f"[Discovery]   - {source}: ERROR - {stats['error']}")
                else:
                    logger.debug(f"[Discovery]   - {source}: {stats['count']} companies in {stats.get('duration', 0):.2f}s")
            
            # Deduplicate companies
            if total_before_dedup > 0:
                logger.info(f"[Discovery] 🧬 Starting deduplication...")
                dedup_start = datetime.now()
                deduplicated = self._deduplicate_companies(all_companies)
                dedup_duration = (datetime.now() - dedup_start).total_seconds()
                total_after_dedup = len(deduplicated)
                
                duplicates_removed = total_before_dedup - total_after_dedup
                logger.info(f"[Discovery] 🎯 Deduplication complete in {dedup_duration:.2f}s: {total_after_dedup} unique (removed {duplicates_removed} duplicates)")
            else:
                deduplicated = []
                total_after_dedup = 0
                logger.warning(f"[Discovery] ⚠️ No companies to deduplicate")
            
            # Apply final limit if specified
            if limit and len(deduplicated) > limit:
                logger.info(f"[Discovery] ✂️ Applying final limit: {limit} (had {len(deduplicated)})")
                deduplicated = deduplicated[:limit]
            
            total_duration = (datetime.now() - start_time).total_seconds()
            
            logger.info("="*60)
            logger.info(f"[Discovery] ✅ DISCOVERY COMPLETE")
            logger.info(f"[Discovery] Total duration: {total_duration:.2f}s")
            logger.info(f"[Discovery] Companies returned: {len(deduplicated)}")
            logger.info(f"[Discovery] Sources used: {', '.join(sources_used) if sources_used else 'None'}")
            logger.info("="*60)
            
            return {
                'success': True,
                'companies': deduplicated,
                'sources_used': sources_used,
                'total_before_dedup': total_before_dedup,
                'total_after_dedup': total_after_dedup,
                'duration': total_duration,
                'source_stats': source_stats
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[Discovery] ❌ Discovery failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'companies': [],
                'duration': duration
            }
    
    def _deduplicate_companies(self, companies: List[Dict]) -> List[Dict]:
        """
        Remove duplicate companies based on name and website
        
        Args:
            companies: List of company dicts
        
        Returns:
            Deduplicated list
        """
        logger.debug(f"[Discovery-Dedup] Starting deduplication of {len(companies)} companies")
        
        seen_names: Set[str] = set()
        seen_domains: Set[str] = set()
        deduplicated = []
        
        duplicates_by_name = 0
        duplicates_by_domain = 0
        
        for company in companies:
            # Normalize company name for comparison
            name = company.get('company_name', '').lower().strip()
            website = company.get('website', '')
            
            # Extract domain from website for better matching
            domain = self._extract_domain(website) if website else ''
            
            # Skip if we've seen this company before
            if name in seen_names:
                duplicates_by_name += 1
                logger.debug(f"[Discovery-Dedup] ⚠️ Duplicate by name: {name}")
                continue
            
            if domain and domain in seen_domains:
                duplicates_by_domain += 1
                logger.debug(f"[Discovery-Dedup] ⚠️ Duplicate by domain: {domain} ({name})")
                continue
            
            # Add to results
            deduplicated.append(company)
            seen_names.add(name)
            if domain:
                seen_domains.add(domain)
        
        logger.debug(f"[Discovery-Dedup] Removed {duplicates_by_name} duplicates by name, {duplicates_by_domain} by domain")
        return deduplicated
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        from urllib.parse import urlparse
        
        try:
            if not url:
                return ""
            
            # Add scheme if missing
            if not url.startswith(('http://', 'https://')):
                url = f'https://{url}'
            
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain.lower()
        except:
            return ""
