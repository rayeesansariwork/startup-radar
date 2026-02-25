"""
Enhanced Mistral AI analyzer for extracting job information
"""

import logging
import json
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# Map role keywords to team labels used in outreach copy
ROLE_TEAM_MAP = [
    (["machine learning", "ml ", "data scientist", "ai ", "nlp", "llm"], "ML/AI"),
    (["data engineer", "data analyst", "analytics", "bi ", "etl"], "Data"),
    (["devops", "sre", "platform engineer", "infrastructure", "cloud", "kubernetes", "terraform"], "DevOps/Platform"),
    (["backend", "back-end", "api", "python", "java ", "golang", "node", "ruby", "scala"], "Backend Engineering"),
    (["frontend", "front-end", "react", "vue", "angular", "ui engineer"], "Frontend Engineering"),
    (["full stack", "fullstack"], "Full-Stack Engineering"),
    (["mobile", "ios", "android", "flutter", "react native"], "Mobile Engineering"),
    (["security", "cybersecurity", "appsec", "devsecops"], "Security Engineering"),
    (["product manager", "product owner", "program manager"], "Product"),
    (["qa", "quality assurance", "test engineer", "sdet"], "QA/Testing"),
]


def _infer_team(job_roles: List[str]) -> str:
    """Infer the dominant hiring team from job titles."""
    roles_lower = " ".join(job_roles).lower()
    scores: Dict[str, int] = {}
    for keywords, team in ROLE_TEAM_MAP:
        score = sum(1 for kw in keywords if kw in roles_lower)
        if score:
            scores[team] = scores.get(team, 0) + score
    if not scores:
        return "Engineering"
    return max(scores, key=scores.get)


def _clean_body(text: str) -> str:
    """Strip em-dashes, smart quotes, and other characters that make emails look AI-generated."""
    replacements = {
        "\u2014": "-",   # em dash
        "\u2013": "-",   # en dash
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...", # ellipsis
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.strip()


def _parse_json_response(text: str) -> dict:
    """Robustly strip markdown fences and parse JSON from an LLM response."""
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "").strip()
    return json.loads(text)


class JobAnalyzer:
    """Analyze text/HTML to extract job information using Mistral AI"""

    def __init__(self, mistral_api_key: str):
        if not MISTRAL_AVAILABLE:
            raise ImportError("Mistral package not installed")
        self.mistral = Mistral(api_key=mistral_api_key)

    def analyze_career_page(self, text: str, company_name: str) -> Dict:
        """
        Analyze career page text to extract job information.

        Args:
            text: Page text content
            company_name: Company name for context

        Returns:
            Dict with is_hiring, job_roles, hiring_summary
        """
        try:
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

Rules:
- Only include REAL job titles you find in the content
- If you see "No open positions" or similar, set is_hiring to false
- Be specific (e.g., "Senior Software Engineer" not just "Engineer")
- Include up to 20 job titles maximum
"""

            response = self.mistral.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000
            )

            result_text = response.choices[0].message.content.strip()
            data = _parse_json_response(result_text)

            logger.info(f"✅ Mistral analysis: {len(data.get('job_roles', []))} jobs found")

            return {
                'is_hiring': data.get('is_hiring', False),
                'job_roles': data.get('job_roles', [])[:20],
                'hiring_summary': data.get('hiring_summary', '')[:200]
            }

        except json.JSONDecodeError as e:
            logger.error(f"Mistral returned invalid JSON: {e}")
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
        Clean and categorize a raw list of job titles.

        Args:
            job_titles: List of potential job titles
            company_name: Company name

        Returns:
            Dict with is_hiring, job_roles, hiring_summary
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
2. Remove non-job entries (e.g., "About Us", "FAQ", navigation labels)
3. Standardize formatting (proper title case)
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
            cleaned_jobs = _parse_json_response(result_text)

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

    def generate_outreach_mail(
        self,
        company_name: str,
        job_roles: List[str],
        funding_info: Optional[str] = None,
        sender_email: str = "shilpi.bhatia@gravityer.com",
        max_retries: int = 2
    ) -> Optional[Dict]:
        """
        Generate a personalized outreach email for a hiring company.

        Args:
            company_name: Name of the company
            job_roles: List of job titles they are hiring for
            funding_info: Optional funding information (e.g. "Series B, $20M")
            sender_email: Rayees' actual email address for the CTA
            max_retries: How many times to retry on JSON parse failure

        Returns:
            Dict with subject, body, team_focus — or None on failure
        """
        if not job_roles:
            return None

        team_focus = _infer_team(job_roles)
        roles_sample = ", ".join(job_roles[:6])  # keep prompt concise

        # Build the funding line only when real data exists
        if funding_info:
            funding_line = f"They recently received funding ({funding_info}) and are scaling fast."
        else:
            funding_line = "They are actively scaling their team."

        # Funding congratulations line — only when we have real data
        if funding_info:
            funding_congrats = f"— congratulations on raising {funding_info}. That milestone truly reflects the strength of your vision and execution."
        else:
            funding_congrats = "— I've been really impressed by the strength of your vision and execution."

        prompt = f"""Write a warm B2B cold outreach email from Shilpi Bhatia (Senior BDM, Gravity Engineering Services) to a hiring contact at {company_name}.

Follow this EXACT structure and tone. Fill in the bracketed parts with real values from the context below. Do not change the sentence structure -- only swap in the right details.

--- TEMPLATE ---
Hey [first name if known, else send an generic greeting line of Hey {company_name} team],

I’ve been following {company_name}’s journey for some time now {funding_congrats}

While reviewing your careers page and LinkedIn, I noticed openings across several strategic roles, including {roles_sample}. Given the competitive market, hiring for these roles can be both time-consuming and expensive.

At Gravity Engineering Services (www.gravityer.com), we specialize in delivering the top 3% of pre-vetted global engineering talent through flexible contract engagements. We help high-growth technology companies scale efficiently by providing experienced engineers who integrate seamlessly into existing teams — remotely or onsite — and begin contributing from day one.

If optimizing cost without compromising quality is part of your hiring strategy, I would welcome the opportunity to explore how we can support {company_name}’s expansion plans.

Please feel free to share a suitable time, or I’d be happy to coordinate based on your availability. You can also book a time directly here: https://sales.polluxa.com/ext/meeting/574EEC5864/meeting
--- END TEMPLATE ---

Context:
- Company: {company_name}
- Hiring for ({team_focus}): {roles_sample}
- {funding_line}

Hard rules:
- Keep the tone exactly as shown: warm, human, conversational. Not salesy.
- Do NOT add extra paragraphs, bullet points, or marketing language
- Do NOT use em dashes or smart quotes
- Do NOT fabricate facts beyond what is given
- If no recipient first name is available, start directly with "I’ve been following..."
- Keep word count to about 120-150 words (body only, excluding signature)

Return ONLY valid JSON, no markdown fences:
{{
  "subject": "specific subject line about supporting {company_name}'s expansion plans (max 10 words)",
  "body": "full email body with \\n\\n between paragraphs",
  "team_focus": "{team_focus}"
}}"""

        for attempt in range(max_retries + 1):
            try:
                response = self.mistral.chat.complete(
                    model="mistral-large-latest",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.65,
                    max_tokens=600
                )

                result_text = response.choices[0].message.content.strip()
                data = _parse_json_response(result_text)

                body = _clean_body(data.get('body', ''))
                subject = _clean_body(data.get('subject', ''))

                # Ensure signature is always present and correctly formatted
                cta_banner = (
                    '\n\n<a href="https://sales.polluxa.com/ext/meeting/574EEC5864/meeting" target="_blank">'
                    '<img src="https://ci3.googleusercontent.com/mail-sig/AIorK4zzPing2FyYjR1YFA-fvADgwE2cUWzzqE3RXGzQjp5AKHwa7Prc33GyN-XnlAjsCkWjxa_f7p2rlRNd" '
                    'width="100" height="29" alt="Book a meeting with Gravity Engineering" '
                    'style="display:block;border:none;" /></a>'
                )
                signature = (
                    "\n\nShilpi Bhatia\n"
                    "Senior BDM\n"
                    "Gravity Engineering Services Pvt Ltd.\n"
                    "shilpi.bhatia@gravityer.com"
                )
                # Strip any partial signature the LLM may have appended, then re-add ours
                for marker in ["Shilpi Bhatia", "Senior BDM", "Best,", "Best regards", "Sincerely", "Thanks,", "cheers,"]:
                    # Ensure case-insensitive or specifically matched markers to avoid truncating valid body text
                    if marker in body:
                        # only strip if it's near the end of the text to prevent rare false positives
                        if body.rindex(marker) > len(body) * 0.5:
                            body = body[:body.rindex(marker)].rstrip()
                            break
                            
                body = body + signature + cta_banner 

                if not body or not subject:
                    raise ValueError("Empty subject or body in response")

                logger.info(f"✉️ Outreach mail generated for {company_name} (team: {team_focus})")

                return {
                    'subject': subject,
                    'body': body,
                    'team_focus': team_focus,
                }

            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Attempt {attempt + 1} failed for {company_name}: {e}")
                if attempt == max_retries:
                    logger.error(f"Mail generation failed after {max_retries + 1} attempts for {company_name}")
                    return None

            except Exception as e:
                logger.error(f"Mail generation failed for {company_name}: {e}")
                return None