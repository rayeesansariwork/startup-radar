# context.md

## 1. Project Overview
**Goal:** Build a production-ready, automated "Hiring Signal" detector.
**Purpose:** B2B Lead Generation. We need to identify if a specific company (by domain) is actively hiring for engineering/tech roles to pitch them services.
**Core Philosophy:** "Intelligence over Brute Force." Instead of blindly scraping complex corporate homepages, we triangulate the specific "Careers" page or third-party Applicant Tracking System (ATS) URL using search APIs and sitemaps.

## 2. Technical Constraints & Requirements
* **Environment:** Production Linux Server (e.g., AWS, DigitalOcean).
* **Language:** Python 3.x.
* **Dependencies:** `requests`, `beautifulsoup4`, `google-search-results` (or generic `requests` for Serper.dev).
* **Restriction:** **Avoid Headless Browsers (Playwright/Selenium)** if possible. They are resource-heavy and prone to crashing in production. Use them only as a last resort.
* **Ethics:** Must respect rate limits, use randomized sleep delays, and rotate User-Agents to avoid IP bans.

## 3. The "Triangulation" Strategy (The Intelligence Layer)
To detect hiring without getting blocked, the system follows this strict hierarchy:

### Priority 1: The ATS Backdoor (High Success, Low Risk)
Most tech companies host jobs on external domains which are easier to scrape and rarely block bots.
* **Target:** `boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `apply.workable.com`.
* **Action:** Use Google Search (Serper.dev) to find these specifically for the target domain (e.g., `site:greenhouse.io "openai"`).

### Priority 2: The Sitemap Surgeon (Polite Discovery)
* **Target:** `domain.com/sitemap.xml`
* **Action:** Parse the XML to find URLs containing "careers", "jobs", or "join-us". This is "white-hat" and extremely reliable.

### Priority 3: The Organic Search (Fallback)
* **Action:** If 1 & 2 fail, search Google for `site:domain.com (careers OR jobs)`.
* **Risk:** Higher chance of parsing errors due to custom HTML/JS on the main site.

## 4. Implementation Code (`HiringDetective`)
Below is the complete, robust Python implementation. Any LLM working on this project must preserve this logic.

```python
import requests
import json
import time
import random
import re
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
SERPER_API_KEY = "YOUR_KEY_HERE"

# Known ATS domains that are easy to scrape (The "Backdoor")
ATS_PROVIDERS = {
    "greenhouse.io": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "jobs.lever.co": "Lever",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "workable.com": "Workable",
    "breezy.hr": "Breezy"
}

# Rotate User Agents to avoid simple IP blocks
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
]

class HiringDetective:
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        
    def _get_headers(self):
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

    def _sleep(self, min_s=3, max_s=7):
        """Randomized sleep to act human."""
        time.sleep(random.uniform(min_s, max_s))

    def search_serper(self, query):
        """Queries Google via Serper.dev"""
        url = "[https://google.serper.dev/search](https://google.serper.dev/search)"
        payload = json.dumps({"q": query, "num": 5})
        headers = {'X-API-KEY': self.api_key, 'Content-Type': 'application/json'}
        try:
            res = requests.post(url, headers=headers, data=payload)
            return res.json().get('organic', [])
        except:
            return []

    # --- STRATEGY 1: FIND ATS ---
    def find_ats_url(self, domain):
        company = domain.split('.')[0]
        # "Smart" Query: Look for the company on specific ATS domains
        query = f'site:greenhouse.io OR site:lever.co OR site:ashbyhq.com "{company}"'
        results = self.search_serper(query)
        for r in results:
            if any(ats in r['link'] for ats in ATS_PROVIDERS):
                return r['link'], "ATS_Backdoor"
        return None, None

    # --- STRATEGY 2: CHECK SITEMAP ---
    def check_sitemap(self, domain):
        try:
            sitemap_url = f"https://{domain}/sitemap.xml"
            res = self.session.get(sitemap_url, headers=self._get_headers(), timeout=10)
            if res.status_code == 200:
                urls = re.findall(r'<loc>(.*?)</loc>', res.text)
                for u in urls:
                    if 'career' in u or 'jobs' in u:
                        return u, "Sitemap_Discovery"
        except:
            pass
        return None, None

    # --- STRATEGY 3: FALLBACK SEARCH ---
    def find_generic_url(self, domain):
        results = self.search_serper(f'site:{domain} (careers OR jobs)')
        if results:
            return results[0]['link'], "Google_Organic"
        return None, None

    # --- ANALYSIS ENGINE ---
    def analyze_hiring(self, url):
        self._sleep()
        try:
            res = self.session.get(url, headers=self._get_headers(), timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            text = soup.get_text().lower()
            
            # Simple Heuristics
            keywords = ['engineer', 'developer', 'data scientist', 'product manager']
            jobs_found = []
            
            # Check for ATS-specific structures (e.g. div.opening) or generic links
            links = soup.find_all('a', href=True)
            for link in links:
                ltext = link.get_text(" ", strip=True)
                if 5 < len(ltext) < 50 and any(k in ltext.lower() for k in keywords):
                    jobs_found.append(ltext)
            
            is_hiring = len(jobs_found) > 0 or "open positions" in text
            return {
                "hiring": is_hiring,
                "url": url,
                "jobs_preview": list(set(jobs_found))[:5]
            }
        except Exception as e:
            return {"hiring": False, "error": str(e)}

    # --- MAIN RUNNER ---
    def investigate(self, domain):
        # 1. Try ATS
        url, method = self.find_ats_url(domain)
        # 2. Try Sitemap
        if not url: url, method = self.check_sitemap(domain)
        # 3. Try Generic
        if not url: url, method = self.find_generic_url(domain)
        
        if url:
            print(f"Found Career Page via {method}: {url}")
            return self.analyze_hiring(url)
        return {"hiring": False, "error": "No URL found"}





# Deployment Instructions for you
# If asking another LLM to modify or extend this:

# Do NOT remove the randomized sleep (Safety).

# Do NOT replace requests with selenium unless explicitly asked (Complexity).

# Focus on improving the ATS_PROVIDERS list or the regex logic in analyze_hiring.

# Always prefer the "Search First" approach over "Crawl All" approach.

---

## 5. Implemented: Triangulation Strategy (`HiringTriangulator`)
The triangulation strategy from the `HiringDetective` above has been implemented in `hiring_detector/triangulator.py` and integrated into the `EnhancedHiringChecker`.

### How It Works
When `EnhancedHiringChecker._find_career_page()` is called, it now runs `HiringTriangulator.triangulate(domain)` **first**, before falling back to the existing URL pattern-guessing loop.

### Triangulation Hierarchy
1. **ATS Backdoor** → Serper search: `site:greenhouse.io OR site:lever.co OR site:ashbyhq.com "company"`
2. **Sitemap Surgeon** → Fetches `domain.com/sitemap.xml`, finds career/jobs URLs via `<loc>` tag regex
3. **Organic Search** → Serper search: `site:domain (careers OR jobs)`

### Files
- `hiring_detector/triangulator.py` — `HiringTriangulator` class
- `hiring_detector/checker.py` — Integration point in `_find_career_page()`
- `hiring_detector/__init__.py` — Exports both `EnhancedHiringChecker` and `HiringTriangulator`

---

## 6. Implemented: Custom Mail Generation
The `/api/hiring` endpoint now generates a personalized B2B outreach email for every company that `is_hiring: true`.

### How It Works
After hiring results are collected, the system calls `JobAnalyzer.generate_outreach_mail()` which sends the company name + job roles to Mistral AI. Mistral generates a short, professional cold email from Gravity (info@gravityer.com) mentioning the specific team they're scaling.

### Response Shape
```json
{
  "company_name": "Kavak",
  "is_hiring": true,
  "job_roles": ["Senior Back End Engineer", ...],
  "custom_mail": {
    "subject": "Scaling your Backend team?",
    "body": "Hey Kavak team,\n\nFirst of all, congrats on the funding...",
    "team_focus": "Backend Engineering"
  },
  "career_page_url": "...",
  "hiring_summary": "...",
  "detection_method": "..."
}
```

### Files
- `hiring_detector/analyzer.py` — `JobAnalyzer.generate_outreach_mail()` method
- `models/responses.py` — `custom_mail: Optional[Dict]` field on `HiringInfo`
- `main.py` — Mail generation wired into `/api/hiring` endpoint

### API Endpoint (Postman)
**POST** `http://localhost:8001/api/hiring`
```json
{
  "companies": [
    { "company_name": "Stripe", "website": "stripe.com" }
  ]
}
```
Response will include `custom_mail` for each hiring company.

---

## 7. Implemented: F6S Funding Source
Added F6S (`f6s.com/companies/funding`) as a new company discovery source.

### Why Serper-Based
F6S blocks direct HTTP scraping (returns 405 + CAPTCHA). So this scraper uses Google Search (via Serper) with `site:f6s.com` queries, then Mistral extracts company/funding data from search results.

### Search Queries
- `site:f6s.com/companies funding raised`
- `site:f6s.com startup funded seed round`
- `site:f6s.com company "series a" OR "series b" OR "seed" funding`

### Files
- `services/scrapers/f6s_scraper.py` — `F6SScraper` class
- `services/scrapers/__init__.py` — Exports `F6SScraper`
- `services/company_discovery.py` — `enable_f6s=True` parameter in `CompanyDiscoveryService`

### How to Test (Postman)
**POST** `http://localhost:8001/api/discover`
```json
{
  "query": "funded startups",
  "limit": 20
}
```
F6S results will appear with `"source": "F6S"` in the response.

---

## 8. Implemented: Daily Hiring Outreach (SSE Streaming Endpoint)

### Purpose
A combined FastAPI streaming endpoint (`GET /api/v1/daily-hiring-outreach/`) that:
1. Authenticates with the CRM via JWT
2. Fetches companies created on a target date (default: yesterday) with `source=ENRICHMENT ENGINE`
3. Runs hiring detection on each company (same `EnhancedHiringChecker` logic)
4. **Always** generates a custom outreach email — even if `is_hiring = false`
5. Streams progress via **Server-Sent Events** (SSE)
6. Emits a final structured JSON summary

### Key Design Decisions
- **SSE streaming** — client gets real-time progress (`event: log`, `event: company`) and a final `event: summary`
- **Pagination fix** — relative `next` URLs (e.g. `/api/v1/companies/?page=2`) are resolved against `http://127.0.0.1:8000` using `urljoin`
- **Always-generate-mail** — every company gets a `custom_mail`, not just `is_hiring=true` ones
- **Funding signal keywords**: `raised`, `funding`, `$`, `valuation`, `million`, `billion`, `seed`, `series`

### Query Parameters
| Param | Default | Description |
|---|---|---|
| `date` | yesterday | Target date in `YYYY-MM-DD` |
| `page_size` | 100 | CRM page size (1–500) |

### SSE Event Types
| Event | Payload | When |
|---|---|---|
| `log` | `{"message": "..."}` | Progress/debug messages |
| `company` | `{company_name, is_hiring, custom_mail, ...}` | After each company is processed |
| `summary` | Full JSON summary with `processed_companies` array | Final event |

### Files
- `routes/daily_outreach.py` — SSE streaming endpoint + all logic
- `routes/__init__.py` — Package init
- `main.py` — Registers router via `app.include_router()`
- `daily_outreach.py` — Legacy standalone CLI script (still works independently)

## 9. Implemented: C-Suite Contact Lookup & Personalized Email Drafts

### Purpose
After generating a base outreach email for each company, the pipeline now:
1. **Finds C-suite contacts** — uses the company domain to discover 2–3 executive-level emails (CEO, CTO, VP Engineering, COO, VP Sales)
2. **Personalizes the email** — re-addresses the email body to the first (highest-priority) found contact, replacing the generic "Hi {Company} team" with "Hi {FirstName}"
3. **Streams contact details via SSE** — `found_contacts` and `personalized_email` are included in each `company` event

### Contact Simulation (Dummy Mode)
Currently uses **deterministic dummy data** (no real API calls) via `find_csuite_contacts()`:
- Hash-seeded from domain → same domain always returns the same contacts
- Realistic name pools per C-level title
- Common email patterns: `firstname@domain`, `first.last@domain`, `flast@domain`

> **To switch to real enrichment:** Replace `find_csuite_contacts()` with a call to Apollo.io, RocketReach, or similar. The function signature stays the same: `(domain: str, count: int) → list[dict]` where each dict has `{name, title, email}`.

### Pipeline Flow
```
CRM companies → hiring check → email generation → C-suite lookup → personalized draft
                                     │
                           ┌─────────┴──────────┐
                      is_hiring=true        is_hiring=false
                           │                     │
                    Mistral AI email        Template email
                    (tailored, role-aware)  (generic nurture)
                           │                     │
                     template fallback            │
                     (if AI fails)               │
                           └─────────┬───────────┘
                                     ▼
                            C-suite lookup → personalized draft
```

Each SSE `company` event now includes:
| Field | Type | Description |
|---|---|---|
| `found_contacts` | `[{name, title, email}]` | 2-3 simulated C-level contacts |
| `personalized_email` | `{to, to_name, to_title, subject, body}` | Email addressed to first contact |
| `mail_source` | `string` | `mistral_ai`, `template`, or `template_fallback` |

### Email Generation Strategy
- **Hiring companies** → `JobAnalyzer.generate_outreach_mail()` via Mistral AI. Uses model `mistral-large-latest` with `temperature=0.7`. Prompt includes company name, open roles, and funding context. Produces varied, natural, role-aware cold emails.
- **Non-hiring companies** → Fast f-string template. No API call needed.
- **Fallback** → If AI call fails or returns empty, the template generator is used as a safety net.

### Frontend
The automation page (`/agency/automation/`) shows:
- **Expandable company rows** — click to expand
- **Found Contacts** — name, title, email per contact
- **Personalized Email Draft** — full preview with To chip, subject line, and body
- **🤖 AI Generated** / **📝 Template** badge — indicates email source

