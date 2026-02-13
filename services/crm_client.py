"""
CRM API Client - Store companies in external CRM
"""

import logging
import requests
from typing import Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


class CRMClient:
    """Client for interacting with external CRM API"""
    
    def __init__(self):
        self.base_url = settings.crm_base_url
        self.crm_email = settings.crm_email
        self.crm_password = settings.crm_password
        self.access_token = None
        self.token_expires_at = None
        self._obtain_access_token()
    
    def _obtain_access_token(self) -> bool:
        """
        Obtain a fresh access token from CRM API
        
        Returns:
            bool: True if token obtained successfully
        """
        try:
            url = f"{self.base_url}/token/obtain/"
            payload = {
                "email": self.crm_email,
                "password": self.crm_password
            }
            
            logger.info("🔑 Obtaining fresh CRM access token...")
            
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access')
                expires_in = data.get('expires_in', 28800)  # Default 8 hours
                
                logger.info(f"✅ Access token obtained successfully (expires in {expires_in}s)")
                
                # Update headers with new token
                self.headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                }
                return True
            else:
                logger.error(f"❌ Failed to obtain token: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error obtaining access token: {e}", exc_info=True)
            return False
    
    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def store_company(self, company_data: Dict) -> Dict:
        """
        Store a company in the CRM
        
        Args:
            company_data: Company information dict
        
        Returns:
            {'success': bool, 'company_id': int, 'error': str}
        """
        try:
            url = f"{self.base_url}/companies/"
            
            # Build payload according to CRM schema
            payload = {
                "company_name": company_data.get('company_name'),
                "website": company_data.get('website'),
                "contact_person": company_data.get('contact_person'),
                "technologies": company_data.get('technologies'),
                "corporate_phone": company_data.get('corporate_phone'),
                "employees": company_data.get('employees'),
                "industry": company_data.get('industry'),
                "company_linkedin_url": company_data.get('company_linkedin_url'),
                "company_address": company_data.get('company_address'),
                "company_city": company_data.get('company_city'),
                "company_state": company_data.get('company_state'),
                "company_country": company_data.get('company_country'),
                "company_phone": company_data.get('company_phone'),
                "company_zip": company_data.get('company_zip'),
                "social_data": company_data.get('social_data'),
                "extra_data": company_data.get('extra_data'),
                "emails": company_data.get('emails'),
                "telephones": company_data.get('telephones'),
                "tranco": company_data.get('tranco'),
                "majestic": company_data.get('majestic'),
                "umbrella": company_data.get('umbrella'),
                "social": company_data.get('social'),
                "seo_description": company_data.get('seo_description'),
                "annual_revenue": company_data.get('funding_info') or company_data.get('annual_revenue'),
                "total_funding": company_data.get('total_funding'),
                "latest_funding": company_data.get('published_date'),
                "latest_funding_amount": company_data.get('funding_info'),
                "last_raised_at": company_data.get('funding_round'),
                "number_of_retail_locations": company_data.get('number_of_retail_locations'),
                "source": "ENRICHMENT ENGINE"
            }
            
            logger.info(f"💾 Storing company in CRM: '{payload['company_name']}'")
            logger.debug(f"CRM endpoint: {url}")
            
            response = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=15
            )
            
            logger.info(f"📡 CRM responded: {response.status_code}")
            
            if response.status_code in [200, 201]:
                data = response.json()
                company_id = data.get('id')
                logger.info(f"✅ Company stored successfully - ID: {company_id}")
                return {
                    'success': True,
                    'company_id': company_id,
                    'data': data
                }
            else:
                error_msg = f"CRM API returned {response.status_code}: {response.text[:200]}"
                logger.error(f"❌ {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            logger.error(f"❌ Failed to store company: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_companies(self, limit: int = 100) -> Dict:
        """
        Fetch companies from CRM
        
        Args:
            limit: Maximum number of companies to fetch
        
        Returns:
            {'success': bool, 'companies': list}
        """
        try:
            url = f"{self.base_url}/companies/"
            params = {'limit': limit}
            
            logger.info(f"Fetching companies from CRM (limit={limit})")
            
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=15
            )
            
            if response.status_code == 200:
                companies = response.json()
                logger.info(f"✅ Fetched {len(companies)} companies from CRM")
                return {
                    'success': True,
                    'companies': companies
                }
            else:
                logger.error(f"Failed to fetch companies: {response.status_code}")
                return {
                    'success': False,
                    'companies': [],
                    'error': f"Status {response.status_code}"
                }
                
        except Exception as e:
            logger.error(f"Failed to fetch companies: {e}")
            return {
                'success': False,
                'companies': [],
                'error': str(e)
            }
