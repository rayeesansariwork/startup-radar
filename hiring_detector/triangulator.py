"""
HiringTriangulator - Intelligence-first career page discovery.

Implements the 3-priority "Triangulation" strategy from context.md:
  Priority 1: ATS Backdoor  — Serper search on greenhouse/lever/ashby
  Priority 2: Sitemap Surgeon — Parse sitemap.xml for career URLs
  Priority 3: Organic Search  — site:domain (careers OR jobs) fallback

Rules (from context.md):
  - Do NOT remove randomized sleep (safety).
  - Do NOT replace requests with selenium.
  - Always prefer "Search First" over "Crawl All".
"""

import logging
import random
import re
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Known ATS domains (The "Backdoor") — from context.md
ATS_PROVIDERS = {
    "greenhouse.io": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "jobs.lever.co": "Lever",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "jobs.ashbyhq.com": "Ashby",
    "workable.com": "Workable",
    "apply.workable.com": "Workable",
    "breezy.hr": "Breezy",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
]


class HiringTriangulator:
    """
    Intelligence-first career page finder.

    Usage:
        t = HiringTriangulator()
        url, method = t.triangulate("openai.com")
        # url  → "https://boards.greenhouse.io/openai"
        # method → "ATS_Backdoor"
    """

    SERPER_ENDPOINT = "https://google.serper.dev/search"

    def __init__(self, serper_api_key: str = None):
        # Prefer injected key, then env/settings
        if serper_api_key:
            self._api_key = serper_api_key
        else:
            try:
                from config import settings
                self._api_key = settings.serper_api_key
            except Exception:
                import os
                self._api_key = os.getenv("SERPER_API_KEY", "")

        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def triangulate(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Find the career/jobs URL for a domain using the triangulation hierarchy.

        Args:
            domain: bare domain, e.g. "openai.com" or "stripe.com"

        Returns:
            (url, method) where method is one of:
              "ATS_Backdoor" | "Sitemap_Discovery" | "Google_Organic" | None
        """
        domain = self._clean_domain(domain)
        logger.info(f"🔺 Triangulating career page for: {domain}")

        # Priority 1 — ATS Backdoor
        url, method = self._find_ats_url(domain)
        if url:
            logger.info(f"✅ P1 ATS Backdoor → {url}")
            return url, method

        # Priority 2 — Sitemap Surgeon
        url, method = self._check_sitemap(domain)
        if url:
            logger.info(f"✅ P2 Sitemap Discovery → {url}")
            return url, method

        # Priority 3 — Organic Search Fallback
        url, method = self._find_generic_url(domain)
        if url:
            logger.info(f"✅ P3 Google Organic → {url}")
            return url, method

        logger.warning(f"⚠️ Triangulation failed for {domain}")
        return None, None

    # ------------------------------------------------------------------
    # Priority 1: ATS Backdoor
    # ------------------------------------------------------------------

    def _find_ats_url(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """Search Serper for company on known ATS platforms."""
        company = domain.split(".")[0]
        query = f'site:greenhouse.io OR site:lever.co OR site:ashbyhq.com "{company}"'
        results = self._search_serper(query, num=5)

        for r in results:
            link = r.get("link", "")
            if any(ats in link for ats in ATS_PROVIDERS):
                return link, "ATS_Backdoor"

        return None, None

    # ------------------------------------------------------------------
    # Priority 2: Sitemap Surgeon
    # ------------------------------------------------------------------

    def _check_sitemap(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetch sitemap.xml and look for career/jobs URLs."""
        sitemap_url = f"https://{domain}/sitemap.xml"
        try:
            res = self._session.get(
                sitemap_url,
                headers=self._get_headers(),
                timeout=10,
            )
            if res.status_code == 200:
                urls = re.findall(r"<loc>(.*?)</loc>", res.text)
                for u in urls:
                    if "career" in u.lower() or "jobs" in u.lower() or "join" in u.lower():
                        return u, "Sitemap_Discovery"
        except Exception as e:
            logger.debug(f"Sitemap fetch failed for {domain}: {e}")

        return None, None

    # ------------------------------------------------------------------
    # Priority 3: Organic Search Fallback
    # ------------------------------------------------------------------

    def _find_generic_url(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """Fallback: site:domain (careers OR jobs) via Serper."""
        query = f"site:{domain} (careers OR jobs)"
        results = self._search_serper(query, num=5)
        if results:
            return results[0].get("link"), "Google_Organic"
        return None, None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _search_serper(self, query: str, num: int = 5) -> list:
        """Query Serper.dev and return organic results list."""
        if not self._api_key:
            logger.warning("No Serper API key — skipping search")
            return []
        try:
            headers = {
                "X-API-KEY": self._api_key,
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
            logger.warning(f"Serper returned {res.status_code} for: {query}")
        except Exception as e:
            logger.error(f"Serper search error: {e}")
        return []

    def _get_headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }

    def _sleep(self, min_s: float = 2, max_s: float = 5) -> None:
        """Randomized sleep — do NOT remove (safety rule from context.md)."""
        time.sleep(random.uniform(min_s, max_s))

    @staticmethod
    def _clean_domain(domain: str) -> str:
        """Strip protocol and www prefix."""
        domain = domain.replace("https://", "").replace("http://", "")
        domain = domain.replace("www.", "")
        return domain.split("/")[0].strip()
