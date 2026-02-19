"""
JobProspectorBE - FastAPI Application

Search for funded companies via Serper API and scrape their job listings
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from typing import List

from config import settings
from models import (
    DiscoverRequest, DiscoverResponse,
    HiringRequest, HiringResponse,
    CompanyInfo, HiringInfo,
    FindJobsRequest, FindJobsResponse     # New imports
)
from services import CRMClient, CompanyDiscoveryService, ScheduledDiscoveryService, NotificationService, HiringPageFinderService
from hiring_detector.checker import EnhancedHiringChecker
from hiring_detector.analyzer import JobAnalyzer
from routes.daily_outreach import router as daily_outreach_router

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize services
crm = CRMClient()
crm = CRMClient()
hiring_checker = EnhancedHiringChecker(mistral_api_key=settings.mistral_api_key)
hiring_page_finder = HiringPageFinderService()

# Initialize notification service (if credentials provided)
notification_service = None
has_gmail = settings.gmail_user and settings.gmail_app_password
has_sendgrid = settings.sendgrid_api_key and settings.sendgrid_from_email

if (has_gmail or has_sendgrid) and settings.notification_recipient:
    notification_service = NotificationService(
        gmail_user=settings.gmail_user,
        gmail_app_password=settings.gmail_app_password,
        recipient=settings.notification_recipient,
        sendgrid_api_key=settings.sendgrid_api_key,
        sendgrid_from_email=settings.sendgrid_from_email
    )
    method = "SendGrid" if has_sendgrid else "Gmail SMTP"
    logger.info(f"✅ Email notifications enabled via {method}")
else:
    logger.warning("⚠️ Email notifications disabled - No valid credentials configured")

# Initialize scheduled discovery (passive engine)
scheduler = ScheduledDiscoveryService(
    crm_client=crm,
    notification_service=notification_service
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for FastAPI"""
    # Startup
    logger.info("Starting JobProspectorBE...")
    # Start passive discovery engine
    scheduler.start(
        daily_hour=settings.daily_scrape_hour,
        daily_minute=settings.daily_scrape_minute,
        enable_hourly=False,  # Disable hourly for now
        hourly_interval=3
    )

    # ── Schedule daily hiring outreach at 10:10 UTC ──────────────────────
    from apscheduler.triggers.cron import CronTrigger
    from routes.daily_outreach import _stream
    from datetime import datetime, timedelta

    def _run_daily_outreach():
        """Synchronous wrapper that consumes the full outreach stream."""
        target_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info("⏰ [Cron] Daily hiring outreach triggered for %s", target_date)

        async def _consume():
            async for _ in _stream(target_date, page_size=15):
                pass  # each yield does its own work (hiring check, mail gen, DB save)

        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_consume())
            else:
                loop.run_until_complete(_consume())
        except RuntimeError:
            asyncio.run(_consume())

        logger.info("✅ [Cron] Daily hiring outreach finished for %s", target_date)

    scheduler.scheduler.add_job(
        _run_daily_outreach,
        trigger=CronTrigger(hour=10, minute=10, timezone="UTC"),
        id="daily_hiring_outreach",
        name="Daily Hiring Outreach (10:10 UTC)",
        replace_existing=True,
    )
    logger.info("📅 Daily hiring outreach scheduled at 10:10 UTC")

    logger.info("JobProspectorBE started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down JobProspectorBE...")
    scheduler.stop()
    logger.info("JobProspectorBE shut down successfully")



# Initialize FastAPI app
app = FastAPI(
    title="JobProspectorBE",
    description="Discover funded companies and scrape their job listings",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(daily_outreach_router)


@app.get("/")
async def root():
    return {
        "message": "JobProspectorBE API",
        "version": "1.0.0",
        "endpoints": {
            "/api/discover": "Discover funded companies",
            "/api/hiring": "Check hiring status",
            "/api/find-jobs": "Find and extract jobs from a company website",
            "/api/v1/daily-hiring-outreach/": "SSE: daily hiring outreach (fetch + detect + mail)",
            "/api/scheduler/status": "Get scheduler status",
            "/api/scheduler/manual": "Manually trigger discovery"
        },
        "scheduled_jobs": {
            "daily_hiring_outreach": "Runs automatically at 10:10 UTC every day",
        }
    }


@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get status of the passive discovery scheduler"""
    try:
        status = scheduler.get_status()
        return {
            "success": True,
            **status
        }
    except Exception as e:
        logger.error(f"Failed to get scheduler status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/manual")
async def trigger_manual_discovery(limit: int = 50):
    """Manually trigger discovery (for testing)"""
    try:
        result = scheduler.run_manual_discovery(limit=limit)
        return result
    except Exception as e:
        logger.error(f"Manual discovery failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/discover", response_model=DiscoverResponse)
async def discover_companies(request: DiscoverRequest):
    """
    STEP 1: Search for recently funded companies and store them in CRM
    
    Flow:
    1. Use CompanyDiscoveryService to scrape from multiple sources (YC, TechCrunch, etc.)
    2. Deduplicate companies across sources
    3. Store each company in CRM via POST request
    4. Return summary with successes and errors
    """
    try:
        logger.info("="*60)
        logger.info(f"🚀 DISCOVER ENDPOINT CALLED")
        logger.info(f"Query: '{request.query}' (NOTE: Multi-source discovery, query is currently ignored)")
        logger.info(f"Limit: {request.limit}")
        logger.info("="*60)
        
        # Step 1: Discover companies from multiple sources
        logger.info("STEP 1: Discovering companies from multiple sources...")
        discovery_service = CompanyDiscoveryService(
            enable_yc=True,
            enable_techcrunch=True
        )
        
        discovery_result = discovery_service.discover_companies(request.limit)
        
        if not discovery_result['success']:
            logger.error(f"❌ Company discovery failed: {discovery_result.get('error')}")
            raise HTTPException(
                status_code=500,
                detail=f"Company discovery failed: {discovery_result.get('error')}"
            )
        
        companies = discovery_result['companies']
        sources_used = discovery_result.get('sources_used', [])
        logger.info(f"✅ STEP 1 Complete: Discovered {len(companies)} companies from sources: {', '.join(sources_used)}")
        
        if not companies:
            logger.warning("⚠️ No companies discovered - returning empty result")
            return DiscoverResponse(
                success=True,
                companies_found=0,
                companies_stored=0,
                errors=["No companies found in any source"],
                companies=[]
            )
        
        # Step 2: Store companies in CRM (with async concurrency)
        async def store_company_async(company_data):
            """Async wrapper for storing a company"""
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, crm.store_company, company_data)
        
        # Limit concurrent requests
        semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        
        async def store_with_limit(company_data):
            async with semaphore:
                return await store_company_async(company_data)
        
        # Store all companies concurrently
        tasks = [store_with_limit(company) for company in companies]
        store_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        company_infos = []
        errors = []
        stored_count = 0
        
        for idx, (company_data, store_result) in enumerate(zip(companies, store_results)):
            if isinstance(store_result, Exception):
                error_msg = f"{company_data['company_name']}: {str(store_result)}"
                errors.append(error_msg)
                company_infos.append(CompanyInfo(
                    company_name=company_data['company_name'],
                    website=company_data.get('website'),
                    funding_info=company_data.get('funding_info'),
                    source=company_data.get('source'),
                    batch=company_data.get('batch'),
                    funding_round=company_data.get('funding_round'),
                    description=company_data.get('description'),
                    stored=False,
                    error=str(store_result)
                ))
            elif store_result['success']:
                stored_count += 1
                company_infos.append(CompanyInfo(
                    company_name=company_data['company_name'],
                    website=company_data.get('website'),
                    funding_info=company_data.get('funding_info'),
                    source=company_data.get('source'),
                    batch=company_data.get('batch'),
                    funding_round=company_data.get('funding_round'),
                    description=company_data.get('description'),
                    crm_id=store_result.get('company_id'),
                    stored=True
                ))
            else:
                errors.append(f"{company_data['company_name']}: {store_result.get('error')}")
                company_infos.append(CompanyInfo(
                    company_name=company_data['company_name'],
                    website=company_data.get('website'),
                    funding_info=company_data.get('funding_info'),
                    source=company_data.get('source'),
                    batch=company_data.get('batch'),
                    funding_round=company_data.get('funding_round'),
                    description=company_data.get('description'),
                    stored=False,
                    error=store_result.get('error')
                ))
        
        logger.info(f"✅ Discovery complete: {stored_count}/{len(companies)} companies stored")
        
        return DiscoverResponse(
            success=True,
            companies_found=len(companies),
            companies_stored=stored_count,
            errors=errors,
            companies=company_infos
        )
        
    except Exception as e:
        logger.error(f"Discovery failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/hiring", response_model=HiringResponse)
async def get_hiring_info(request: HiringRequest):
    """
    STEP 2: Scrape job listings for discovered companies
    
    Flow:
    1. Use companies from the request (discovered in Step 1)
    2. For each company, use Enhanced Hiring Checker (4 layers):
       - Layer 1: Platform APIs (Greenhouse, Lever, Ashby)
       - Layer 2: Career page detection
       - Layer 3: Playwright browser scraping
       - Layer 4: Mistral AI analysis
    3. Return job listings for each company
    
    NOTE: Pass the companies discovered in /api/discover to this endpoint
    """
    try:
        logger.info("🔍 Starting hiring info scraping")
        
        # Get companies from request - these should be the companies from /discover
        if not request.companies or len(request.companies) == 0:
            raise HTTPException(
                status_code=400,
                detail="No companies provided. Please run /api/discover first and pass the companies here."
            )
        
        companies = request.companies
        logger.info(f"📋 Processing {len(companies)} companies")
        
        # Step 2: Check hiring for each company (with async concurrency)
        async def check_hiring_async(company):
            """Async wrapper for hiring check"""
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                hiring_checker.check_hiring,
                company.get('company_name', ''),
                company.get('website', '')
            )
        
        # Limit concurrent requests
        semaphore = asyncio.Semaphore(settings.max_concurrent_requests)
        
        async def check_with_limit(company):
            async with semaphore:
                try:
                    return await check_hiring_async(company)
                except Exception as e:
                    logger.error(f"Hiring check failed for {company.get('company_name')}: {e}")
                    return {
                        'is_hiring': False,
                        'job_count': 0,
                        'job_roles': [],
                        'error': str(e)
                    }
        
        # Check all companies concurrently
        tasks = [check_with_limit(company) for company in companies]
        hiring_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        # Initialize mail generator
        mail_generator = JobAnalyzer(settings.mistral_api_key) if settings.mistral_api_key else None
        
        hiring_infos = []
        hiring_count = 0
        
        for company, result in zip(companies, hiring_results):
            if isinstance(result, Exception):
                hiring_infos.append(HiringInfo(
                    company_id=company.get('crm_id'),
                    company_name=company.get('company_name', 'Unknown'),
                    is_hiring=False,
                    job_count=0,
                    job_roles=[],
                    hiring_summary=f"Error: {str(result)}"
                ))
            else:
                company_name = company.get('company_name', 'Unknown')
                job_roles = result.get('job_roles', [])
                is_hiring = result.get('is_hiring', False)
                
                if is_hiring:
                    hiring_count += 1
                
                # Generate outreach mail for hiring companies
                custom_mail = None
                if is_hiring and job_roles and mail_generator:
                    try:
                        custom_mail = mail_generator.generate_outreach_mail(
                            company_name=company_name,
                            job_roles=job_roles,
                            funding_info=company.get('funding_info')
                        )
                    except Exception as mail_err:
                        logger.warning(f"Mail generation failed for {company_name}: {mail_err}")
                
                hiring_infos.append(HiringInfo(
                    company_id=company.get('crm_id'),
                    company_name=company_name,
                    is_hiring=is_hiring,
                    job_count=result.get('job_count', 0),
                    job_roles=job_roles,
                    custom_mail=custom_mail,
                    career_page_url=result.get('career_page_url'),
                    hiring_summary=result.get('hiring_summary'),
                    detection_method=result.get('detection_method')
                ))
        
        logger.info(f"✅ Hiring info complete: {hiring_count}/{len(companies)} companies hiring")
        
        return HiringResponse(
            success=True,
            total_companies=len(companies),
            hiring_companies=hiring_count,
            results=hiring_infos
        )
        
    except Exception as e:
        logger.error(f"Hiring info scraping failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/find-jobs", response_model=FindJobsResponse)
async def find_jobs(request: FindJobsRequest):
    """
    Find and extract job openings from a company's career page.
    
    Steps:
    1. Search for career page using Serper
    2. Scrape content
    3. Extract jobs using Mistral AI
    """
    try:
        logger.info(f"🔎 Finding jobs for: {request.url}")
        
        # Run in threadpool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, 
            hiring_page_finder.find_hiring_page,
            request.url
        )
        
        if "error" in result:
            # If strictly following user instruction "Handle errors: Return {error: ...}"
            # But since we use a response model, we should return the model with error field.
            return FindJobsResponse(error=result["error"])
            
        return FindJobsResponse(
            career_page_url=result.get("career_page_url"),
            jobs=result.get("jobs", [])
        )
        
    except Exception as e:
        logger.error(f"Find jobs failed: {e}", exc_info=True)
        return FindJobsResponse(error=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True
    )
