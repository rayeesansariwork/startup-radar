"""
Mistral AI Analyzer - Extract company data from search results
"""

import logging
import json
from typing import List, Dict
from mistralai import Mistral

from config import settings

logger = logging.getLogger(__name__)


class MistralAnalyzer:
    """Use Mistral AI to extract company information from search results"""
    
    def __init__(self):
        self.mistral = Mistral(api_key=settings.mistral_api_key)
        logger.info("✅ Mistral Analyzer initialized")
    
    def extract_companies(self, search_results: List[Dict]) -> List[Dict]:
        """
        Extract company names and websites from search results
        
        Args:
            search_results: List of search result dicts with title, link, snippet
        
        Returns:
            List of {'company_name': str, 'website': str, 'funding_info': str}
        """
        try:
            logger.info(f"📥 Received {len(search_results)} search results for extraction")
            
            # Build context from search results
            context = ""
            for idx, result in enumerate(search_results[:20], 1):
                context += f"{idx}. {result['title']}\n"
                context += f"   URL: {result['link']}\n"
                context += f"   {result['snippet']}\n\n"
            
            logger.info(f"📝 Built context from search results ({len(context)} characters)")
            logger.debug(f"Context preview: {context[:500]}...")
            
            prompt = f"""Analyze these search results about recently funded companies and extract company information.

Search Results:
{context}

Extract all companies that received funding/investment. For each company, provide:
1. company_name: Official company name (clean, without extra text)
2. website: Company website URL (use the domain from the search result URL or find it in the snippet)
3. funding_info: Brief funding details if mentioned (amount, stage, date)

Return ONLY valid JSON array:
[
  {{
    "company_name": "Company Name",
    "website": "https://company.com",
    "funding_info": "Raised $10M Series A"
  }}
]

Important:
- Only include companies explicitly mentioned as funded/invested
- Extract clean company names (e.g., "Acme Corp" not "Acme Corp raises $10M")
- Ensure website URLs are valid (start with http:// or https://)
- If website not found in results, try to infer from company name (e.g., company.com)
- Return empty array [] if no funded companies found
"""
            
            logger.info(f"🤖 Sending prompt to Mistral (prompt length: {len(prompt)} chars)")
            logger.debug(f"Full prompt:\n{prompt}")
            
            response = self.mistral.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000
            )
            
            result_text = response.choices[0].message.content.strip()
            logger.info(f"📨 Received response from Mistral ({len(result_text)} chars)")
            logger.info(f"Raw Mistral response:\n{result_text}")
            
            # Clean markdown formatting
            original_text = result_text
            if '```json' in result_text:
                logger.debug("Detected ```json markdown, extracting...")
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                logger.debug("Detected ``` markdown, extracting...")
                result_text = result_text.split('```')[1].split('```')[0]
            
            result_text = result_text.strip()
            
            if result_text != original_text:
                logger.debug(f"Cleaned JSON:\n{result_text}")
            
            # Parse JSON
            logger.info("🔄 Parsing JSON response...")
            companies = json.loads(result_text)
            
            if not companies or len(companies) == 0:
                logger.warning("⚠️ Mistral returned EMPTY array!")
                logger.warning(f"This might mean no funding-related companies in search results")
                logger.warning(f"First search result was: {search_results[0]['title'] if search_results else 'None'}")
            else:
                logger.info(f"✅ Successfully extracted {len(companies)} companies!")
                for i, company in enumerate(companies, 1):
                    logger.info(f"  {i}. {company.get('company_name')} - {company.get('website')}")
            
            return companies
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON Parse Error: {e}")
            logger.error(f"Failed to parse: {result_text[:1000]}")
            return []
        except Exception as e:
            logger.error(f"❌ Company extraction failed: {e}", exc_info=True)
            return []
