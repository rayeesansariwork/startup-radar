"""
Enhanced Mistral AI analyzer for extracting job information
"""

import logging
import json
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False


class JobAnalyzer:
    """Analyze text/HTML to extract job information using Mistral AI"""
    
    def __init__(self, mistral_api_key: str):
        if not MISTRAL_AVAILABLE:
            raise ImportError("Mistral package not installed")
        
        self.mistral = Mistral(api_key=mistral_api_key)
    
    def analyze_career_page(self, text: str, company_name: str) -> Dict:
        """
        Analyze career page text to extract job information
        
        Args:
            text: Page text content
            company_name: Company name for context
        
        Returns:
            Dict with is_hiring, job_roles, hiring_summary
        """
        try:
            # Truncate text to avoid token limits
            text = text[:10000]
            
            prompt = f"""Analyze this career page content from {company_name} and extract job information.

Content:
{text}

Extract:
1. is_hiring: Are they currently hiring? (true/false)
2. job_roles: List of specific job titles/roles (array of strings)
3. hiring_summary: Brief summary of hiring status (string, max 200 chars)

Return ONLY valid JSON in this exact format:
{{
  "is_hiring": true/false,
  "job_roles": ["Job Title 1", "Job Title 2", ...],
  "hiring_summary": "brief summary here"
}}

Important:
- Only include REAL job titles you find
- If you see "No open positions" or similar, set is_hiring to false
- Be specific with job titles (e.g., "Senior Software Engineer" not just "Engineer")
- Include up to 20 job titles maximum
"""

            response = self.mistral.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Clean markdown formatting
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            result_text = result_text.strip()
            
            # Parse JSON
            data = json.loads(result_text)
            
            logger.info(f"✅ Mistral analysis: {len(data.get('job_roles', []))} jobs found")
            
            return {
                'is_hiring': data.get('is_hiring', False),
                'job_roles': data.get('job_roles', [])[:20],  # Limit to 20
                'hiring_summary': data.get('hiring_summary', '')[:200]  # Limit to 200 chars
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Mistral returned invalid JSON: {e}")
            logger.debug(f"Response was: {result_text[:500]}")
            return {
                'is_hiring': False,
                'job_roles': [],
                'hiring_summary': 'Error: Could not parse AI response'
            }
        except Exception as e:
            logger.error(f"Mistral analysis failed: {e}")
            return {
                'is_hiring': False,
                'job_roles': [],
                'hiring_summary': f'Error: {str(e)}'
            }
    
    def analyze_job_list(self, job_titles: List[str], company_name: str) -> Dict:
        """
        Analyze a list of job titles to clean and categorize
        
        Args:
            job_titles: List of potential job titles
            company_name: Company name
        
        Returns:
            Dict with cleaned job_roles
        """
        if not job_titles:
            return {
                'is_hiring': False,
                'job_roles': [],
                'hiring_summary': 'No jobs found'
            }
        
        try:
            prompt = f"""Given these potential job titles from {company_name}, clean and filter them.

Raw titles:
{json.dumps(job_titles)}

Tasks:
1. Remove duplicates
2. Remove non-job entries (like "About Us", "FAQ", etc.)
3. Standardize formatting
4. Keep only real job titles

Return ONLY a JSON array of cleaned job titles:
["Job Title 1", "Job Title 2", ...]
"""

            response = self.mistral.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Clean markdown
            if '```' in result_text:
                result_text = result_text.split('```')[1] if '```' in result_text else result_text
                if 'json' in result_text[:10].lower():
                    result_text = result_text[4:]
                result_text = result_text.replace('```', '').strip()
            
            cleaned_jobs = json.loads(result_text)
            
            return {
                'is_hiring': len(cleaned_jobs) > 0,
                'job_roles': cleaned_jobs[:20],
                'hiring_summary': f"Found {len(cleaned_jobs)} open positions"
            }
            
        except Exception as e:
            logger.error(f"Job list analysis failed: {e}")
            return {
                'is_hiring': len(job_titles) > 0,
                'job_roles': job_titles[:20],
                'hiring_summary': f"Found {len(job_titles)} potential positions"
            }

    def generate_outreach_mail(self, company_name: str, job_roles: List[str], funding_info: str = None) -> Dict:
        """
        Generate a personalized outreach email for a hiring company using Mistral AI.

        Args:
            company_name: Name of the company
            job_roles: List of job titles they are hiring for
            funding_info: Optional funding information

        Returns:
            Dict with subject, body, to_hint fields
        """
        if not job_roles:
            return None

        try:
            # Identify the dominant hiring category
            roles_text = ", ".join(job_roles[:10])

            prompt = f"""Generate a short, professional B2B cold outreach email for a staffing company called Gravity (info@gravityer.com) to send to {company_name}.

Context:
- {company_name} is actively hiring for these roles: {roles_text}
- {"They recently received funding: " + funding_info if funding_info else "They appear to have recently received funding."}
- Gravity provides cost-effective staff augmentation for tech/engineering roles.

Rules:
- Keep it under 120 words.
- Tone: confident, warm, not pushy.
- Mention the specific team/department they are scaling (infer from the job roles — e.g. "Backend Engineering", "Sales", "Data" etc.)
- Do NOT use placeholder brackets like [Name].
- End with a soft CTA to reply or reach out to info@gravityer.com.

Return ONLY valid JSON:
{{
  "subject": "email subject line",
  "body": "full email body text",
  "team_focus": "the main department/team they are scaling"
}}"""

            response = self.mistral.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500
            )

            result_text = response.choices[0].message.content.strip()

            # Clean markdown formatting
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]

            result_text = result_text.strip()
            data = json.loads(result_text)

            logger.info(f"✉️ Outreach mail generated for {company_name} (focus: {data.get('team_focus', 'N/A')})")

            return {
                'subject': data.get('subject', ''),
                'body': data.get('body', ''),
                'team_focus': data.get('team_focus', ''),
            }

        except Exception as e:
            logger.error(f"Mail generation failed for {company_name}: {e}")
            return None
