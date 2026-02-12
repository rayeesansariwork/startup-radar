# JobProspectorBE - Passive Lead Generation Engine 🚀

**Automated company discovery system** that passively finds newly funded startups daily from multiple sources.

## 🎯 Overview

JobProspectorBE is a FastAPI-based backend that:
- **Discovers funded companies** from 7+ sources automatically
- **Runs scheduled daily discovery** at 9 AM (passive engine)
- **Scrapes career pages** to find hiring roles
- **Stores companies** in CRM for sales/recruitment outreach

### Key Features

✅ **Multi-Source Discovery**: YC, TechCrunch, NewsAPI, Google News, Crunchbase, VentureBeat  
✅ **Passive Automation**: Daily scheduled jobs discover 10-30+ companies automatically  
✅ **Comprehensive Logging**: Track every step with detailed metrics  
✅ **Deduplication**: Smart company matching by name and domain  
✅ **CRM Integration**: Auto-stores discovered companies  
✅ **Career Page Scraping**: Detect hiring status and job roles  

---

## 📋 Prerequisites

- Python 3.9+
- Virtual environment (recommended)

---

## 🛠️ Installation

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
GROQ_API_KEY=your_groq_key_here
NEWSAPI_KEY=your_newsapi_key_here

# CRM Configuration
CRM_BASE_URL=https://salesapi.gravityer.com/api/v1
CRM_ACCESS_TOKEN=your_crm_token_here

# Application Settings
APP_HOST=0.0.0.0
APP_PORT=8001
LOG_LEVEL=INFO
```

**Get Free API Keys:**
- **Groq**: https://console.groq.com (free)
- **NewsAPI**: https://newsapi.org/register (100 req/day free)
- **Serper**: https://serper.dev (optional for search)

---

## 🚀 Running the Application

### Start Server
```bash
python main.py
```

The server will start on `http://localhost:8001` with the **passive discovery engine activated**.

You should see:
```
============================================================
[Scheduler] 🚀 PASSIVE DISCOVERY ENGINE STARTED
[Scheduler] Daily job: 09:00
[Scheduler] Active sources: 7
============================================================
```

---

## 📡 API Endpoints

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

**Purpose:** Manually discover funded companies from all sources

**Request:**
```bash
curl -X POST http://localhost:8001/api/discover \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "limit": 20
  }'
```

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/discover" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "test", "limit": 20}'
```

**Response:**
```json
{
  "success": true,
  "companies_found": 15,
  "companies_stored": 8,
  "errors": ["Company X: already exists"],
  "companies": [
    {
      "company_name": "Acme Corp",
      "website": "https://acme.com",
      "funding_info": "Raised $10M Series A",
      "source": "Google News (TechCrunch)",
      "crm_id": "123",
      "stored": true
    }
  ]
}
```

---

### 3. Check Hiring Status

**Endpoint:** `POST /api/hiring`

**Purpose:** Check if companies are actively hiring

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

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/hiring" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"companies": [{"company_name": "Acme Corp", "website": "https://acme.com"}]}'
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "company_name": "Acme Corp",
      "is_hiring": true,
      "confidence": "high",
      "job_count": 15,
      "roles": ["Software Engineer", "Product Manager"],
      "career_page_url": "https://acme.com/careers"
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

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/status"
```

**Response:**
```json
{
  "success": true,
  "running": true,
  "active_sources": 7,
  "jobs": [
    {
      "id": "daily_discovery",
      "name": "Daily Company Discovery",
      "next_run": "2026-02-13 09:00:00"
    }
  ]
}
```

---

### 5. Manual Discovery Trigger

**Endpoint:** `POST /api/scheduler/manual?limit=50`

**Purpose:** Manually trigger discovery (for testing passive engine)

**Request:**
```bash
curl -X POST "http://localhost:8001/api/scheduler/manual?limit=30"
```

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/manual?limit=30" -Method Post
```

**Response:**
```json
{
  "success": true,
  "companies_found": 25,
  "companies": [...],
  "sources_used": ["Y Combinator", "Google News", "Crunchbase News"]
}
```

---

## 🧪 Testing Guide

### Quick Test: All Endpoints

```powershell
# 1. Health check
Invoke-RestMethod -Uri "http://localhost:8001/"

# 2. Check scheduler status
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/status"

# 3. Manual discovery (small limit for testing)
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/manual?limit=5" -Method Post

# 4. Discover companies
Invoke-RestMethod -Uri "http://localhost:8001/api/discover" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "test", "limit": 10}'

# 5. Check hiring status
Invoke-RestMethod -Uri "http://localhost:8001/api/hiring" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"companies": [{"company_name": "OpenAI", "website": "https://openai.com"}]}'
```

### Test Individual Scrapers

```bash
# Test NewsAPI scraper
python test_newsapi.py

# Test all RSS scrapers
python test_rss_scrapers.py
```

---

## 🤖 Passive Engine Details

### How It Works

1. **Scheduled Job** runs daily at 9 AM
2. **7 Scrapers** run in parallel:
   - Y Combinator (recent batches)
   - TechCrunch RSS
   - NewsAPI (past 24 hours)
   - Google News RSS (aggregates all sources)
   - Crunchbase News RSS
   - VentureBeat RSS
   - ProductHunt (placeholder)
3. **Deduplicates** companies by name and domain
4. **Stores** new companies in CRM automatically
5. **Logs** detailed metrics for monitoring

### Expected Results

- **Daily**: 10-30+ newly funded companies
- **Weekly**: 50-150 companies
- **Per YC Batch**: 200-400 companies (every 6 months)

### Monitoring

Check logs for:
```
[Scheduler] 🌅 DAILY DISCOVERY STARTED
[Discovery] 🚀 STARTING MULTI-SOURCE DISCOVERY
[YC] ✅ Scrape complete: 10 companies
[GNews] ✅ Scrape complete: 15 companies
[CB] ✅ Scrape complete: 8 companies
[Discovery] ✅ DISCOVERY COMPLETE: 30 companies found
```

---

## 📊 Data Sources

| Source | Type | Update Frequency | Companies/Day |
|--------|------|------------------|---------------|
| **Y Combinator** | API | Per batch (~6 months) | 200-400/batch |
| **NewsAPI** | API | Real-time | 5-20 |
| **Google News** | RSS | Hourly | 10-30 |
| **Crunchbase News** | RSS | Daily | 20-50 |
| **VentureBeat** | RSS | Daily | 5-15 |
| **TechCrunch** | RSS | Daily | 5-15 |

---

## 🔧 Configuration

### Scheduler Settings

Edit `main.py` to customize:

```python
scheduler.start(
    daily_hour=9,        # Hour to run (0-23)
    daily_minute=0,      # Minute to run (0-59)
    enable_hourly=False, # Enable hourly checks
    hourly_interval=3    # Hours between checks
)
```

### Enable/Disable Sources

Edit `services/scheduled_discovery.py`:

```python
self.discovery_service = CompanyDiscoveryService(
    enable_yc=True,              # Y Combinator
    enable_techcrunch=True,      # TechCrunch
    enable_newsapi=True,         # NewsAPI
    enable_google_news=True,     # Google News
    enable_crunchbase=True,      # Crunchbase
    enable_venturebeat=True,     # VentureBeat
    enable_producthunt=False     # ProductHunt (placeholder)
)
```

---

## 📝 Project Structure

```
JobProspectorBE/
├── main.py                          # FastAPI app + endpoints
├── config.py                        # Settings & env vars
├── models.py                        # Pydantic models
├── services/
│   ├── company_discovery.py         # Multi-source orchestration
│   ├── scheduled_discovery.py       # Passive engine scheduler
│   ├── crm_client.py               # CRM integration
│   └── scrapers/
│       ├── base_scraper.py          # Base class
│       ├── yc_scraper.py           # Y Combinator
│       ├── techcrunch_scraper.py   # TechCrunch RSS
│       ├── news_api_scraper.py     # NewsAPI
│       ├── google_news_scraper.py  # Google News RSS
│       ├── crunchbase_news_scraper.py  # Crunchbase RSS
│       └── venturebeat_scraper.py  # VentureBeat RSS
├── hiring_detector/
│   └── checker.py                   # Career page scraper
├── test_newsapi.py                  # Test NewsAPI
├── test_rss_scrapers.py            # Test RSS scrapers
└── requirements.txt                 # Dependencies
```

---

## 🐛 Troubleshooting

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

### Issue: RSS scrapers failing

**Solution:**
- RSS feeds may be temporarily unavailable
- Check individual scraper logs
- Groq API may be rate-limited (wait a bit)

---

## 🚀 Next Steps

1. **Monitor Daily Discovery**: Check logs at 9 AM to see automated discovery
2. **Review Companies**: Use CRM to review discovered companies
3. **Scrape Career Pages**: Use `/api/hiring` endpoint on discovered companies
4. **Add Notifications**: Implement email/Slack webhooks in `scheduled_discovery.py`

---

## 📄 License

MIT License

---

## 🤝 Contributing

Feel free to submit issues and enhancement requests!

---

## 📞 Support

For questions or issues, check the logs first:
- Server logs show all scraper activity
- Use log prefixes to filter: `[YC]`, `[GNews]`, `[CB]`, `[VB]`, `[Discovery]`, `[Scheduler]`

**Happy hunting! 🎯**
