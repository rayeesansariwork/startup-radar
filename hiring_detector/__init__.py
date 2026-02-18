"""
Enhanced Hiring Detection System

Multi-layer fallback approach for maximum accuracy:
1. Platform APIs (Greenhouse, Lever, Ashby)
2. Triangulation (ATS Backdoor → Sitemap → Organic Search)
3. Playwright browser automation
4. Mistral AI analysis
"""

from .checker import EnhancedHiringChecker
from .triangulator import HiringTriangulator

__all__ = ['EnhancedHiringChecker', 'HiringTriangulator']
