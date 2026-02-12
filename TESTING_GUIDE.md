# Testing Guide - JobProspectorBE 🧪

Complete guide to test all endpoints and features of the passive lead engine.

---

## 🚀 Quick Start Testing

### 1. Start the Server
```bash
python main.py
```

Wait for:
```
[Scheduler] 🚀 PASSIVE DISCOVERY ENGINE STARTED
INFO: Application startup complete.
```

---

## 📋 Test All Endpoints (PowerShell)

### Copy-Paste Test Suite

Open PowerShell and run these commands one by one:

```powershell
# ============================================================
# TEST 1: Health Check
# ============================================================
Write-Host "`n=== TEST 1: Health Check ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8001/"


# ============================================================
# TEST 2: Scheduler Status
# ============================================================
Write-Host "`n=== TEST 2: Scheduler Status ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/status"


# ============================================================
# TEST 3: Manual Discovery (Small Test)
# ============================================================
Write-Host "`n=== TEST 3: Manual Discovery (5 companies) ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/manual?limit=5" -Method Post


# ============================================================
# TEST 4: Discover Companies Endpoint
# ============================================================
Write-Host "`n=== TEST 4: Discover Companies ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8001/api/discover" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"query": "test", "limit": 10}'


# ============================================================
# TEST 5: Check Hiring Status
# ============================================================
Write-Host "`n=== TEST 5: Check Hiring Status ===" -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://localhost:8001/api/hiring" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"companies": [{"company_name": "OpenAI", "website": "https://openai.com"}]}'


# ============================================================
# SUMMARY
# ============================================================
Write-Host "`n=== ALL TESTS COMPLETE ===" -ForegroundColor Green
Write-Host "Check the terminal running 'python main.py' for detailed logs" -ForegroundColor Yellow
```

---

## 🔍 Expected Responses

### Test 1: Health Check ✅

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

### Test 2: Scheduler Status ✅

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

### Test 3: Manual Discovery ✅

```json
{
  "success": true,
  "companies_found": 5,
  "companies": [
    {
      "company_name": "Acme Corp",
      "website": "https://acme.com",
      "funding_info": "Raised $10M Series A",
      "source": "Google News (TechCrunch)",
      "funding_round": "Series A"
    }
  ],
  "sources_used": ["Y Combinator", "Google News", "Crunchbase News"]
}
```

### Test 4: Discover Companies ✅

```json
{
  "success": true,
  "companies_found": 10,
  "companies_stored": 6,
  "errors": [
    "Company X: CRM API returned 400: company already exists"
  ],
  "companies": [
    {
      "company_name": "StartupX",
      "website": "https://startupx.com",
      "funding_info": "Y Combinator Winter 2026",
      "source": "Y Combinator",
      "crm_id": "12345",
      "stored": true
    }
  ]
}
```

### Test 5: Hiring Status ✅

```json
{
  "success": true,
  "results": [
    {
      "company_name": "OpenAI",
      "is_hiring": true,
      "confidence": "high",
      "job_count": 25,
      "roles": ["Research Engineer", "Software Engineer"],
      "career_page_url": "https://openai.com/careers"
    }
  ]
}
```

---

## 🧪 Individual Scraper Tests

### Test NewsAPI Scraper
```bash
python test_newsapi.py
```

**Expected output:**
```
================================================================================
Testing NewsAPI Scraper
================================================================================
[NewsAPI] 🔍 Starting scrape (limit=5)
[NewsAPI] 📡 API response received in 0.89s
[NewsAPI] 📰 Found 15 articles
[NewsAPI] ✅ Scrape complete: 3 companies from 15 articles

[RESULT] Found 3 companies
```

### Test All RSS Scrapers
```bash
python test_rss_scrapers.py
```

**Expected output:**
```
================================================================================
Testing Google News RSS Scraper
================================================================================
[GNews] 🔍 Starting scrape (limit=5)
[GNews] 📰 Found 20 articles in RSS feed
[GNews] ✅ Scrape complete: 5 companies from 20 articles

================================================================================
Testing Crunchbase News RSS Scraper
================================================================================
[CB] 🔍 Starting scrape (limit=5)
[CB] 📰 Found 15 articles in RSS feed
[CB] ✅ Scrape complete: 4 companies from 15 articles

================================================================================
Testing VentureBeat RSS Scraper
================================================================================
[VB] 🔍 Starting scrape (limit=5)
[VB] 📰 Found 18 total articles from 2 feeds
[VB] ✅ Scrape complete: 3 companies from 18 articles
```

---

## 📊 Monitoring Server Logs

When running tests, watch the server terminal for detailed logs:

```
[Discovery] 🚀 STARTING MULTI-SOURCE DISCOVERY
[Discovery] Enabled sources: 7
[Discovery] 🛠️ Starting parallel scraping with 7 workers

[YC] 🔍 Starting scrape (limit=10)
[YC] 📡 API response received in 1.23s (status=200)
[YC] 📊 Total companies in API: 12000
[YC] ✅ Scrape complete: 5 companies normalized

[GNews] 🔍 Starting scrape (limit=10)
[GNews] 📰 Found 25 articles in RSS feed
[GNews] 🎯 Filtered to 10 funding-related articles
[GNews] ✅ Scrape complete: 8 companies from 10 articles

[Discovery-Dedup] Starting deduplication of 20 companies
[Discovery-Dedup] Removed 2 duplicates by name, 1 by domain
[Discovery] ✅ DISCOVERY COMPLETE: 17 unique companies
```

---

## 🎯 Testing Passive Engine

### Test Daily Scheduled Discovery

**Option 1: Wait for 9 AM**
- Server automatically runs discovery at 9:00 AM daily
- Check logs at that time

**Option 2: Manually Trigger**
```powershell
# Simulate daily discovery
Invoke-RestMethod -Uri "http://localhost:8001/api/scheduler/manual?limit=100" -Method Post
```

**Expected Server Logs:**
```
[Scheduler] 🔧 Manual discovery triggered (limit=100)
[Discovery] 🚀 STARTING MULTI-SOURCE DISCOVERY
...
[Scheduler] ✅ Manual discovery complete: 45 companies
```

---

## ⚠️ Common Issues & Solutions

### Issue: "Connection refused"
**Cause:** Server not running  
**Solution:** Run `python main.py`

### Issue: "No companies found"
**Cause:** API keys missing or invalid  
**Solution:** Check `.env` file has all required keys

### Issue: "Scheduler not running"
**Cause:** APScheduler not installed  
**Solution:** `pip install apscheduler==3.10.4`

### Issue: RSS scrapers return 0 companies
**Cause:** No recent funding news or RSS feeds temporarily unavailable  
**Solution:** Normal! Try again in a few hours

### Issue: "CRM API returned 400: company already exists"
**Cause:** Company already in CRM (this is expected!)  
**Solution:** This is normal behavior - system prevents duplicates

---

## 📈 Performance Benchmarks

Expected performance on typical hardware:

| Endpoint | Avg Response Time | Companies Found |
|----------|-------------------|-----------------|
| `/api/discover` (limit=10) | 15-30s | 5-10 |
| `/api/discover` (limit=50) | 45-90s | 20-40 |
| `/api/hiring` (1 company) | 8-15s | N/A |
| `/api/scheduler/manual` | 30-60s | 10-30 |
| `/api/scheduler/status` | <1s | N/A |

---

## 🎉 Success Criteria

✅ All 5 tests return success responses  
✅ Server logs show scraper activity  
✅ Scheduler shows next run time  
✅ Companies stored in CRM (check for CRM IDs in response)  
✅ No critical errors in server logs  

---

## 📝 Test Checklist

- [ ] Health check returns API info
- [ ] Scheduler status shows "running: true"
- [ ] Manual discovery finds companies
- [ ] Discover endpoint returns companies
- [ ] Hiring endpoint detects job postings
- [ ] Individual scrapers work (test scripts)
- [ ] Server logs show detailed activity
- [ ] CRM stores companies successfully

---

## 🚀 Next Steps After Testing

1. **Monitor Daily Discovery**: Check logs at 9 AM tomorrow
2. **Review CRM**: Verify companies are being stored
3. **Test Career Page Scraping**: Run hiring checks on discovered companies
4. **Customize Sources**: Enable/disable scrapers as needed

**You're all set! The passive engine is working! 🎉**
