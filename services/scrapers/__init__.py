"""
Scrapers package - Multiple data source scrapers
"""

from .base_scraper import BaseScraper
from .yc_scraper import YCombinatorScraper
from .techcrunch_scraper import TechCrunchScraper
from .producthunt_scraper import ProductHuntScraper
from .news_api_scraper import NewsAPIScraper
from .google_news_scraper import GoogleNewsScraper
from .venturebeat_scraper import VentureBeatScraper

__all__ = [
    'BaseScraper', 
    'YCombinatorScraper', 
    'TechCrunchScraper', 
    'ProductHuntScraper', 
    'NewsAPIScraper',
    'GoogleNewsScraper',
    'VentureBeatScraper'
]
