"""
Configuration management for JobProspectorBE
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # API Keys
    serper_api_key: str
    newsapi_key: Optional[str] = None  # NewsAPI.org key (free tier: 100 req/day)
    
    # CRM Configuration
    crm_base_url: str = "https://salesapi.gravityer.com/api/v1"
    crm_email: str
    crm_password: str
    crm_access_token: Optional[str] = None  # Optional - will be obtained dynamically
    
    # Application Settings
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    log_level: str = "INFO"
    
    # Rate Limiting
    max_concurrent_requests: int = 10
    retry_max_attempts: int = 3
    retry_wait_seconds: int = 2
    mistral_rate_limit_rpm: int = 60  # Mistral rate limit (conservative)
    mistral_min_interval_seconds: float = 8.0  # Force slower pacing to avoid 429 on low-tier keys
    
    # Mistral AI
    mistral_api_key: str
    mistral_api_key_for_talent: Optional[str] = None
    mistral_api_key_for_outreach: Optional[str] = None
    
    # Gmail SMTP Notifications
    gmail_user: Optional[str] = None
    gmail_app_password: Optional[str] = None
    notification_recipient: Optional[str] = None
    
    # SendGrid Configuration
    sendgrid_api_key: Optional[str] = None
    sendgrid_from_email: Optional[str] = None  # Validated sender email in SendGrid
    
    # Scheduler Configuration (values provided in IST, converted to UTC at runtime)
    daily_scrape_hour: int = 9    # IST hour to run daily discovery (0-23)
    daily_scrape_minute: int = 0  # IST minute to run daily discovery (0-59)

    # Daily Hiring Outreach Cron (values provided in IST, converted to UTC at runtime)
    sched_ist_hour: int = 15    # IST hour  for daily hiring-outreach cron
    sched_ist_minute: int = 40  # IST minute for daily hiring-outreach cron
    
    # Apollo API
    apollo_api_key: Optional[str] = None
    
    # Production Email Dispatcher
    send_real_emails: bool = False
    outreach_email_override_to: Optional[str] = None
    daily_outreach_email_enabled: bool = False
    shilpi_crm_email: Optional[str] = None
    shilpi_crm_password: Optional[str] = None
    shilpi_crm_access_token: Optional[str] = None

    # Talent API External Job Sync (optional)
    talent_api_enabled: bool = False
    talent_api_base_url: str = "https://talentapi-dev.gravityer.com"
    talent_api_email: Optional[str] = None
    talent_api_password: Optional[str] = None
    talent_api_rate_limit_seconds: int = 60
    talent_api_request_max_retries: int = 3
    talent_api_request_backoff_seconds: float = 1.5
    talent_api_default_role_id: Optional[str] = None
    talent_api_max_jobs_per_company: int = 3
    talent_api_debug: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()
