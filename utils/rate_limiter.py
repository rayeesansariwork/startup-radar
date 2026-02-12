"""
Rate limiter utility for managing API quotas across multiple threads.
"""

import time
import threading
import logging
from datetime import datetime
from config import settings

logger = logging.getLogger(__name__)

class GlobalRateLimiter:
    """
    Thread-safe token bucket rate limiter.
    Ensures that we don't exceed N requests per minute across all threads.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(GlobalRateLimiter, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        # Use Mistral rate limit setting (defaults to 60 RPM if not set)
        self.rpm = getattr(settings, 'mistral_rate_limit_rpm', 60)
        self.interval = 60.0 / self.rpm
        self.last_request_time = 0
        self.lock = threading.Lock()
        
        logger.info(f"⚡ Global Rate Limiter initialized: {self.rpm} RPM ({self.interval:.2f}s interval)")

    def acquire(self):
        """
        Block until a request slot is available.
        """
        with self.lock:
            current_time = time.time()
            elapsed = current_time - self.last_request_time
            
            if elapsed < self.interval:
                sleep_time = self.interval - elapsed
                logger.debug(f"⏳ Rate limit: Sleeping {sleep_time:.2f}s used {self.rpm} RPM")
                time.sleep(sleep_time)
                
            self.last_request_time = time.time()

# Global instance
rate_limiter = GlobalRateLimiter()
