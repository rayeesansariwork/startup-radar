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
    crm_access_token: str
    
    # Application Settings
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    log_level: str = "INFO"
    
    # Rate Limiting
    max_concurrent_requests: int = 10
    retry_max_attempts: int = 3
    retry_wait_seconds: int = 2
    mistral_rate_limit_rpm: int = 60  # Mistral rate limit (conservative)
    
    # Mistral AI
    mistral_api_key: str
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# Global settings instance
settings = Settings()
