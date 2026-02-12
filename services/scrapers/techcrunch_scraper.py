"""
TechCrunch Scraper - Scrapes funding news from TechCrunch RSS feed
"""

import logging
import feedparser
import json
import re
import requests
from typing import List, Dict, Optional
from datetime import datetime


from .base_scraper import BaseScraper
from config import settings

logger = logging.getLogger(__name__)


class TechCrunchScraper(BaseScraper):
    """Scraper for TechCrunch funding news via RSS feed"""
    
    RSS_URL = "https://techcrunch.com/feed/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    def __init__(self):
        super().__init__("TechCrunch")
    
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Scrape TechCrunch funding articles
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        start_time = datetime.now()
        groq_calls = 0
        groq_errors = 0
        
        try:
            # Fetch RSS feed
            logger.info(f"[TC] 🔍 Starting scrape (limit={limit or 'None'})")
            logger.debug(f"[TC] RSS URL: {self.RSS_URL}")
            
            rss_start = datetime.now()
            
            # Use requests with headers to avoid bot detection
            try:
                response = requests.get(self.RSS_URL, headers=self.HEADERS, timeout=15)
                response.raise_for_status()
                feed_content = response.content
            except Exception as e:
                logger.error(f"[TC] ❌ Failed to fetch RSS feed: {e}")
                return []

            feed = feedparser.parse(feed_content)
            rss_duration = (datetime.now() - rss_start).total_seconds()
            
            logger.info(f"[TC] 📡 RSS feed parsed in {rss_duration:.2f}s")
            logger.debug(f"[TC] Feed bozo: {feed.bozo}, version: {feed.get('version', 'N/A')}")
            
            if feed.bozo:
                logger.warning(f"[TC] ⚠️ RSS feed has bozo flag (malformed): {feed.get('bozo_exception', 'Unknown')}")
            
            if not feed.entries:
                logger.warning(f"[TC] ⚠️ No entries found in TechCrunch RSS feed")
                logger.debug(f"[TC] Feed keys: {list(feed.keys())}")
                return []
            
            logger.info(f"[TC] 📰 Found {len(feed.entries)} articles in RSS feed")
            
            # Limit articles to process (more articles = more API calls)
            max_articles = min(limit or 10, 20)
            articles_to_process = feed.entries[:max_articles]
            logger.debug(f"[TC] Processing {len(articles_to_process)} articles (max={max_articles})")
            
            # Extract companies from articles using Groq
            all_companies = []
            
            for idx, entry in enumerate(articles_to_process, 1):
                try:
                    title = entry.get('title', '')
                    summary = entry.get('summary', '')
                    link = entry.get('link', '')
                    published = entry.get('published', '')
                    
                    logger.info(f"[TC] 📄 [{idx}/{len(articles_to_process)}] Processing: {title[:60]}...")
                    logger.debug(f"[TC]   Link: {link}")
                    
                    # Extract company info using Groq
                    article_start = datetime.now()
                    companies = self._extract_companies_from_article(title, summary, link, published)
                    article_duration = (datetime.now() - article_start).total_seconds()
                    groq_calls += 1
                    
                    if companies:
                        all_companies.extend(companies)
                        logger.info(f"[TC]   ✅ Extracted {len(companies)} companies in {article_duration:.2f}s")
                        logger.debug(f"[TC]   Companies: {[c['company_name'] for c in companies]}")
                    else:
                        logger.debug(f"[TC]   ⚠️ No companies extracted (took {article_duration:.2f}s)")
                    
                    # Rate limit to avoid overwhelming Groq API
                    if idx < len(articles_to_process):
                        self.rate_limit(0.5)
                    
                except Exception as e:
                    groq_errors += 1
                    logger.error(f"[TC]   ❌ Failed to process article: {type(e).__name__}: {e}")
                    logger.debug(f"[TC]   Article title: {title[:100]}")
                    continue
            
            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[TC] ✅ Scrape complete: {len(all_companies)} companies from {len(articles_to_process)} articles")
            logger.info(f"[TC] 📊 Stats: Groq calls={groq_calls}, errors={groq_errors}, duration={total_duration:.2f}s")
            
            # Apply final limit if specified
            if limit and len(all_companies) > limit:
                logger.debug(f"[TC] Applying final limit: {limit} (had {len(all_companies)})")
                all_companies = all_companies[:limit]
            
            return all_companies
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[TC] ❌ Scraper failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []
    
    def _extract_companies_from_article(
        self, 
        title: str, 
        summary: str, 
        link: str,
        published: str
    ) -> List[Dict]:
        """
        Use Groq AI to extract company information from article
        
        Args:
            title: Article title
            summary: Article summary/excerpt
            link: Article URL
            published: Publication date
        
        Returns:
            List of company dicts
        """
        try:
            logger.debug(f"[TC-Groq] Extracting from article: {title[:50]}...")
            
            # Build prompt for Groq
            prompt = f"""Extract company funding information from this TechCrunch article.

Title: {title}

Summary: {summary}

Extract all companies mentioned that raised funding. For each company provide:
1. company_name: Official company name
2. website: Company website URL (infer from company name if not mentioned, e.g., companyname.com)
3. funding_info: Amount raised and round type (e.g., "Raised $10M Series A")

Return ONLY valid JSON array:
[
  {{
    "company_name": "Company Name",
    "website": "https://company.com",
    "funding_info": "Raised $10M Series A",
    "funding_round": "Series A"
  }}
]

Important:
- Only include companies that raised funding (not investors or mentioned companies)
- Extract clean company names
- If funding amount/round not clear, use "Raised funding" as funding_info
- Ensure website URLs are valid (start with http:// or https://)
- Return empty array [] if no funded companies found
"""
            
            # Call Mistral API
            mistral_start = datetime.now()
            
            chat_response = self._call_mistral_with_retry(
                self.mistral_client.chat.complete,
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000
            )
            mistral_duration = (datetime.now() - mistral_start).total_seconds()
            
            result_text = chat_response.choices[0].message.content.strip()
            
            logger.debug(f"[TC-Mistral] API call completed in {mistral_duration:.2f}s")
            
            # Robust JSON extraction using regex
            json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(0)
            else:
                logger.warning(f"[TC-Mistral] No JSON array found in response")
                logger.debug(f"[TC-Mistral] Raw response: {result_text[:200]}")
                return []
            
            # Parse JSON
            try:
                companies = json.loads(result_text)
            except json.JSONDecodeError as je:
                logger.error(f"[TC-Groq] JSON decode failed: {je}")
                logger.debug(f"[TC-Groq] Raw response: {result_text[:300]}")
                return []
            
            if not isinstance(companies, list):
                logger.warning(f"[TC-Groq] Groq returned non-list: {type(companies)}")
                return []
            
            # Normalize and add source metadata
            normalized = []
            for company in companies:
                if not company.get('company_name'):
                    continue
                
                normalized.append({
                    'company_name': company['company_name'],
                    'website': self.normalize_website(company.get('website', '')),
                    'funding_info': company.get('funding_info', 'Raised funding'),
                    'source': 'TechCrunch',
                    'funding_round': company.get('funding_round'),
                    'article_url': link,
                    'published_date': published
                })
            
            logger.debug(f"[TC-Groq] Normalized {len(normalized)} companies from Groq response")
            return normalized
            
        except Exception as e:
            logger.error(f"[TC-Groq] Failed to extract from article: {type(e).__name__}: {e}")
            return []
