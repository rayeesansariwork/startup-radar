"""
Enhanced Hiring Detection System

Multi-layer fallback approach for maximum accuracy:
1. Platform APIs (Greenhouse, Lever, Ashby)
2. Smart career page detection
3. Playwright browser automation
4. Groq AI analysis
"""

from .checker import EnhancedHiringChecker

__all__ = ['EnhancedHiringChecker']
