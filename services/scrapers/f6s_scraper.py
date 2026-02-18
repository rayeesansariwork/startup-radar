"""
Funding News Scraper (formerly F6S) - Discovers funded companies from startup
funding news roundups via Serper search + Mistral extraction.

F6S search via Serper consistently returns accelerator program pages and startup
directory listings, NOT individual funded company pages with funding data in snippets.
This scraper pivots to targeting funding news roundup articles from reliable sources
(AlleyWatch, BusinessWire, PRNewswire, Axios) where funding data IS present
in the title/snippet, making Mistral extraction reliable.
"""

import logging
import json
import requests
from typing import List, Dict, Optional
from datetime import datetime

from .base_scraper import BaseScraper
from config import settings

logger = logging.getLogger(__name__)


class F6SScraper(BaseScraper):
    """Scraper for funded companies via funding news roundups (Serper + Mistral)"""

    SERPER_ENDPOINT = "https://google.serper.dev/search"

    # Target funding news roundup articles — these have rich snippets with
    # company names, amounts, and round types that Mistral can reliably extract.
    # Deliberately diverse to avoid overlap with VentureBeat/TechCrunch/GNews scrapers.
    SEARCH_QUERIES = [
        'startup funding round raised million 2026 site:alleywatch.com',
        'startup "seed round" OR "series a" raised million 2026 site:axios.com',
        '"raised" "million" startup funding round 2026 site:businesswire.com OR site:prnewswire.com',
    ]

    # Minimum funding signals required in title+snippet to bother calling Mistral
    FUNDING_SIGNALS = ['raised', 'funding', 'series', 'seed', 'million', 'investment', 'round', 'secured']

    def __init__(self):
        super().__init__("F6S")
        self.serper_api_key = settings.serper_api_key

    def scrape(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Discover funded companies from funding news roundups via Serper + Mistral.

        Args:
            limit: Optional limit on number of companies to return

        Returns:
            List of normalized company dicts
        """
        start_time = datetime.now()
        mistral_calls = 0
        mistral_errors = 0

        try:
            logger.info(f"[F6S] 🔍 Starting scrape (limit={limit or 'None'})")

            # Step 1: Collect search results from all queries
            all_results = []
            for query in self.SEARCH_QUERIES:
                results = self._search_serper(query, num=10)
                if results:
                    all_results.extend(results)
                    logger.info(f"[F6S] 📡 Query '{query[:55]}...' → {len(results)} results")
                else:
                    logger.warning(f"[F6S] ⚠️ No results for: {query[:55]}")

            if not all_results:
                logger.warning("[F6S] ⚠️ No search results from Serper — check API key or queries")
                return []

            # Step 2: Deduplicate by URL
            seen_urls = set()
            unique_results = []
            for r in all_results:
                url = r.get('link', '')
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_results.append(r)

            logger.info(f"[F6S] 📦 {len(unique_results)} unique results after dedup")

            # Step 3: Per-result extraction with pre-filter
            max_to_process = min(limit or 20, len(unique_results))
            results_to_process = unique_results[:max_to_process]

            all_companies = []
            seen_names: set = set()

            for idx, result in enumerate(results_to_process, 1):
                title = result.get('title', '')
                snippet = result.get('snippet', '')
                link = result.get('link', '')
                combined = (title + ' ' + snippet).lower()

                # Pre-filter: skip results with no funding signals
                if not any(sig in combined for sig in self.FUNDING_SIGNALS):
                    logger.debug(f"[F6S] ⏭️ [{idx}] Skipping (no funding signals): {title[:60]}")
                    continue

                logger.info(f"[F6S] 📄 [{idx}/{len(results_to_process)}] Processing: {title[:65]}...")

                mistral_calls += 1
                try:
                    companies = self._extract_companies_from_result(title, snippet, link)
                    for company in companies:
                        name = company.get('company_name', '').lower().strip()
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_companies.append(company)
                            logger.info(f"[F6S]   ✅ Extracted: {company['company_name']} ({company.get('funding_info', 'N/A')})")
                except Exception as e:
                    mistral_errors += 1
                    logger.warning(f"[F6S]   ⚠️ Extraction failed for '{title[:50]}': {e}")

                # Early exit if limit reached
                if limit and len(all_companies) >= limit:
                    logger.info(f"[F6S] 🎯 Reached limit of {limit}, stopping early")
                    break

            total_duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[F6S] ✅ Scrape complete: {len(all_companies)} companies in {total_duration:.2f}s")
            logger.info(f"[F6S] 📊 Stats: Mistral calls={mistral_calls}, errors={mistral_errors}, duration={total_duration:.2f}s")

            return all_companies[:limit] if limit else all_companies

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[F6S] ❌ Scraper failed after {duration:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            return []

    def _search_serper(self, query: str, num: int = 10) -> list:
        """Query Serper.dev and return organic results."""
        try:
            headers = {
                "X-API-KEY": self.serper_api_key,
                "Content-Type": "application/json",
            }
            payload = {"q": query, "num": num}
            res = requests.post(
                self.SERPER_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=15,
            )
            if res.status_code == 200:
                return res.json().get("organic", [])
            logger.warning(f"[F6S] Serper returned {res.status_code} for: {query[:55]}")
        except Exception as e:
            logger.error(f"[F6S] Serper request error: {e}")
        return []

    def _extract_companies_from_result(self, title: str, snippet: str, url: str) -> List[Dict]:
        """
        Use Mistral AI to extract funded company info from a single search result.
        Returns [] if no funded company is found or result is not relevant.
        """
        try:
            prompt = f"""Extract funded startup information from this news search result.

Title: {title}
Snippet: {snippet}
URL: {url}

Instructions:
- If this describes one or more startups that received funding, extract each one.
- Only extract STARTUPS/COMPANIES that received funding (not VC firms, accelerators, or investors).
- Return a JSON array. Return [] if no funded company is clearly described.

For each funded company, return:
{{
  "company_name": "Exact company name",
  "website": "https://company.com (infer from company name if not in snippet)",
  "funding_info": "e.g. Raised $10M Series A",
  "funding_round": "e.g. Seed / Series A / Series B",
  "description": "One sentence: what does this company do?"
}}

Return ONLY the JSON array, no explanation."""

            chat_response = self._call_mistral_with_retry(
                self.mistral_client.chat.complete,
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
            )

            raw = chat_response.choices[0].message.content.strip()

            # Strip markdown code fences if present
            if '```json' in raw:
                raw = raw.split('```json')[1].split('```')[0]
            elif '```' in raw:
                raw = raw.split('```')[1].split('```')[0]
            raw = raw.strip()

            try:
                companies = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.debug(f"[F6S-Mistral] JSON parse failed: {e} | Raw: {raw[:200]}")
                return []

            if not isinstance(companies, list):
                return []

            # Normalize and validate each entry
            normalized = []
            for c in companies:
                name = (c.get('company_name') or '').strip()
                if not name:
                    continue
                normalized.append({
                    'company_name': name,
                    'website': self.normalize_website(c.get('website', '')),
                    'funding_info': c.get('funding_info') or 'Raised funding',
                    'source': 'F6S',
                    'funding_round': c.get('funding_round') or None,
                    'description': (c.get('description') or '').strip(),
                })

            return normalized

        except Exception as e:
            logger.error(f"[F6S-Mistral] Extraction error: {type(e).__name__}: {e}")
            return []