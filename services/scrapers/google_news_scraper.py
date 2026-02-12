"""
Google News RSS Scraper - Scrapes funding news from Google News aggregation
"""

import logging
import feedparser
import json
from typing import List, Dict, Optional
from datetime import datetime


from .base_scraper import BaseScraper
from config import settings

logger = logging.getLogger(__name__)


class GoogleNewsScraper(BaseScraper):
    """Scraper for funding news via Google News RSS (aggregates all news sources)"""
    
    # Google News RSS search query for startup funding
    RSS_URL = (
        "https://news.google.com/rss/search?"
        "q=startup+funding+OR+raised+OR+Series+A+OR+Series+B+OR+seed+round+OR+venture+capital"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    
    def __init__(self):
        super().__init__("Google News")
    
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Scrape funding news from Google News RSS
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        start_time = datetime.now()
        groq_calls = 0
        groq_errors = 0
        
        try:
            logger.info(f"[GNews] 🔍 Starting scrape (limit={limit or 'None'})")
            logger.debug(f"[GNews] RSS URL: {self.RSS_URL[:100]}...")
            
            # Fetch RSS feed
            rss_start = datetime.now()
            feed = feedparser.parse(self.RSS_URL)
            rss_duration = (datetime.now() - rss_start).total_seconds()
            
            logger.info(f"[GNews] 📡 RSS feed parsed in {rss_duration:.2f}s")
            logger.debug(f"[GNews] Feed bozo: {feed.bozo}, version: {feed.get('version', 'N/A')}")
            
            if feed.bozo:
                logger.warning(f"[GNews] ⚠️ RSS feed has bozo flag (malformed): {feed.get('bozo_exception', 'Unknown')}")
            
            if not feed.entries:
                logger.warning(f"[GNews] ⚠️ No entries found in Google News RSS feed")
                logger.debug(f"[GNews] Feed keys: {list(feed.keys())}")
                return []
            
            logger.info(f"[GNews] 📰 Found {len(feed.entries)} articles in RSS feed")
            
            # Limit articles to process
            max_articles = min(limit or 15, 30)
            articles_to_process = feed.entries[:max_articles]
            logger.debug(f"[GNews] Processing {len(articles_to_process)} articles (max={max_articles})")
            
            # Extract companies from articles using Groq
            all_companies = []
            
            for idx, entry in enumerate(articles_to_process, 1):
                try:
                    title = entry.get('title', '')
                    summary = entry.get('summary', entry.get('description', ''))
                    link = entry.get('link', '')
                    published = entry.get('published', '')
                    source_name = entry.get('source', {}).get('title', 'Unknown') if hasattr(entry.get('source', {}), 'get') else 'Unknown'
                    
                    logger.info(f"[GNews] 📄 [{idx}/{len(articles_to_process)}] Processing: {title[:60]}...")
                    logger.debug(f"[GNews]   Source: {source_name}")
                    logger.debug(f"[GNews]   Published: {published}")
                    
                    # Extract company info using Groq
                    article_start = datetime.now()
                    companies = self._extract_companies_from_article(title, summary, link, published, source_name)
                    article_duration = (datetime.now() - article_start).total_seconds()
                    groq_calls += 1
                    
                    if companies:
                        all_companies.extend(companies)
                        logger.info(f"[GNews]   ✅ Extracted {len(companies)} companies in {article_duration:.2f}s")
                        logger.debug(f"[GNews]   Companies: {[c['company_name'] for c in companies]}")
                    else:
                        logger.debug(f"[GNews]   ⚠️ No companies extracted (took {article_duration:.2f}s)")
                    
                    # Rate limit Groq calls
                    if idx < len(articles_to_process):
                        self.rate_limit(0.5)
                    
                except Exception as e:
                    groq_errors += 1
                    logger.error(f"[GNews]   ❌ Failed to process article: {type(e).__name__}: {e}")
                    logger.debug(f"[GNews]   Article title: {title[:100]}")
                    continue
            
            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[GNews] ✅ Scrape complete: {len(all_companies)} companies from {len(articles_to_process)} articles")
            logger.info(f"[GNews] 📊 Stats: Groq calls={groq_calls}, errors={groq_errors}, duration={total_duration:.2f}s")
            
            # Apply final limit
            if limit and len(all_companies) > limit:
                logger.debug(f"[GNews] Applying final limit: {limit} (had {len(all_companies)})")
                all_companies = all_companies[:limit]
            
            return all_companies
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[GNews] ❌ Scraper failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []
    
    def _extract_companies_from_article(
        self, 
        title: str, 
        summary: str, 
        url: str,
        published: str,
        source_name: str
    ) -> List[Dict]:
        """
        Use Groq AI to extract company information from article
        """
        try:
            logger.debug(f"[GNews-Groq] Extracting from article: {title[:50]}...")
            
            # Build prompt for Groq
            prompt = f"""Extract company funding information from this news article.

Title: {title}

Summary: {summary}

Extract all companies mentioned that raised funding. For each company provide:
1. company_name: Official company name
2. website: Company website URL (infer from company name if not mentioned)
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
- Only include companies that raised funding (not investors)
- Extract clean company names
- If funding amount/round not clear, use "Raised funding"
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
            
            logger.debug(f"[GNews-Mistral] API call completed in {mistral_duration:.2f}s")
            logger.debug(f"[GNews-Mistral] Response length: {len(result_text)} chars")
            
            # Clean markdown formatting (Mistral might wrap in markdown too)
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            result_text = result_text.strip()
            
            # Parse JSON
            try:
                companies = json.loads(result_text)
            except json.JSONDecodeError as je:
                logger.error(f"[GNews-Groq] JSON decode failed: {je}")
                logger.debug(f"[GNews-Groq] Raw response: {result_text[:300]}")
                return []
            
            if not isinstance(companies, list):
                logger.warning(f"[GNews-Groq] Groq returned non-list: {type(companies)}")
                logger.debug(f"[GNews-Groq] Value: {str(companies)[:200]}")
                return []
            
            # Normalize and add source metadata
            normalized = []
            for company in companies:
                if not company.get('company_name'):
                    logger.debug(f"[GNews-Groq] Skipping company with no name: {company}")
                    continue
                
                normalized.append({
                    'company_name': company['company_name'],
                    'website': self.normalize_website(company.get('website', '')),
                    'funding_info': company.get('funding_info', 'Raised funding'),
                    'source': f'Google News ({source_name})',
                    'funding_round': company.get('funding_round'),
                    'article_url': url,
                    'published_date': published
                })
            
            logger.debug(f"[GNews-Groq] Normalized {len(normalized)} companies from Groq response")
            return normalized
            
        except Exception as e:
            logger.error(f"[GNews-Groq] Failed to extract from article: {type(e).__name__}: {e}")
            logger.debug(f"[GNews-Groq] Article: {title[:100]}")
            return []
