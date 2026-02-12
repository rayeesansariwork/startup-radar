"""
Pydantic models for API responses
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class CompanyInfo(BaseModel):
    """Company information model"""
    company_name: str
    website: Optional[str] = None
    funding_info: Optional[str] = None
    crm_id: Optional[int] = None
    stored: bool = False
    error: Optional[str] = None
    # New fields for multi-source discovery
    source: Optional[str] = None  # e.g., "Y Combinator", "TechCrunch"
    batch: Optional[str] = None  # For YC companies (e.g., "W26")
    funding_round: Optional[str] = None  # e.g., "Series A", "Seed"
    description: Optional[str] = None  # Brief company description


class DiscoverResponse(BaseModel):
    """Response model for /api/discover endpoint"""
    success: bool
    companies_found: int
    companies_stored: int
    errors: List[str] = []
    companies: List[CompanyInfo]


class HiringInfo(BaseModel):
    """Hiring information for a company"""
    company_id: Optional[int] = None
    company_name: str
    is_hiring: bool
    job_count: int
    job_roles: List[str] = []
    career_page_url: Optional[str] = None
    hiring_summary: Optional[str] = None
    detection_method: Optional[str] = None


class HiringResponse(BaseModel):
    """Response model for /api/hiring endpoint"""
    success: bool
    total_companies: int
    hiring_companies: int
    results: List[HiringInfo]
