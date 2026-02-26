import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

class ApolloService:
    """Service to interact with the Apollo.io API to find C-Suite contacts."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.apollo.io/v1"

    def find_csuite_contacts(self, domain: str, company_name: str = None, limit: int = 3) -> List[Dict]:
        """
        Search Apollo for C-suite and engineering leaders at the given domain.
        If domain fails to find contacts, fallbacks to searching by company_name.
        Returns a list of dicts: [{"name": ..., "title": ..., "email": ...}]
        """
        if not self.api_key:
            logger.error("Apollo API key is missing. Cannot search contacts.")
            return []
            
        url = f"{self.base_url}/mixed_people/api_search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }
        
        # Searching for top executives and engineering/HR leaders
        payload = {
            "q_organization_domains": domain,
            "page": 1,
            "per_page": 10,  # fetch a bit more than limit to filter for valid emails
            "person_titles": [
                "CEO", "Chief Executive Officer", "Founder", "Co-Founder",
                "CTO", "Chief Technology Officer", "VP Engineering", "Vice President of Engineering",
                "Head of Engineering", "Engineering Manager",
                "Director of Engineering", "Head of Talent", "HR Director", "VP of Engineering"
            ]
        }
        
        logger.info(f"🔍 Searching Apollo.io for contacts at {domain}...")
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            
            if response.status_code != 200:
                logger.error(f"❌ Apollo API request failed: {response.status_code} - {response.text[:200]}")
                return []
                
            data = response.json()
            people = data.get("people", [])
            
            if not people and company_name:
                logger.info(f"⚠️ No contacts found for domain {domain}, retrying with company name {company_name}...")
                payload.pop("q_organization_domains", None)
                payload["q_organization_name"] = company_name
                
                fallback_response = requests.post(url, headers=headers, json=payload, timeout=20)
                if fallback_response.status_code == 200:
                    people = fallback_response.json().get("people", [])
                    if people:
                        logger.info(f"✅ Found {len(people)} contacts using company name {company_name}")
            
            contacts = []
            for person in people:
                person_id = person.get("id")
                if not person_id:
                    continue
                    
                # ── Step 2: Enrich to reveal email ──
                enrich_url = f"{self.base_url}/people/match"
                enrich_payload = {"id": person_id}
                
                enrich_resp = requests.post(enrich_url, headers=headers, json=enrich_payload, timeout=15)
                if enrich_resp.status_code == 200:
                    enrich_data = enrich_resp.json()
                    enriched_person = enrich_data.get("person", {})
                    
                    email = enriched_person.get("email")
                    if not email:
                        continue # Skip if no email is available even after enrichment
                        
                    name = enriched_person.get("name", "Unknown")
                    title = enriched_person.get("title", person.get("title", "Unknown Title"))
                    
                    contacts.append({
                        "name": name,
                        "title": title,
                        "email": email
                    })
                    
                    if len(contacts) >= limit:
                        break
                else:
                    logger.warning(f"⚠️ Failed to enrich Apollo contact {person_id}: {enrich_resp.status_code}")
                    
            logger.info(f"✅ Found and enriched {len(contacts)} contacts via Apollo for {domain}")
            return contacts
            
        except Exception as e:
            logger.error(f"❌ Apollo search failed for {domain}: {e}")
            return []
