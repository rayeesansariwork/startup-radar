"""
Serper API Service - Web search for funded companies
"""

import logging
import requests
from typing import Dict, List
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


class SerperService:
    """Service for searching the web using Serper API"""
    
    API_ENDPOINT = "https://google.serper.dev/search"
    
    def __init__(self):
        self.api_key = settings.serper_api_key
    
    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(self, query: str, num_results: int = 10) -> Dict:
        """
        Search for companies using Serper API
        
        Args:
            query: Search query (e.g., "SaaS startups raised funding 2026")
            num_results: Number of search results to return
        
        Returns:
            {
                'success': bool,
                'results': [{'title': str, 'link': str, 'snippet': str}],
                'query': str
            }
        """
        try:
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json"
            }
            
            payload = {
                "q": query,
                "num": min(num_results, 100)
            }
            
            logger.info(f"🔍 Serper Search: '{query}' (requesting {num_results} results)")
            start_time = datetime.now()
            
            response = requests.post(
                self.API_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            response_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"📡 Serper API responded in {response_time:.2f}s (Status: {response.status_code})")
            
            if response.status_code != 200:
                logger.error(f"❌ Serper API error {response.status_code}: {response.text[:500]}")
                return {
                    'success': False,
                    'error': f"{response.status_code}: {response.text}",
                    'query': query,
                    'results': []
                }
            
            data = response.json()
            
            # Extract organic results
            organic = data.get('organic', [])
            
            results = []
            for item in organic:
                results.append({
                    'title': item.get('title', ''),
                    'link': item.get('link', ''),
                    'snippet': item.get('snippet', ''),
                    'date': item.get('date')
                })
            
            logger.info(f"✅ Serper returned {len(results)} organic results")
            if results:
                logger.info(f"📄 Sample result: {results[0]['title'][:80]}...")
                logger.debug(f"First result link: {results[0]['link']}")
            else:
                logger.warning("⚠️ No organic results returned by Serper!")
            
            return {
                'success': True,
                'results': results,
                'query': query
            }
            
        except Exception as e:
            logger.error(f"❌ Serper search exception: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'query': query,
                'results': []
            }
