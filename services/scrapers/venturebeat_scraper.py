"""
VentureBeat RSS Scraper - Scrapes funding news from VentureBeat RSS feed
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


class VentureBeatScraper(BaseScraper):
    """Scraper for funding news via VentureBeat RSS"""
    
    # VentureBeat has multiple RSS feeds - using AI/funding categories
    RSS_URLS = [
        "https://venturebeat.com/category/ai/feed/",
        "https://venturebeat.com/category/business/feed/"
    ]
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    def __init__(self):
        super().__init__("VentureBeat")
    
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Scrape funding news from VentureBeat RSS feeds
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        start_time = datetime.now()
        groq_calls = 0
        groq_errors = 0
        
        try:
            logger.info(f"[VB] 🔍 Starting scrape (limit={limit or 'None'})")
            logger.debug(f"[VB] RSS URLS: {len(self.RSS_URLS)} feeds")
            
            # Fetch all RSS feeds
            all_entries = []
            for rss_url in self.RSS_URLS:
                try:
                    logger.debug(f"[VB] Fetching: {rss_url}")
                    
                    # Use requests with headers
                    try:
                        response = requests.get(rss_url, headers=self.HEADERS, timeout=15)
                        response.raise_for_status()
                        feed_content = response.content
                    except Exception as e:
                        logger.error(f"[VB]   Failed to fetch {rss_url}: {e}")
                        continue
                        
                    feed = feedparser.parse(feed_content)
                    
                    if not feed.bozo and feed.entries:
                        all_entries.extend(feed.entries)
                        logger.debug(f"[VB]   Got {len(feed.entries)} entries")
                    else:
                        logger.warning(f"[VB]   No entries from {rss_url} (Bozo: {feed.bozo})")
                except Exception as e:
                    logger.error(f"[VB]   Failed to parse {rss_url}: {e}")
                    continue
            
            if not all_entries:
                logger.warning(f"[VB] ⚠️ No entries found in any VentureBeat RSS feed")
                return []
            
            logger.info(f"[VB] 📰 Found {len(all_entries)} total articles from {len(self.RSS_URLS)} feeds")
            
            # Filter for funding-related articles
            funding_articles = []
            for entry in all_entries:
                title = entry.get('title', '').lower()
                summary = entry.get('summary', entry.get('description', '')).lower()
                
                # Check if article is about funding
                funding_keywords = ['funding', 'raises', 'raised', 'series', 'seed', 'investment', 'capital', 'round', 'million', 'billion']
                if any(keyword in title or keyword in summary for keyword in funding_keywords):
                    funding_articles.append(entry)
            
            logger.info(f"[VB] 🎯 Filtered to {len(funding_articles)} funding-related articles")
            
            # Limit articles to process
            max_articles = min(limit or 10, 20)
            articles_to_process = funding_articles[:max_articles]
            logger.debug(f"[VB] Processing {len(articles_to_process)} articles (max={max_articles})")
            
            # Extract companies from articles using Groq
            all_companies = []
            
            for idx, entry in enumerate(articles_to_process, 1):
                try:
                    title = entry.get('title', '')
                    summary = entry.get('summary', entry.get('description', ''))
                    link = entry.get('link', '')
                    published = entry.get('published', '')
                    
                    logger.info(f"[VB] 📄 [{idx}/{len(articles_to_process)}] Processing: {title[:60]}...")
                    logger.debug(f"[VB]   Published: {published}")
                    
                    # Extract company info using Groq
                    article_start = datetime.now()
                    companies = self._extract_companies_from_article(title, summary, link, published)
                    article_duration = (datetime.now() - article_start).total_seconds()
                    groq_calls += 1
                    
                    if companies:
                        all_companies.extend(companies)
                        logger.info(f"[VB]   ✅ Extracted {len(companies)} companies in {article_duration:.2f}s")
                        logger.debug(f"[VB]   Companies: {[c['company_name'] for c in companies]}")
                    else:
                        logger.debug(f"[VB]   ⚠️ No companies extracted (took {article_duration:.2f}s)")
                    
                    # Rate limit Groq calls
                    if idx < len(articles_to_process):
                        self.rate_limit(0.5)
                    
                except Exception as e:
                    groq_errors += 1
                    logger.error(f"[VB]   ❌ Failed to process article: {type(e).__name__}: {e}")
                    continue
            
            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[VB] ✅ Scrape complete: {len(all_companies)} companies from {len(articles_to_process)} articles")
            logger.info(f"[VB] 📊 Stats: Groq calls={groq_calls}, errors={groq_errors}, duration={total_duration:.2f}s")
            
            # Apply final limit
            if limit and len(all_companies) > limit:
                logger.debug(f"[VB] Applying final limit: {limit} (had {len(all_companies)})")
                all_companies = all_companies[:limit]
            
            return all_companies
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[VB] ❌ Scraper failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []
    
    def _extract_companies_from_article(
        self, 
        title: str, 
        summary: str, 
        url: str,
        published: str
    ) -> List[Dict]:
        """Use Groq AI to extract company information from article"""
        try:
            logger.debug(f"[VB-Groq] Extracting from article: {title[:50]}...")
            
            prompt = f"""Extract company funding information from this VentureBeat article.

Title: {title}

Summary: {summary}

Extract all companies mentioned that raised funding. For each company provide:
1. company_name: Official company name
2. website: Company website URL (infer if not mentioned)
3. funding_info: Amount raised and round type

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
- Only include companies that raised funding
- Extract clean company names
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
            
            logger.debug(f"[VB-Mistral] API call completed in {mistral_duration:.2f}s")
            
            # Robust JSON extraction using regex
            json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
            if json_match:
                result_text = json_match.group(0)
            else:
                logger.warning(f"[VB-Mistral] No JSON array found in response")
                return []
            
            # Parse JSON
            try:
                companies = json.loads(result_text)
            except json.JSONDecodeError as e:
                logger.error(f"[VB-Mistral] JSON decode failed: {e}")
                logger.debug(f"[VB-Mistral] Raw response: {result_text[:500]}")
                return []
            
            if not isinstance(companies, list):
                logger.warning(f"[VB-Mistral] Response is not a list")
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
                    'source': 'VentureBeat',
                    'funding_round': company.get('funding_round'),
                    'article_url': url,
                    'published_date': published
                })
            
            logger.debug(f"[VB-Mistral] Normalized {len(normalized)} companies")
            return normalized
            
        except Exception as e:
            logger.error(f"[VB-Mistral] Failed to extract: {type(e).__name__}: {e}")
            return []
