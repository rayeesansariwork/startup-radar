"""
News API Scraper - Scrapes funding news from multiple sources using NewsAPI.org
"""

import logging
import requests
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta


from .base_scraper import BaseScraper
from config import settings

logger = logging.getLogger(__name__)


class NewsAPIScraper(BaseScraper):
    """Scraper for funding news via NewsAPI.org (free tier: 100 requests/day)"""
    
    API_URL = "https://newsapi.org/v2/everything"
    
    # Funding-related keywords to search for
    FUNDING_KEYWORDS = [
        "raised funding",
        "Series A",
        "Series B",
        "seed funding",
        "venture capital",
        "funding round"
    ]
    
    # Tech news sources to prioritize
    TECH_SOURCES = [
        "techcrunch",
        "venturebeat",
        "the-verge",
        "wired",
        "ars-technica"
    ]
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("NewsAPI")
        # NewsAPI key should be in environment
        self.api_key = api_key or getattr(settings, 'newsapi_key', None)
        
        if not self.api_key:
            logger.warning("[NewsAPI] No API key configured - scraper will not work")
    
    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Scrape funding news from News API
        
        Args:
            limit: Optional limit on number of companies
        
        Returns:
            List of company dicts
        """
        start_time = datetime.now()
        groq_calls = 0
        groq_errors = 0
        
        try:
            if not self.api_key:
                logger.error("[NewsAPI] ❌ No API key available")
                return []
            
            logger.info(f"[NewsAPI] 🔍 Starting scrape (limit={limit or 'None'})")
            logger.debug(f"[NewsAPI] API URL: {self.API_URL}")
            logger.debug(f"[NewsAPI] Keywords: {', '.join(self.FUNDING_KEYWORDS[:3])}...")
            
            # Search for recent funding news (past 7 days)
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            logger.debug(f"[NewsAPI] Searching from: {from_date}")
            
            # Build search query
            query = " OR ".join([f'"{keyword}"' for keyword in self.FUNDING_KEYWORDS])
            
            # Make API request
            api_start = datetime.now()
            params = {
                'q': query,
                'from': from_date,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': min(limit or 20, 100),  # NewsAPI max is 100
                'apiKey': self.api_key
            }
            
            logger.debug(f"[NewsAPI] Request params: q={query[:50]}..., pageSize={params['pageSize']}")
            
            response = requests.get(self.API_URL, params=params, timeout=30)
            api_duration = (datetime.now() - api_start).total_seconds()
            
            logger.info(f"[NewsAPI] 📡 API response received in {api_duration:.2f}s (status={response.status_code})")
            logger.debug(f"[NewsAPI] Response size: {len(response.content)} bytes")
            
            if response.status_code != 200:
                logger.error(f"[NewsAPI] ❌ API returned non-200 status: {response.status_code}")
                logger.debug(f"[NewsAPI] Response: {response.text[:500]}")
                return []
            
            data = response.json()
            
            if data.get('status') != 'ok':
                logger.error(f"[NewsAPI] ❌ API returned error: {data.get('message', 'Unknown error')}")
                return []
            
            articles = data.get('articles', [])
            logger.info(f"[NewsAPI] 📰 Found {len(articles)} articles")
            
            if not articles:
                logger.warning(f"[NewsAPI] ⚠️ No articles found for funding keywords")
                return []
            
            # Process articles to extract company info
            all_companies = []
            articles_to_process = articles[:min(limit or 10, 20)]  # Limit Groq calls
            logger.debug(f"[NewsAPI] Processing {len(articles_to_process)} articles with Groq")
            
            for idx, article in enumerate(articles_to_process, 1):
                try:
                    title = article.get('title', '')
                    description = article.get('description', '')
                    url = article.get('url', '')
                    published = article.get('publishedAt', '')
                    source_name = article.get('source', {}).get('name', 'Unknown')
                    
                    logger.info(f"[NewsAPI] 📄 [{idx}/{len(articles_to_process)}] Processing: {title[:60]}...")
                    logger.debug(f"[NewsAPI]   Source: {source_name}")
                    logger.debug(f"[NewsAPI]   Published: {published}")
                    
                    # Extract company info using Groq
                    article_start = datetime.now()
                    companies = self._extract_companies_from_article(title, description, url, published, source_name)
                    article_duration = (datetime.now() - article_start).total_seconds()
                    groq_calls += 1
                    
                    if companies:
                        all_companies.extend(companies)
                        logger.info(f"[NewsAPI]   ✅ Extracted {len(companies)} companies in {article_duration:.2f}s")
                        logger.debug(f"[NewsAPI]   Companies: {[c['company_name'] for c in companies]}")
                    else:
                        logger.debug(f"[NewsAPI]   ⚠️ No companies extracted (took {article_duration:.2f}s)")
                    
                    # Rate limit Groq calls
                    if idx < len(articles_to_process):
                        self.rate_limit(0.5)
                    
                except Exception as e:
                    groq_errors += 1
                    logger.error(f"[NewsAPI]   ❌ Failed to process article: {type(e).__name__}: {e}")
                    logger.debug(f"[NewsAPI]   Article title: {title[:100]}")
                    continue
            
            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[NewsAPI] ✅ Scrape complete: {len(all_companies)} companies from {len(articles_to_process)} articles")
            logger.info(f"[NewsAPI] 📊 Stats: Groq calls={groq_calls}, errors={groq_errors}, duration={total_duration:.2f}s")
            
            # Apply final limit
            if limit and len(all_companies) > limit:
                logger.debug(f"[NewsAPI] Applying final limit: {limit} (had {len(all_companies)})")
                all_companies = all_companies[:limit]
            
            return all_companies
            
        except requests.exceptions.Timeout:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[NewsAPI] ⏱️ API request timed out after {duration:.2f}s")
            return []
        except requests.exceptions.RequestException as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[NewsAPI] 🌐 Network error after {duration:.2f}s: {e}", exc_info=True)
            return []
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[NewsAPI] ❌ Scraper failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []
    
    def _extract_companies_from_article(
        self, 
        title: str, 
        description: str, 
        url: str,
        published: str,
        source_name: str
    ) -> List[Dict]:
        """
        Use Groq AI to extract company information from article
        
        Args:
            title: Article title
            description: Article description/excerpt
            url: Article URL
            published: Publication date
            source_name: News source name
        
        Returns:
            List of company dicts
        """
        try:
            logger.debug(f"[NewsAPI-Groq] Extracting from article: {title[:50]}...")
            
            # Build prompt for Groq (similar to TechCrunch scraper)
            prompt = f"""Extract company funding information from this news article.

Title: {title}

Description: {description}

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
            
            logger.debug(f"[NewsAPI-Mistral] API call completed in {mistral_duration:.2f}s")
            logger.debug(f"[NewsAPI-Mistral] Response length: {len(result_text)} chars")
            
            # Clean markdown formatting
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            result_text = result_text.strip()
            
            # Parse JSON
            try:
                companies = json.loads(result_text)
            except json.JSONDecodeError as je:
                logger.error(f"[NewsAPI-Mistral] JSON decode failed: {je}")
                logger.debug(f"[NewsAPI-Mistral] Raw response: {result_text[:300]}")
                return []
            
            if not isinstance(companies, list):
                logger.warning(f"[NewsAPI-Mistral] Mistral returned non-list: {type(companies)}")
                logger.debug(f"[NewsAPI-Mistral] Value: {str(companies)[:200]}")
                return []
            
            # Normalize and add source metadata
            normalized = []
            for company in companies:
                if not company.get('company_name'):
                    logger.debug(f"[NewsAPI-Mistral] Skipping company with no name: {company}")
                    continue
                
                normalized.append({
                    'company_name': company['company_name'],
                    'website': self.normalize_website(company.get('website', '')),
                    'funding_info': company.get('funding_info', 'Raised funding'),
                    'source': f'NewsAPI ({source_name})',
                    'funding_round': company.get('funding_round'),
                    'article_url': url,
                    'published_date': published
                })
            
            logger.debug(f"[NewsAPI-Mistral] Normalized {len(normalized)} companies from Mistral response")
            return normalized
            
        except Exception as e:
            logger.error(f"[NewsAPI-Mistral] Failed to extract from article: {type(e).__name__}: {e}")
            logger.debug(f"[NewsAPI-Mistral] Article: {title[:100]}")
            return []
