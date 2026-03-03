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
from urllib.parse import urlparse

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

        company_lower = company.lower()

        for r in results:
            link = r.get("link", "")
            if any(ats in link for ats in ATS_PROVIDERS):
                if not self._is_ats_job_board_link(link):
                    logger.debug("Skipping ATS non-jobboard link: %s", link)
                    continue
                # Validate ATS link belongs to this company (avoid substring false matches:
                # e.g. "dig" matching "digrestaurants").
                if self._ats_link_matches_company(company_lower, link):
                    return link, "ATS_Backdoor"
                else:
                    logger.debug(
                        "Skipping ATS link (wrong company): %s", link
                    )

        return None, None

    # ------------------------------------------------------------------
    # Priority 2: Sitemap Surgeon
    # ------------------------------------------------------------------

    # URL segments that indicate this is NOT a job listing page
    _SITEMAP_BLOCKLIST = (
        "/blog/", "/news/", "/article/", "/press/",
        "/media/", "/podcast/", "/training/", "/post/",
        "/resources/", "/learn/",
    )

    def _check_sitemap(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetch sitemap.xml and look for actual career/jobs listing URLs."""
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
                    u_lower = u.lower()
                    if "career" in u_lower or "jobs" in u_lower or "join" in u_lower:
                        # Skip blog posts / articles that mention careers in their URL
                        if any(block in u_lower for block in self._SITEMAP_BLOCKLIST):
                            logger.debug("Sitemap: skipping non-listing URL: %s", u)
                            continue
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

    @staticmethod
    def _ats_link_matches_company(company: str, link: str) -> bool:
        """
        Determine whether ATS URL likely belongs to the target company.
        Uses token-level matching, with limited prefix fallback for longer names.
        """
        if not company or not link:
            return False

        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        path = (parsed.path or "").lower()

        # Extract alphanumeric tokens from host + path.
        host_tokens = [t for t in re.split(r"[^a-z0-9]+", host) if t]
        path_tokens = [t for t in re.split(r"[^a-z0-9]+", path) if t]
        if not (host_tokens or path_tokens):
            return False

        company = company.lower().strip()

        # Strong signal: exact host token match.
        if company in host_tokens:
            return True

        stopwords = {
            "boards", "jobs", "job", "careers", "career", "postings", "posting",
            "api", "v0", "v1", "products", "product", "store", "company",
        }
        path_candidates = [t for t in path_tokens if t not in stopwords]
        if not path_candidates:
            return False

        # For short company names, require exact first candidate match to avoid false positives.
        if len(company) < 5:
            return path_candidates[0] == company

        if company in path_candidates:
            return True

        # Prefix fallback for longer names only.
        if len(company) >= 5:
            for token in path_candidates:
                if token.startswith(company):
                    return True

        return False

    @staticmethod
    def _is_ats_job_board_link(link: str) -> bool:
        """Allow only known ATS job-board URL shapes, not generic marketing/store pages."""
        try:
            parsed = urlparse(link)
            host = (parsed.netloc or "").lower()
            path = (parsed.path or "").lower()
        except Exception:
            return False

        if "greenhouse.io" in host:
            return (
                host.startswith("boards.greenhouse.io")
                or host.startswith("job-boards.greenhouse.io")
                or "/boards/" in path
            )
        if "lever.co" in host:
            return host.startswith("jobs.lever.co") or "/postings/" in path
        if "ashbyhq.com" in host:
            return host.startswith("jobs.ashbyhq.com")
        if "workable.com" in host:
            return host.startswith("apply.workable.com") or "/jobs/" in path
        return False
