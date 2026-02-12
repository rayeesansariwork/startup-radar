"""
Initialize models package
"""

from .requests import DiscoverRequest, HiringRequest
from .responses import DiscoverResponse, HiringResponse, CompanyInfo, HiringInfo

__all__ = [
    'DiscoverRequest', 'HiringRequest',
    'DiscoverResponse', 'HiringResponse',
    'CompanyInfo', 'HiringInfo'
]
