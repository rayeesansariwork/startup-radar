"""
Pydantic models for API requests
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class DiscoverRequest(BaseModel):
    """Request model for /api/discover endpoint"""
    query: str = Field(
        ...,
        description="Search query for finding funded companies",
        example="SaaS startups raised funding 2026"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of companies to search for"
    )


class HiringRequest(BaseModel):
    """Request model for /api/hiring endpoint"""
    companies: List[Dict[str, Any]] = Field(
        ...,
        description="List of companies from /discover endpoint to check for hiring"
    )
