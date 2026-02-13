"""
Scheduled Discovery Service - Automated passive company discovery
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .company_discovery import CompanyDiscoveryService

logger = logging.getLogger(__name__)


class ScheduledDiscoveryService:
    """Service for running automated company discovery on a schedule"""
    
    def __init__(self, crm_client=None, notification_service=None):
        """
        Initialize scheduled discovery service
        
        Args:
            crm_client: CRMClient instance for storing discovered companies
            notification_service: NotificationService instance for sending email notifications
        """
        self.scheduler = BackgroundScheduler()
        self.discovery_service = CompanyDiscoveryService(
            enable_yc=True,
            enable_techcrunch=True,
            enable_newsapi=True,
            enable_google_news=True,
            enable_venturebeat=True,
            enable_producthunt=False  # Still placeholder
        )
        self.crm_client = crm_client
        self.notification_service = notification_service
        self.is_running = False
        
        if crm_client:
            logger.info("[Scheduler] CRM storage enabled")
        else:
            logger.warning("[Scheduler] CRM storage disabled - companies will not be stored")
        
        if notification_service:
            logger.info("[Scheduler] Email notifications enabled")
        else:
            logger.warning("[Scheduler] Email notifications disabled")
    
    def start(self, 
              daily_hour: int = 9, 
              daily_minute: int = 0,
              enable_hourly: bool = False,
              hourly_interval: int = 3):
        """
        Start the scheduled discovery jobs
        
        Args:
            daily_hour: Hour to run daily discovery (0-23)
            daily_minute: Minute to run daily discovery (0-59)
            enable_hourly: Enable hourly discovery checks
            hourly_interval: Hours between hourly discoveries
        """
        if self.is_running:
            logger.warning("[Scheduler] Scheduler already running!")
            return
        
        try:
            # Daily comprehensive discovery
            self.scheduler.add_job(
                self.run_daily_discovery,
                CronTrigger(hour=daily_hour, minute=daily_minute),
                id='daily_discovery',
                name='Daily Company Discovery',
                replace_existing=True
            )
            logger.info(f"[Scheduler] ✅ Daily discovery scheduled at {daily_hour:02d}:{daily_minute:02d}")
            
            # Optional: Hourly quick checks
            if enable_hourly:
                self.scheduler.add_job(
                    self.run_hourly_discovery,
                    CronTrigger(hour=f'*/{hourly_interval}'),
                    id='hourly_discovery',
                    name='Hourly Company Discovery',
                    replace_existing=True
                )
                logger.info(f"[Scheduler] ✅ Hourly discovery enabled (every {hourly_interval} hours)")
            
            # Start the scheduler
            self.scheduler.start()
            self.is_running = True
            
            logger.info("=" * 60)
            logger.info("[Scheduler] 🚀 PASSIVE DISCOVERY ENGINE STARTED")
            logger.info(f"[Scheduler] Daily job: {daily_hour:02d}:{daily_minute:02d}")
            logger.info(f"[Scheduler] Hourly job: {'Enabled' if enable_hourly else 'Disabled'}")
            logger.info(f"[Scheduler] Active sources: {len(self.discovery_service.scrapers)}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"[Scheduler] ❌ Failed to start scheduler: {e}", exc_info=True)
    
    def stop(self):
        """Stop the scheduled discovery jobs"""
        if not self.is_running:
            logger.warning("[Scheduler] Scheduler is not running!")
            return
        
        try:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("[Scheduler] 🛑 Scheduler stopped")
        except Exception as e:
            logger.error(f"[Scheduler] ❌ Failed to stop scheduler: {e}", exc_info=True)
    
    def run_daily_discovery(self):
        """Run comprehensive discovery from all sources"""
        try:
            logger.info("=" * 60)
            logger.info(f"[Scheduler] 🌅 DAILY DISCOVERY STARTED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 60)
            
            start_time = datetime.now()
            
            # Run discovery with higher limit for daily comprehensive search
            result = self.discovery_service.discover_companies(limit=100)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if result['success']:
                companies_found = len(result.get('companies', []))
                sources_used = result.get('sources_used', [])
                
                logger.info("=" * 60)
                logger.info(f"[Scheduler] ✅ DAILY DISCOVERY COMPLETE")
                logger.info(f"[Scheduler] Duration: {duration:.2f}s")
                logger.info(f"[Scheduler] Companies found: {companies_found}")
                logger.info(f"[Scheduler] Sources: {', '.join(sources_used)}")
                logger.info("=" * 60)
                
                # Store companies in CRM if client provided
                if self.crm_client and companies_found > 0:
                    try:
                        logger.info(f"[Scheduler] 💾 Storing {companies_found} companies in CRM...")
                        stored_count = self._store_companies_in_crm(result.get('companies', []))
                        logger.info(f"[Scheduler] ✅ Stored {stored_count}/{companies_found} companies in CRM")
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to store companies in CRM: {e}", exc_info=True)
                
                # Send email notification
                if self.notification_service:
                    try:
                        logger.info("[Scheduler] 📧 Sending email notification...")
                        success = self.notification_service.send_discovery_notification(result, "daily")
                        if success:
                            logger.info("[Scheduler] ✅ Email notification sent successfully")
                        else:
                            logger.warning("[Scheduler] ⚠️ Email notification failed (check logs)")
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to send notification: {e}", exc_info=True)
                
            else:
                error = result.get('error', 'Unknown error')
                logger.error(f"[Scheduler] ❌ Daily discovery failed: {error}")
                
        except Exception as e:
            logger.error(f"[Scheduler] ❌ Daily discovery exception: {type(e).__name__}: {e}", exc_info=True)
    
    def run_hourly_discovery(self):
        """Run quick discovery check (smaller limit)"""
        try:
            logger.info(f"[Scheduler] ⏰ Hourly discovery check - {datetime.now().strftime('%H:%M:%S')}")
            
            # Run discovery with smaller limit for hourly checks
            result = self.discovery_service.discover_companies(limit=20)
            
            if result['success']:
                companies_found = len(result.get('companies', []))
                logger.info(f"[Scheduler] ✅ Hourly check complete: {companies_found} companies found")
                
                # Store companies in CRM if client provided
                if self.crm_client and companies_found > 0:
                    try:
                        stored_count = self._store_companies_in_crm(result.get('companies', []))
                        logger.info(f"[Scheduler] 💾 Stored {stored_count}/{companies_found} companies in CRM")
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to store: {e}")
                
                # Send email notification
                if self.notification_service and companies_found > 0:
                    try:
                        self.notification_service.send_discovery_notification(result, "hourly")
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to send notification: {e}")
                
            else:
                logger.warning(f"[Scheduler] ⚠️ Hourly check failed: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"[Scheduler] ❌ Hourly discovery exception: {e}")
    

    
    def run_manual_discovery(self, limit: Optional[int] = 50) -> Dict:
        """
        Manually trigger discovery (for testing)
        
        Args:
            limit: Limit on companies to discover
        
        Returns:
            discovery result dict
        """
        logger.info(f"[Scheduler] 🔧 Manual discovery triggered (limit={limit})")
        
        try:
            result = self.discovery_service.discover_companies(limit=limit)
            
            if result['success']:
                companies_found = len(result.get('companies', []))
                logger.info(f"[Scheduler] ✅ Manual discovery complete: {companies_found} companies")
                
                # Store companies in CRM if client provided
                if self.crm_client and companies_found > 0:
                    try:
                        logger.info(f"[Scheduler] 💾 Storing {companies_found} companies in CRM...")
                        stored_count = self._store_companies_in_crm(result.get('companies', []))
                        logger.info(f"[Scheduler] ✅ Stored {stored_count}/{companies_found} companies in CRM")
                        result['stored_count'] = stored_count
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to store companies in CRM: {e}", exc_info=True)
                        result['storage_error'] = str(e)
                
                # Send email notification
                if self.notification_service:
                    try:
                        logger.info("[Scheduler] 📧 Sending email notification...")
                        success = self.notification_service.send_discovery_notification(result, "manual")
                        if success:
                            logger.info("[Scheduler] ✅ Email notification sent successfully")
                        else:
                            logger.warning("[Scheduler] ⚠️ Email notification failed (check logs)")
                    except Exception as e:
                        logger.error(f"[Scheduler] ❌ Failed to send notification: {e}", exc_info=True)
            
            return result
            
        except Exception as e:
            logger.error(f"[Scheduler] ❌ Manual discovery failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'companies': []
            }
    
    def get_status(self) -> Dict:
        """Get scheduler status and next run times"""
        if not self.is_running:
            return {
                'running': False,
                'message': 'Scheduler is not running'
            }
        
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'N/A'
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run
            })
        
        return {
            'running': True,
            'active_sources': len(self.discovery_service.scrapers),
            'jobs': jobs
        }
    
    def _store_companies_in_crm(self, companies: list[Dict]) -> int:
        """
        Store discovered companies in CRM
        
        Args:
            companies: List of company dicts from discovery
        
        Returns:
            int: Number of companies successfully stored
        """
        if not self.crm_client:
            logger.warning("[Scheduler] No CRM client available for storage")
            return 0
        
        stored_count = 0
        
        for company in companies:
            try:
                result = self.crm_client.store_company(company)
                if result.get('success'):
                    stored_count += 1
                    logger.debug(f"[Scheduler] ✅ Stored: {company.get('company_name')}")
                else:
                    logger.warning(f"[Scheduler] ⚠️ Failed to store {company.get('company_name')}: {result.get('error')}")
            except Exception as e:
                logger.error(f"[Scheduler] ❌ Error storing {company.get('company_name')}: {e}")
        
        return stored_count
