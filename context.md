# context.md — JobProspectorBE

> **Last updated:** 2026-02-20  
> **Purpose:** Complete technical reference for any LLM or developer working on this project.  
> Keep this file updated whenever new features are added.

---

## 1. Project Overview

**What it is:** A production-ready, automated B2B lead-generation engine.  
**Goal:** Identify companies that (a) recently received funding and (b) are actively hiring tech/engineering talent, then generate personalized cold-outreach emails for each.

**Core philosophy:** *"Intelligence over Brute Force."* Instead of blindly crawling homepages, the system triangulates career pages via ATS backdoors, sitemaps, and targeted Serper searches — minimizing bandwidth, latency, and IP-ban risk.

**Tech stack:**
| Layer | Technology |
|---|---|
| Runtime | Python 3.x |
| API server | FastAPI (async, `uvicorn`) |
| Scraping | `requests` + `beautifulsoup4`, Playwright (last resort) |
| AI | Mistral AI (`mistral-large-latest`) |
| Search | Serper.dev (Google Search API) |
| Scheduler | APScheduler (cron + interval) |
| Config | `pydantic-settings` via `.env` |
| Persistence | SalesTechBE REST API (Django) |

---

## 2. Project Layout

```
JobProspectorBE/
├── main.py                  # FastAPI app entry point, all routes except daily outreach
├── config.py                # pydantic-settings: all env vars with defaults
├── core_utils.py            # apply_windows_asyncio_fix(), execute_with_retry()
├── daily_outreach.py        # Legacy standalone CLI script (still works)
├── routes/
│   └── daily_outreach.py    # SSE streaming endpoint (PRIMARY)
├── hiring_detector/
│   ├── checker.py           # EnhancedHiringChecker — 4-layer hiring detector
│   ├── triangulator.py      # HiringTriangulator — ATS/Sitemap/Serper strategy
│   ├── analyzer.py          # JobAnalyzer — Mistral AI email + job extraction
│   ├── platforms.py         # Direct ATS API scrapers (Greenhouse, Lever, Ashby)
│   └── scraper.py           # Generic career-page HTML scraper
├── services/
│   ├── crm_client.py        # CRMClient — JWT auth + company store
│   ├── company_discovery.py # CompanyDiscoveryService — multi-source company finder
│   ├── scheduled_discovery.py  # ScheduledDiscoveryService — APScheduler wrapper
│   ├── notification_service.py # Email notifications (Gmail SMTP / SendGrid)
│   ├── hiring_page_finder.py   # HiringPageFinderService — Serper + Mistral
│   ├── serper.py            # Low-level Serper.dev HTTP wrapper
│   └── scrapers/
│       ├── base_scraper.py       # BaseScraper ABC
│       ├── yc_scraper.py         # Y Combinator company list
│       ├── techcrunch_scraper.py # TechCrunch news RSS
│       ├── google_news_scraper.py# Google News RSS (funded startups)
│       ├── venturebeat_scraper.py# VentureBeat RSS
│       ├── news_api_scraper.py   # NewsAPI.org (optional, 100 req/day free)
│       ├── f6s_scraper.py        # F6S via Serper (direct scraping blocked)
│       └── producthunt_scraper.py# Product Hunt
└── models/
    └── responses.py         # Pydantic models: HiringInfo, DiscoverResponse, etc.
```

---

## 3. Configuration (`.env` / `config.py`)

All config lives in `.env`, read by `pydantic_settings.BaseSettings`.

```ini
# Required
SERPER_API_KEY=<your_key>
MISTRAL_API_KEY=<your_key>
CRM_EMAIL=rayees@gravityer.com
CRM_PASSWORD=<pass>
CRM_BASE_URL=https://salesapi.gravityer.com/api/v1   # default

# Optional notifications
GMAIL_USER=
GMAIL_APP_PASSWORD=
SENDGRID_API_KEY=
SENDGRID_FROM_EMAIL=
NOTIFICATION_RECIPIENT=

# Scheduler (times given in IST, auto-converted to UTC at startup)
DAILY_SCRAPE_HOUR=9      # IST 09:00 → daily company discovery
DAILY_SCRAPE_MINUTE=0
SCHED_IST_HOUR=15        # IST 15:40 → daily hiring outreach cron
SCHED_IST_MINUTE=40

# Limits
MAX_CONCURRENT_REQUESTS=10
```

**IST → UTC conversion** happens in `main.py` `lifespan()` using `_ist_to_utc(h, m)` = `(h*60+m - 330) % 1440`.

---

## 4. API Endpoints

### `GET /`
Health check. Returns list of all available endpoints.

### `POST /api/discover`
Discover recently funded companies from multiple sources and store them in the CRM.  
- **Sources (enabled by default):** YC Scraper, TechCrunch Scraper  
- Deduplicates across sources, stores via `CRMClient.store_company()`  
- Uses `asyncio.Semaphore(10)` for concurrency control

### `POST /api/hiring`
Check hiring status for a list of companies (usually the output of `/api/discover`).  
- Runs `EnhancedHiringChecker.check_hiring()` per company  
- For hiring companies with roles, generates an outreach email via `JobAnalyzer.generate_outreach_mail()` (Mistral AI)

### `POST /api/find-jobs`
Find and extract job openings from a single company URL.  
- Uses `HiringPageFinderService.find_hiring_page(url)`: Serper search → scrape → Mistral extraction

### `GET /api/v1/daily-hiring-outreach/` ⭐ PRIMARY PIPELINE
**Server-Sent Events streaming endpoint.** See section 8 for full details.

Query params:
| Param | Default | Description |
|---|---|---|
| `date` | yesterday | `YYYY-MM-DD` override |
| `page_size` | 100 | CRM fetch page size (1–500) |

### `GET /api/scheduler/status`
Returns APScheduler job list and status.

### `POST /api/scheduler/manual`
Manually trigger company discovery (for testing). Accepts `?limit=50`.

---

## 5. The Triangulation Strategy (`HiringTriangulator`)

File: `hiring_detector/triangulator.py`

Three-layer hierarchy to find career pages without getting blocked:

```
Priority 1 — ATS Backdoor (HIGH success, LOW risk)
  → Serper: site:greenhouse.io OR site:lever.co OR site:ashbyhq.com "<company>"
  → Known ATS domains: greenhouse.io, lever.co, ashbyhq.com, workable.com, breezy.hr

Priority 2 — Sitemap Surgeon (Polite, no Serper quota)
  → Fetch domain.com/sitemap.xml
  → Parse <loc> tags for URLs containing "career" or "jobs"

Priority 3 — Organic Search (Fallback)
  → Serper: site:domain (careers OR jobs)
```

**Rules for any LLM modifying this:**
- Do NOT remove randomized sleep (keeps us undetected)
- Do NOT replace `requests` with Playwright unless explicitly asked
- Prefer "Search First" over "Crawl All"
- Extend `ATS_PROVIDERS` dict to add new platforms

---

## 6. Hiring Detection (`EnhancedHiringChecker`)

File: `hiring_detector/checker.py`

Four-layer detection engine:
1. **Platform APIs** — Direct Greenhouse / Lever / Ashby API calls (fastest, most accurate)
2. **Career page detection** — Runs `HiringTriangulator`, then scrapes the found URL
3. **Playwright browser** — Headless browser for JS-heavy sites (last resort; requires `playwright install`)
4. **Mistral AI analysis** — Passes scraped text to Mistral with structured extraction prompt

Returns:
```python
{
    "is_hiring": bool,
    "job_count": int,
    "job_roles": ["Software Engineer", ...],
    "career_page_url": str,
    "hiring_summary": str,
    "detection_method": str   # "Platform_API", "Triangulation", "Playwright", "Mistral"
}
```

**Windows asyncio fix:** `core_utils.apply_windows_asyncio_fix()` is called at the very top of `main.py` before any other imports to switch to `ProactorEventLoop` so Playwright can spawn browser subprocesses.

---

## 7. AI Email Generation (`JobAnalyzer`)

File: `hiring_detector/analyzer.py`

Uses Mistral AI (`mistral-large-latest`, `temperature=0.7`).

**Input:** `company_name`, `job_roles: list[str]`, `funding_info: Optional[str]`  
**Output:**
```python
{
    "subject": str,
    "body": str,
    "team_focus": str   # "Backend Engineering", "AI / Data Engineering", etc.
}
```

Used by `/api/hiring` and by the daily outreach pipeline for **hiring companies only**. Non-hiring companies get a template email (fast, no API tokens burned).

---

## 8. Daily Hiring Outreach Pipeline ⭐

File: `routes/daily_outreach.py`

### Full pipeline (per run)
```
1. Authenticate with SalesTechBE CRM → JWT Bearer token
2. Fetch companies (source=ENRICHMENT ENGINE, created >= target_date)
   - Handles pagination via relative `next` URL resolution
   - Auto-refreshes token on 401
3. Per company (sequential, 5–7 s polite delay between):
   a. EnhancedHiringChecker.check_hiring(name, website)    → hiring result
   b. Email generation:
      - is_hiring + roles → JobAnalyzer (Mistral AI)        → "mistral_ai"
      - is_hiring, no roles → template                       → "template"
      - not hiring → template                                → "template"
      - AI fails → template fallback                         → "template_fallback"
   c. find_csuite_contacts(domain, count=3)                 → simulated C-suite contacts
   d. generate_personalized_mail(company, contacts[0], mail)→ personalized draft
   e. yield SSE event: "company" with full result
4. yield SSE event: "summary" { stats + processed_companies[] }
5. POST processed[] to SalesTechBE /hiring-outreach-results/bulk_create/
```

### SSE Event Types
| Event | Payload | When |
|---|---|---|
| `log` | `{"message": "..."}` | Every step — real-time progress |
| `company` | Full company result dict | After each company processed |
| `summary` | Stats + all processed companies | Last event sent |

### Company result shape (per SSE `company` event)
```python
{
    "company_name": str,
    "website": str,
    "is_hiring": bool,
    "job_count": int,
    "job_roles": ["Senior Engineer", ...],
    "custom_mail": {"subject": str, "body": str, "team_focus": str},
    "mail_source": "mistral_ai" | "template" | "template_fallback" | "failed",
    "found_contacts": [{"name": str, "title": str, "email": str}, ...],  # 2-3 items
    "personalized_email": {"to": str, "to_name": str, "to_title": str, "subject": str, "body": str},
    "error": str | None,    # hiring check error if any
    "run_date": str,        # YYYY-MM-DD
}
```

### Automatic cron scheduling
Configured in `main.py` `lifespan()`:
- Time read from `.env` `SCHED_IST_HOUR` + `SCHED_IST_MINUTE` (IST)
- Converted to UTC at startup
- APScheduler `CronTrigger` added to the shared `scheduler.scheduler`

---

## 9. C-Suite Contact Lookup

File: `routes/daily_outreach.py` → `find_csuite_contacts(domain, count=3)`

### Current state: Simulated (placeholder)
- Deterministic output: same domain always returns the same 3 contacts
- Hash-seeded from MD5(domain) → `random.Random(seed)`
- Realistic names, titles, email patterns

Roles covered: CEO, CTO, VP Engineering, COO, VP Sales

### ⚠️ To switch to real enrichment:
Replace `find_csuite_contacts()` with a call to **Apollo.io**, **RocketReach**, or similar.  
Function signature must stay: `(domain: str, count: int) → list[{"name": str, "title": str, "email": str}]`

> **NO APOLLO KEY AVAILABLE YET.** Real email fetching is not wired up.  
> `personalized_email.to` contains **simulated addresses** — do not attempt SMTP sends.

---

## 10. Persistence Layer (SalesTechBE)

Results are pushed to the Django CRM after each outreach run.

**Endpoint:** `POST https://salesapi.gravityer.com/api/v1/hiring-outreach-results/bulk_create/`  
**Payload:** `{"results": [...], "run_date": "YYYY-MM-DD"}`

### DB model: `HiringOutreachResult` (SalesTechBE)
| Field | Type | Notes |
|---|---|---|
| `company_name` | CharField | db_index |
| `website` | URLField | nullable |
| `is_hiring` | BooleanField | default False |
| `job_count` | IntegerField | default 0 |
| `job_roles` | JSONField | list |
| `custom_mail` | JSONField | nullable |
| `found_contacts` | JSONField | list |
| `personalized_email` | JSONField | nullable |
| `mail_source` | CharField | `mistral_ai`, `template`, etc. |
| `career_page_url` | URLField | nullable |
| `detection_method` | CharField | nullable |
| `hiring_summary` | TextField | nullable |
| `run_date` | DateField | db_index |
| `error` | TextField | nullable |
| `email_sent` | BooleanField | **new** — default False; tracks if outreach email was dispatched |

### Mark email as sent
`POST /api/v1/hiring-outreach-results/<id>/send_email/`

- Returns `200 {"id": ..., "email_sent": true}` on success
- Returns `409 {"detail": "Email already sent for this company."}` if already marked
- **No actual SMTP is wired**. This endpoint only flips the flag. Real sending TBD when Apollo key is available.

---

## 11. Company Discovery Sources

| Scraper | File | Method | Notes |
|---|---|---|---|
| Y Combinator | `yc_scraper.py` | Direct HTTP | Company list page |
| TechCrunch | `techcrunch_scraper.py` | RSS | Funding articles |
| Google News | `google_news_scraper.py` | RSS | "funded startup" queries |
| VentureBeat | `venturebeat_scraper.py` | RSS + Mistral extraction | |
| NewsAPI | `news_api_scraper.py` | NewsAPI.org REST | 100 req/day free tier |
| F6S | `f6s_scraper.py` | Serper (site:f6s.com) + Mistral | F6S blocks direct scraping |
| Product Hunt | `producthunt_scraper.py` | HTTP | |

**Currently enabled in `/api/discover`:** YC + TechCrunch only (editable in `main.py`).

---

## 12. Email Outreach Template Logic

File: `routes/daily_outreach.py` → `generate_mail()`

The template system is funding-signal-aware and team-aware:

**Funding detection** — checks `annual_revenue`, `latest_funding_amount`, `total_funding`, `last_raised_at` for keywords: `raised`, `funding`, `$`, `million`, `billion`, `seed`, `series`.

**Team detection** — scans `industry`, `technologies`, `seo_description` keywords:
| Detected keywords | Team focus |
|---|---|
| ai, ml, machine learning, data | AI / Data Engineering |
| fintech, finance, banking, payment | FinTech Engineering |
| health, biotech, medical | HealthTech Engineering |
| saas, cloud, devops, infra | Cloud / Platform Engineering |
| ecommerce, retail, marketplace | Full-Stack Engineering |
| sales, marketing, growth | Sales & Growth |
| (default) | Engineering |

**Email variants:**
1. Hiring + roles + funding → AI-tailored (Mistral) subject + role list
2. Hiring + roles, no funding → AI-tailored, no funding mention  
3. Hiring, no roles → Template (funding-aware)
4. Not hiring + funding → Template nurture (congrats angle)
5. Not hiring, no funding → Generic template

Signature appended: `info@gravityer.com | Gravity Team`

---

## 13. Frontend Integration

The outreach page lives at `salestechui/src/app/agency/automation/page.jsx`.

### SSE consumption
```javascript
const es = new EventSource(`${API_BASE}/api/v1/daily-hiring-outreach/?date=...`)
es.addEventListener('log',     (e) => appendLog(JSON.parse(e.data).message))
es.addEventListener('company', (e) => appendCompany(JSON.parse(e.data)))
es.addEventListener('summary', (e) => setSummary(JSON.parse(e.data)))
```

### Records table columns (current)
| Column | Source field | Notes |
|---|---|---|
| Company | `company_name` + favicon | Favicon from `https://www.google.com/s2/favicons?domain=...` |
| Website | `website` | External link |
| Hiring | `is_hiring` | Chip: green/grey |
| Jobs | `job_count` | |
| Contacts | `found_contacts.length` | |
| Email To | `personalized_email.to` | First contact's email |
| **Email Sent** | `email_sent` | "Yes" (greyed) / "—" |
| **Send Email** | — | Button → `POST /hiring-outreach-results/<id>/send_email/` |

### Send Email button behaviour
- **Active** (purple outline): `email_sent === false`
- **Disabled** (greyed out): `email_sent === true`
- **Tooltip**: "Email already sent" when disabled
- On success: local state updated instantly (no page reload needed)
- History is fetched from `GET /api/v1/hiring-outreach-results/?page_size=N&page=N`

---

## 14. Deployment

| Platform | Config file |
|---|---|
| Render | `render.yaml` |
| Local (dev) | `uvicorn main:app --reload --port 8001` |
| Virtual env | `d:\JobProspectorBE\myenv\` |

**Start command:**
```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

**Windows-specific:** `core_utils.apply_windows_asyncio_fix()` must be the first import in `main.py` to set `ProactorEventLoop` before any other async code loads. This is required for Playwright to work on Windows.

---

## 15. Known Limitations / Future Work

| Item | Status |
|---|---|
| Real Apollo / RocketReach email lookup | ❌ Not wired. Simulated contacts only. |
| Actual SMTP / SendGrid email sending | ❌ Not wired. `email_sent` flag is a placeholder. |
| F6S scraper (direct) | ❌ F6S blocks HTTP. Uses Serper workaround. |
| Playwright in production | ⚠️ Requires `playwright install chromium`. Works on Windows with ProactorEventLoop fix. |
| NewsAPI scraper | ⚠️ Optional — 100 req/day free tier. Set `NEWSAPI_KEY` in `.env`. |
| Hourly passive scheduler | ⚠️ Disabled (`enable_hourly=False`). Re-enable in `main.py` lifespan if needed. |

---

## 16. Golden Rules (for any LLM modifying this project)

1. **Never remove randomized sleep** between company requests (rate limiting / anti-bot).
2. **Never replace `requests` with Playwright** unless the user explicitly asks.
3. **Always prefer "Search First"** (Serper) over "Crawl All".
4. **`email_sent` is a UI placeholder** — do not wire real SMTP until Apollo key is available.
5. **`found_contacts` are simulated** — never send real emails to these addresses.
6. **IST times in `.env`** are converted to UTC at startup — do not hardcode UTC times.
7. **`apply_windows_asyncio_fix()` must be the first call in `main.py`** — before any imports that might set the event loop.
