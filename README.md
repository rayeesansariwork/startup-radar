# JobProspectorBE - Automated Company Discovery System

**Automated company discovery system that finds newly funded startups daily from multiple sources and stores them in your CRM.**

## Overview

JobProspectorBE is a FastAPI-based backend service that:
- Discovers funded companies from 5+ sources automatically
- Runs scheduled daily discovery at 9 AM IST with CRM storage
- Sends email notifications with discovery results
- Scrapes career pages to find hiring roles
- Stores companies in CRM for sales/recruitment outreach

### Key Features

- **Multi-Source Discovery**: Y Combinator, TechCrunch, NewsAPI, Google News, VentureBeat
- **Automated Daily Discovery**: Scheduled jobs discover 100-250+ companies daily
- **CRM Integration**: Automatically stores discovered companies with deduplication
- **Email Notifications**: Gmail SMTP notifications with detailed discovery reports
- **Career Page Scraping**: Detect hiring status and extract job roles
- **Comprehensive Logging**: Track every step with detailed metrics

---

## Prerequisites

- Python 3.9+
- Virtual environment (recommended)
- Gmail account (for email notifications)
- CRM API credentials

---

## Installation

### 1. Clone Repository
```bash
git clone <your-repo-url>
cd JobProspectorBE
```

### 2. Create Virtual Environment
```bash
python -m venv myenv
myenv\Scripts\activate  # Windows
# source myenv/bin/activate  # Linux/Mac
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```env
# API Keys
SERPER_API_KEY=your_serper_key_here
MISTRAL_API_KEY=your_mistral_key_here
NEWSAPI_KEY=your_newsapi_key_here

# CRM Configuration
CRM_BASE_URL=https://salesapi.gravityer.com/api/v1
CRM_EMAIL=your_crm_email@example.com
CRM_PASSWORD=your_crm_password

# Gmail SMTP Notifications
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-16-char-app-password
NOTIFICATION_RECIPIENT=recipient@example.com

# Scheduler Configuration (Times are in server's local timezone - set to IST for India)
DAILY_SCRAPE_HOUR=9
DAILY_SCRAPE_MINUTE=0

# Application Settings
APP_HOST=0.0.0.0
APP_PORT=8001
LOG_LEVEL=INFO

# Rate Limiting
MAX_CONCURRENT_REQUESTS=10
RETRY_MAX_ATTEMPTS=3
RETRY_WAIT_SECONDS=2
```

**Get Free API Keys:**
- **Mistral AI**: https://console.mistral.ai (free tier available)
- **NewsAPI**: https://newsapi.org/register (100 requests/day free)
- **Serper**: https://serper.dev (optional for search)
- **Gmail App Password**: Google Account → Security → 2-Step Verification → App passwords

---

## Running the Application

### Start Server
```bash
python main.py
```

The server will start on `http://localhost:8001` with the **passive discovery engine activated**.

You should see:
```
============================================================
[Scheduler] PASSIVE DISCOVERY ENGINE STARTED
[Scheduler] Daily job: 09:00
[Scheduler] Active sources: 5
============================================================
```

---

## API Endpoints

### 1. Health Check
```bash
GET http://localhost:8001/
```

**Response:**
```json
{
  "message": "JobProspectorBE API",
  "version": "1.0.0",
  "endpoints": {
    "/api/discover": "Discover funded companies",
    "/api/hiring": "Check hiring status",
    "/api/scheduler/status": "Get scheduler status",
    "/api/scheduler/manual": "Manually trigger discovery"
  }
}
```

---

### 2. Discover Companies (Manual)

**Endpoint:** `POST /api/discover`

**Purpose:** Manually discover funded companies from all sources and store in CRM

**Request:**
```bash
curl -X POST http://localhost:8001/api/discover \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "limit": 50
  }'
```

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/discover" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "test", "limit": 50}'
```

**Response:**
```json
{
  "success": true,
  "companies_found": 45,
  "companies_stored": 38,
  "errors": ["Company X: already exists"],
  "companies": [
    {
      "company_name": "Acme Corp",
      "website": "https://acme.com",
      "funding_info": "Raised $10M Series A",
      "source": "Google News (TechCrunch)",
      "crm_id": 123,
      "stored": true
    }
  ]
}
```

---

### 3. Check Hiring Status

**Endpoint:** `POST /api/hiring`

**Purpose:** Check if companies are actively hiring and extract job roles

**Request:**
```bash
curl -X POST http://localhost:8001/api/hiring \
  -H "Content-Type: application/json" \
  -d '{
    "companies": [
      {
        "company_name": "Acme Corp",
        "website": "https://acme.com"
      }
    ]
  }'
```

**Response:**
```json
{
  "success": true,
  "total_companies": 1,
  "hiring_companies": 1,
  "results": [
    {
      "company_name": "Acme Corp",
      "is_hiring": true,
      "job_count": 15,
      "job_roles": ["Software Engineer", "Product Manager"],
      "career_page_url": "https://acme.com/careers",
      "detection_method": "Greenhouse API"
    }
  ]
}
```

---

### 4. Scheduler Status

**Endpoint:** `GET /api/scheduler/status`

**Purpose:** Check passive engine status and next run times

**Request:**
```bash
curl http://localhost:8001/api/scheduler/status
```

**Response:**
```json
{
  "success": true,
  "running": true,
  "active_sources": 5,
  "jobs": [
    {
      "id": "daily_discovery",
      "name": "Daily Company Discovery",
      "next_run": "2026-02-14 09:00:00"
    }
  ]
}
```

---

### 5. Manual Discovery Trigger

**Endpoint:** `POST /api/scheduler/manual?limit=50`

**Purpose:** Manually trigger discovery with CRM storage and email notification

**Request:**
```bash
curl -X POST "http://localhost:8001/api/scheduler/manual?limit=50"
```

**Response:**
```json
{
  "success": true,
  "companies": [...],
  "sources_used": ["Y Combinator", "Google News", "TechCrunch"],
  "total_before_dedup": 262,
  "total_after_dedup": 250,
  "stored_count": 245,
  "duration": 45.2
}
```

---

## Automated Daily Discovery

### How It Works

1. **Scheduled Job** runs daily at 9:00 AM IST
2. **5 Scrapers** run in parallel:
   - Y Combinator (recent batches: W26, S25, W25, S24)
   - TechCrunch RSS (latest funding articles)
   - NewsAPI (past 24 hours)
   - Google News RSS (aggregates all sources)
   - VentureBeat RSS (latest funding news)
3. **Deduplicates** companies by name and domain
4. **Stores** companies in CRM automatically
5. **Sends email notification** with discovery results
6. **Logs** detailed metrics for monitoring

### Expected Results

- **Daily**: 100-250 companies discovered
- **CRM Storage**: 50-150 new companies stored daily (after CRM deduplication)
- **Email Report**: Sent to configured recipient with top 50 companies

### Email Notifications

Automated emails include:
- Total companies discovered
- Source breakdown with counts
- Top 50 companies with funding details
- Timestamp in IST
- Duration and performance metrics

---

## Data Sources

| Source | Type | Update Frequency | Companies/Day |
|--------|------|------------------|---------------|
| **Y Combinator** | API | Per batch (~6 months) | 200-400/batch |
| **NewsAPI** | API | Real-time | 10-30 |
| **Google News** | RSS | Hourly | 20-50 |
| **VentureBeat** | RSS | Daily | 10-25 |
| **TechCrunch** | RSS | Daily | 10-25 |

**Note:** Y Combinator provides a stable baseline of recent batch companies. News sources provide fresh daily funding announcements. The CRM automatically handles duplicates, so the same company won't be stored twice.

---

## Configuration

### Scheduler Settings

Edit `.env` to customize schedule time:

```env
DAILY_SCRAPE_HOUR=9    # Hour to run (0-23) in server timezone
DAILY_SCRAPE_MINUTE=0  # Minute to run (0-59)
```

### Enable/Disable Sources

Edit `services/scheduled_discovery.py`:

```python
self.discovery_service = CompanyDiscoveryService(
    enable_yc=True,              # Y Combinator
    enable_techcrunch=True,      # TechCrunch
    enable_newsapi=True,         # NewsAPI
    enable_google_news=True,     # Google News
    enable_venturebeat=True,     # VentureBeat
    enable_producthunt=False     # ProductHunt (placeholder)
)
```

---

## Project Structure

```
JobProspectorBE/
├── main.py                          # FastAPI app + endpoints
├── config.py                        # Settings & env vars
├── models.py                        # Pydantic models
├── services/
│   ├── company_discovery.py         # Multi-source orchestration
│   ├── scheduled_discovery.py       # Passive engine scheduler
│   ├── crm_client.py               # CRM integration
│   ├── notification_service.py      # Gmail SMTP notifications
│   └── scrapers/
│       ├── base_scraper.py          # Base class with Mistral integration
│       ├── yc_scraper.py           # Y Combinator
│       ├── techcrunch_scraper.py   # TechCrunch RSS
│       ├── news_api_scraper.py     # NewsAPI
│       ├── google_news_scraper.py  # Google News RSS
│       └── venturebeat_scraper.py  # VentureBeat RSS
├── hiring_detector/
│   ├── checker.py                   # Enhanced hiring checker
│   └── analyzer.py                  # Mistral AI analyzer
└── requirements.txt                 # Dependencies
```

---

## Troubleshooting

### Issue: No companies found

**Solution:**
- Check API keys in `.env`
- Verify internet connection
- Check logs for specific scraper errors
- Try manual trigger: `POST /api/scheduler/manual?limit=10`

### Issue: Scheduler not running

**Solution:**
- Check server logs on startup
- Verify APScheduler installed: `pip install apscheduler==3.10.4`
- Check `/api/scheduler/status` endpoint

### Issue: Email notifications not sending

**Solution:**
- Verify Gmail credentials in `.env`
- Ensure you're using Gmail App Password (not regular password)
- Check logs for SMTP errors
- Test with manual discovery endpoint

### Issue: CRM storage failing

**Solution:**
- Verify CRM credentials in `.env`
- Check CRM API is accessible
- Review logs for authentication errors
- Ensure CRM token is valid

---

## Testing Guide

### Quick Test: All Endpoints

```powershell
# 1. Health check
Invoke-RestMethod -Uri "http://localhost:8001/"

# 2. Check scheduler status
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/status"

# 3. Manual discovery (small limit for testing)
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/manual?limit=10" -Method Post

# 4. Discover companies
Invoke-RestMethod -Uri "http://localhost:8001/api/discover" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "test", "limit": 20}'

# 5. Check hiring status
Invoke-RestMethod -Uri "http://localhost:8001/api/hiring" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"companies": [{"company_name": "OpenAI", "website": "https://openai.com"}]}'
```

---

## Monitoring

Check logs for daily discovery activity:

```
[Scheduler] DAILY DISCOVERY STARTED - 2026-02-13 09:00:00
[Discovery] STARTING MULTI-SOURCE DISCOVERY
[YC] Scrape complete: 250 companies
[GNews] Scrape complete: 45 companies
[TC] Scrape complete: 30 companies
[Discovery] DISCOVERY COMPLETE: 250 companies returned
[Scheduler] Storing 250 companies in CRM...
[Scheduler] Stored 180/250 companies in CRM
[Scheduler] Sending email notification...
[Scheduler] Email notification sent successfully
```

---

## License

MIT License

---

## Support

For questions or issues, check the logs first:
- Server logs show all scraper activity
- Use log prefixes to filter: `[YC]`, `[GNews]`, `[TC]`, `[VB]`, `[Discovery]`, `[Scheduler]`
- Email notifications provide daily summary reports
