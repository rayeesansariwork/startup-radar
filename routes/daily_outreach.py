"""
Daily Hiring Outreach — SSE Streaming Endpoint
===============================================
GET /api/v1/daily-hiring-outreach/

Combines company fetch + hiring detection + mail generation into one
streaming endpoint. Returns Server-Sent Events with progress, then a
final JSON summary.

SSE event types:
  - "log"      → progress/debug messages
  - "company"  → per-company result
  - "summary"  → final structured JSON (last event)
"""

import asyncio
import hashlib
import json
import logging
import random
import requests as sync_requests
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from config import settings
from core_utils import execute_with_retry
from hiring_detector.checker import EnhancedHiringChecker
from hiring_detector.analyzer import JobAnalyzer
from services.apollo_service import ApolloService
from services.email_queue import email_queue

logger = logging.getLogger("daily_outreach")
router = APIRouter(prefix="/api/v1", tags=["daily-outreach"])

# Polite-scraping constants — randomised so we look organic
_DELAY_MIN = 5.0   # seconds
_DELAY_MAX = 7.0   # seconds

# ─── Config ──────────────────────────────────────────────────────────────────

CRM_BASE_URL = "https://salesapi.gravityer.com/api/v1"
CRM_CREDENTIALS = {
    "email": "rayees@gravityer.com",
    "password": "Raees@786",
}

FUNDING_KEYWORDS = [
    "raised", "funding", "$", "valuation",
    "million", "billion", "seed", "series",
]

REQUEST_TIMEOUT = 180  # seconds — CRM can be slow on large queries


# ─── SSE helpers ─────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    """Format a single Server-Sent Event line."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ─── Auth ────────────────────────────────────────────────────────────────────

def obtain_token() -> Optional[str]:
    url = f"{CRM_BASE_URL}/token/obtain/"
    logger.info("🔑 Requesting JWT token …")
    try:
        resp = sync_requests.post(url, json=CRM_CREDENTIALS, timeout=15)
        if resp.status_code == 200:
            token = resp.json().get("access")
            logger.info("✅ Token obtained")
            return token
        logger.error("❌ Token failed %s — %s", resp.status_code, resp.text[:200])
    except sync_requests.RequestException as exc:
        logger.error("❌ Token request error: %s", exc)
    return None


# ─── Paginated fetch ────────────────────────────────────────────────────────

def fetch_companies(token: str, target_date: str, page_size: int) -> list[dict]:
    """
    Fetch all companies for *target_date* with source=ENRICHMENT ENGINE.
    Correctly resolves relative `next` URLs against CRM_BASE_URL.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # First page — absolute URL
    url: Optional[str] = (
        f"{CRM_BASE_URL}/companies/"
        f"?created_on_after={target_date}"
        f"&source=ENRICHMENT ENGINE"
        f"&page_size={page_size}"
    )

    all_companies: list[dict] = []
    page = 1

    while url:
        logger.info("📄 Fetching page %d  → %s", page, url[:120])
        try:
            resp = sync_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            # Token refresh on 401
            if resp.status_code == 401:
                logger.warning("🔄 401 — refreshing token …")
                new_token = obtain_token()
                if not new_token:
                    logger.error("❌ Re-auth failed, aborting fetch")
                    break
                headers["Authorization"] = f"Bearer {new_token}"
                resp = sync_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                logger.error("❌ Page %d → %d: %s", page, resp.status_code, resp.text[:200])
                break

            data = resp.json()

            if isinstance(data, list):
                all_companies.extend(data)
                url = None
            elif isinstance(data, dict):
                results = data.get("results", [])
                all_companies.extend(results)

                # ── FIX: resolve relative "next" URL ──
                raw_next = data.get("next")
                if raw_next:
                    if raw_next.startswith("http"):
                        url = raw_next
                    else:
                        # e.g. "/api/v1/companies/?page=2…" → absolute
                        url = urljoin("https://salesapi.gravityer.com", raw_next)
                else:
                    url = None

                logger.info("   ↳ page %d: %d results (total: %d)  next=%s",
                            page, len(results), len(all_companies), "yes" if url else "no")
            else:
                logger.warning("⚠️ Unexpected response type on page %d", page)
                break

            page += 1

        except sync_requests.RequestException as exc:
            logger.error("❌ Request error page %d: %s", page, exc)
            break

    logger.info("📦 Fetched %d companies total", len(all_companies))
    return all_companies


# ─── Mail generation (always runs) ──────────────────────────────────────────

def _has_funding_signal(company: dict) -> bool:
    fields = [
        company.get("annual_revenue", ""),
        company.get("latest_funding_amount", ""),
        company.get("total_funding", ""),
        company.get("last_raised_at", ""),
    ]
    text = " ".join(str(f) for f in fields if f).lower()
    return any(kw in text for kw in FUNDING_KEYWORDS)


def _funding_snippet(company: dict) -> str:
    for field in ("annual_revenue", "latest_funding_amount", "total_funding"):
        val = company.get(field)
        if val and any(kw in str(val).lower() for kw in FUNDING_KEYWORDS):
            return str(val)
    return ""


def _detect_team(company: dict) -> str:
    blob = " ".join(
        str(company.get(f, "")).lower()
        for f in ("industry", "technologies", "seo_description")
    )
    if any(w in blob for w in ("ai", "ml", "machine learning", "data")):
        return "AI / Data Engineering"
    if any(w in blob for w in ("fintech", "finance", "banking", "payment")):
        return "FinTech Engineering"
    if any(w in blob for w in ("health", "biotech", "medical")):
        return "HealthTech Engineering"
    if any(w in blob for w in ("saas", "cloud", "devops", "infra")):
        return "Cloud / Platform Engineering"
    if any(w in blob for w in ("ecommerce", "retail", "marketplace")):
        return "Full-Stack Engineering"
    if any(w in blob for w in ("sales", "marketing", "growth")):
        return "Sales & Growth"
    return "Engineering"


CTA_BANNER = (
    '\n\n<a href="https://sales.polluxa.com/ext/meeting/574EEC5864/meeting" target="_blank">'
    '<img src="https://ci3.googleusercontent.com/mail-sig/AIorK4zzPing2FyYjR1YFA-fvADgwE2cUWzzqE3RXGzQjp5AKHwa7Prc33GyN-XnlAjsCkWjxa_f7p2rlRNd" '
    'width="100" height="29" alt="Book a meeting with Gravity Engineering" '
    'style="display:block;border:none;" /></a>'
)

SIGNATURE = (
    "\n\nShilpi Bhatia\n"
    "Senior BDM\n"
    "Gravity Engineering Services Pvt Ltd.\n"
    "shilpibhatiya@gravityer.com"
)

FULL_SIGNATURE = SIGNATURE + CTA_BANNER


# ─── C-suite contact simulation ─────────────────────────────────────────────

# Realistic first-name pools per role — seeded deterministically from domain
_CSUITE_ROLES = [
    {"title": "CEO",            "first_names": ["James", "Sarah", "Carlos", "Priya", "Michael", "Ana"]},
    {"title": "CTO",            "first_names": ["Alex", "Elena", "David", "Wei", "Thomas", "Anika"]},
    {"title": "VP Engineering",  "first_names": ["Jordan", "Mia", "Rahul", "Sophie", "Daniel", "Fatima"]},
    {"title": "COO",            "first_names": ["Olivia", "Ravi", "Lisa", "Erik", "Mei", "Andrei"]},
    {"title": "VP Sales",       "first_names": ["Samuel", "Yuki", "Hannah", "Omar", "Natasha", "Leo"]},
]

_LAST_NAMES = [
    "Patel", "Garcia", "Chen", "Muller", "Kim", "Johansson",
    "Singh", "Perez", "Nakamura", "Williams", "Bernard", "Costa",
]


def find_csuite_contacts(domain: str, count: int = 3) -> list[dict]:
    """
    Simulate finding C-suite contacts for a domain.
    Deterministic (same domain → same contacts) using a hash-based seed.
    Returns list of {"name", "title", "email"} dicts.

    NOTE: This is a placeholder for a real enrichment API (Apollo, RocketReach, etc.).
    """
    # Seed from domain for deterministic output
    seed = int(hashlib.md5(domain.encode()).hexdigest(), 16)
    rng = random.Random(seed)

    # Pick N unique roles
    roles = rng.sample(_CSUITE_ROLES, min(count, len(_CSUITE_ROLES)))
    contacts = []

    for role in roles:
        first = rng.choice(role["first_names"])
        last = rng.choice(_LAST_NAMES)

        # Common email patterns
        pattern = rng.choice([
            f"{first.lower()}@{domain}",
            f"{first.lower()}.{last.lower()}@{domain}",
            f"{first[0].lower()}{last.lower()}@{domain}",
        ])

        contacts.append({
            "name": f"{first} {last}",
            "title": role["title"],
            "email": pattern,
        })

    return contacts


# ─── Mail generation ────────────────────────────────────────────────────────

def generate_mail(
    company: dict,
    is_hiring: bool = False,
    job_count: int = 0,
    job_roles: list[str] | None = None,
) -> dict:
    """
    Generate an outreach email snippet following exactly the same structure
    and tone as the AI generated ones in analyzer.py.
    """
    name = company.get("company_name", "there")
    funded = _has_funding_signal(company)
    snippet = _funding_snippet(company) if funded else ""
    team = _detect_team(company)
    roles = job_roles or []

    # Funding congratulations line
    if funded and snippet:
        funding_congrats = f"Congrats on the {snippet}. I am really happy to see your growth."
    elif funded:
        funding_congrats = "Congrats on the recent funding. I am really happy to see your growth."
    else:
        funding_congrats = "You guys are doing great work and the growth is clearly showing."

    opening_greeting = f"Hey {name} team,"
    opening_sentence = f"I have been following {name} for a while now. {funding_congrats}"

    # ── Tailored email (hiring = True) ──────────────────────────────────
    if is_hiring and roles:
        if len(roles) <= 3:
            role_list = " and ".join([", ".join(roles[:-1]), roles[-1]] if len(roles) > 1 else roles)
        else:
            role_list = ", ".join(roles[:3]) + " and more"
            
        subject = f"{name} - {team} roles"
        body_para1 = f"{opening_sentence} I was checking your careers page and LinkedIn and I saw that you are hiring {role_list}. You already know how high the market rates are for these roles."

    # ── Hiring but no role details ──────────────────────────────────────
    elif is_hiring:
        subject = f"{name} - {team} roles"
        body_para1 = f"{opening_sentence} I was checking your careers page and LinkedIn and I saw that you are actively hiring for your {team} team. You already know how high the market rates are for these roles."

    # ── Generic nurture email (not hiring) ──────────────────────────────
    else:
        subject = f"{name} - Growth & Engineering team"
        body_para1 = f"{opening_sentence} As you continue to scale your {team} team, you already know how high the market rates are for these roles across regions."

    body_para2 = "We can provide the same level of talent at a much lower cost. We place pre-vetted engineers into your team full time, remote or onsite, based on what works best for you. They plug into your workflow and start contributing fast."

    body_para3 = "If this helps your hiring plans, I would love to support your growth. We can provide the right resources based on your needs and budget. If you want to discuss this, please book a slot here: https://sales.polluxa.com/ext/meeting/574EEC5864/meeting"
    
    body = f"{opening_greeting}\n\n{body_para1}\n\n{body_para2}\n\n{body_para3}{FULL_SIGNATURE}"

    return {"subject": subject, "body": body, "team_focus": team}


def generate_personalized_mail(
    company: dict, contact: dict, base_mail: dict
) -> dict:
    """
    Re-address a generated email to a specific C-suite contact.
    Returns {"to", "to_name", "to_title", "subject", "body"}.
    """
    first_name = contact["name"].split()[0]
    company_name = company.get("company_name", "there")

    # Replace generic "Hey <Company> team" with "Hey <FirstName>"
    body = base_mail["body"].replace(
        f"Hey {company_name} team",
        f"Hey {first_name}",
    )

    return {
        "to": contact["email"],
        "to_name": contact["name"],
        "to_title": contact["title"],
        "subject": base_mail["subject"],
        "body": body,
    }


# ─── SSE stream generator ───────────────────────────────────────────────────

async def _stream(target_date: str, page_size: int) -> AsyncGenerator[str, None]:
    """Core generator — yields SSE events."""

    loop = asyncio.get_event_loop()

    yield _sse("log", {"message": f"▶ Daily outreach for {target_date}"})

    # 1) Token
    token = await loop.run_in_executor(None, obtain_token)
    if not token:
        yield _sse("log", {"message": "❌ Auth failed — aborting"})
        yield _sse("summary", {"error": "Authentication failed"})
        return

    yield _sse("log", {"message": "✅ Authenticated"})

    # 2) Fetch companies
    yield _sse("log", {"message": f"📅 Fetching companies (date={target_date}, page_size={page_size}) …"})
    companies = await loop.run_in_executor(None, fetch_companies, token, target_date, page_size)
    yield _sse("log", {"message": f"📦 {len(companies)} companies fetched"})

    if not companies:
        yield _sse("summary", {
            "date": target_date,
            "companies_fetched": 0,
            "hiring_calls_made": 0,
            "hiring_detected": 0,
            "mails_generated": 0,
            "errors": 0,
            "processed_companies": [],
        })
        return

    # 3) Hiring checker + AI email writer
    hiring_checker = EnhancedHiringChecker(mistral_api_key=settings.mistral_api_key)
    job_analyzer = JobAnalyzer(mistral_api_key=settings.mistral_api_key)
    apollo_service = ApolloService(api_key=settings.apollo_api_key)
    
    yield _sse("log", {"message": "🤖 Mistral AI ready (will generate tailored emails for hiring companies)"})
    yield _sse("log", {"message": "🔍 Apollo Service initialized for real contact discovery"})

    processed: list[dict] = []
    hiring_calls = 0
    hiring_detected = 0
    mails_generated = 0
    errors = 0

    for idx, company in enumerate(companies, 1):
        name = company.get("company_name", "Unknown")
        website = company.get("website", "")
        yield _sse("log", {"message": f"[{idx}/{len(companies)}] Processing {name} …"})

        # ── Hiring check ──
        result_entry: dict = {
            "company_name": name,
            "website": website,
            "is_hiring": False,
            "job_count": 0,
            "job_roles": [],
            "custom_mail": None,
            "found_contacts": [],
            "personalized_email": None,
            "error": None,
        }

        try:
            hiring_result = await execute_with_retry(
                lambda name=name, website=website: loop.run_in_executor(
                    None, hiring_checker.check_hiring, name, website
                ),
                max_retries=3,
                backoff_factor=2.0,
            )
            hiring_calls += 1

            is_hiring = hiring_result.get("is_hiring", False)
            job_roles = hiring_result.get("job_roles", [])
            result_entry["is_hiring"] = is_hiring
            result_entry["job_count"] = hiring_result.get("job_count", len(job_roles))
            result_entry["job_roles"] = job_roles

            if is_hiring:
                hiring_detected += 1

        except Exception as exc:
            hiring_calls += 1
            errors += 1
            result_entry["error"] = str(exc)
            logger.error("Hiring check failed for %s: %s", name, exc)

        # ── Generate mail ──
        #   • Hiring companies → Mistral AI (tailored, role-aware)
        #   • Non-hiring       → fast template
        try:
            if result_entry["is_hiring"] and result_entry["job_roles"]:
                # Build funding context string for the AI
                funding_info = _funding_snippet(company) or None
                yield _sse("log", {
                    "message": f"   🤖 Generating AI-tailored email for {name} "
                               f"({result_entry['job_count']} roles) …"
                })
                ai_mail = await loop.run_in_executor(
                    None,
                    job_analyzer.generate_outreach_mail,
                    name,
                    result_entry["job_roles"],
                    funding_info,
                )
                if ai_mail and ai_mail.get("body"):
                    # Append signature if AI didn't include one
                    if "gravityer.com" not in ai_mail["body"]:
                        ai_mail["body"] += SIGNATURE
                    result_entry["custom_mail"] = ai_mail
                    result_entry["mail_source"] = "mistral_ai"
                    mails_generated += 1
                    yield _sse("log", {
                        "message": f"   ✅ AI email generated (focus: {ai_mail.get('team_focus', 'N/A')})"
                    })
                else:
                    # AI returned nothing — fall back to template
                    logger.warning("AI mail empty for %s, falling back to template", name)
                    mail = generate_mail(
                        company,
                        is_hiring=True,
                        job_count=result_entry["job_count"],
                        job_roles=result_entry["job_roles"],
                    )
                    result_entry["custom_mail"] = mail
                    result_entry["mail_source"] = "template_fallback"
                    mails_generated += 1
            else:
                # Non-hiring → template (no need to burn AI tokens)
                mail = generate_mail(
                    company,
                    is_hiring=result_entry["is_hiring"],
                    job_count=result_entry["job_count"],
                    job_roles=result_entry["job_roles"],
                )
                result_entry["custom_mail"] = mail
                result_entry["mail_source"] = "template"
                mails_generated += 1
        except Exception as exc:
            logger.error("Mail gen failed for %s: %s", name, exc)
            # Last-resort template fallback
            try:
                result_entry["custom_mail"] = generate_mail(
                    company,
                    is_hiring=result_entry["is_hiring"],
                    job_count=result_entry["job_count"],
                    job_roles=result_entry["job_roles"],
                )
                result_entry["mail_source"] = "template_fallback"
                mails_generated += 1
            except Exception:
                result_entry["custom_mail"] = None
                result_entry["mail_source"] = "failed"

        # ── Find C-suite contacts (Apollo API) ──
        domain = (website or "").replace("https://", "").replace("http://", "").strip("/")
        if domain:
            yield _sse("log", {"message": f"   📇 Searching Apollo for contacts at {domain}..."})
            contacts = await loop.run_in_executor(None, apollo_service.find_csuite_contacts, domain, 3)
            result_entry["found_contacts"] = contacts
            
            if contacts:
                yield _sse("log", {
                    "message": f"   ✅ Found {len(contacts)} leads: "
                               + ", ".join(f'{c["name"]} ({c["title"]}) - {c["email"]}' for c in contacts)
                })

                # ── Immediately sync contacts to CRM to prevent data loss ──
                try:
                    sync_payload = {
                        "company_name": name,
                        "website": website,
                        "contacts": contacts
                    }
                    sync_resp = await loop.run_in_executor(
                        None,
                        lambda p=sync_payload: sync_requests.post(
                            f"{CRM_BASE_URL}/hiring-outreach-results/sync_contacts/",
                            json=p,
                            timeout=10
                        )
                    )
                    if sync_resp.status_code == 200:
                        yield _sse("log", {"message": "   💾 Contacts independently secured in CRM Company & Contact models."})
                    else:
                        logger.error(f"CRM sync returned {sync_resp.status_code}: {sync_resp.text}")
                except Exception as e:
                    logger.error(f"Instant CRM sync failed for {name}: {e}")

                # Personalize mail to the first (highest-priority) contact
                if result_entry["custom_mail"]:
                    personalized = generate_personalized_mail(
                        company, contacts[0], result_entry["custom_mail"]
                    )
                    result_entry["personalized_email"] = personalized
                    yield _sse("log", {
                        "message": f"   ✉️  Personalized email prepared for {personalized['to']} ({personalized['to_title']})"
                    })
            else:
                yield _sse("log", {"message": f"   ⚠️ No contacts found by Apollo for {domain}."})

        processed.append(result_entry)
        yield _sse("company", result_entry)

        # ── Polite delay before next company ────────────────────────────────
        if idx < len(companies):  # skip sleep after the last company
            delay = random.uniform(_DELAY_MIN, _DELAY_MAX)
            logger.debug("⏳ Politeness delay: %.1f s before next company …", delay)
            yield _sse("log", {"message": f"   ⏸ Waiting {delay:.1f}s before next request …"})
            await asyncio.sleep(delay)

    # 4) Final summary
    summary = {
        "date": target_date,
        "companies_fetched": len(companies),
        "hiring_calls_made": hiring_calls,
        "hiring_detected": hiring_detected,
        "mails_generated": mails_generated,
        "errors": errors,
        "processed_companies": processed,
    }

    yield _sse("log", {
        "message": (
            f"✅ Done — {len(companies)} fetched, {hiring_detected} hiring, "
            f"{mails_generated} mails, {errors} errors"
        )
    })
    yield _sse("summary", summary)

    # ── Persist results to SalesTechBE ──────────────────────────────────
    try:
        yield _sse("log", {"message": "💾 Saving results to database …"})
        persist_resp = sync_requests.post(
            f"{CRM_BASE_URL}/hiring-outreach-results/bulk_create/",
            json={"results": processed, "run_date": target_date},
            timeout=REQUEST_TIMEOUT,
        )
        if persist_resp.status_code == 201:
            data = persist_resp.json()
            saved = data.get("created", 0)
            returned_results = data.get("results", [])
            yield _sse("log", {"message": f"✅ {saved} results saved to database"})
            
            # ── Enqueue emails now that we have SalesTechBE IDs ──
            queued_count = 0
            for r in returned_results:
                personalized = r.get("personalized_email")
                if personalized and r.get("id"):
                    payload = {
                        "result_id": r["id"],
                        "to": personalized["to"],
                        "to_name": personalized["to_name"],
                        "subject": personalized["subject"],
                        "body": personalized["body"],
                        "already_emailed": r.get("email_sent", False) # The requested boolean 
                    }
                    
                    # Only enqueue if it hasn't somehow already been marked as sent
                    if not payload["already_emailed"]:
                        try:
                            # Try native async enqueue (works on the HTTP SSE path)
                            cur_loop = asyncio.get_event_loop()
                            if email_queue._main_loop and cur_loop is not email_queue._main_loop:
                                # We are on the cron thread's separate loop — use threadsafe bridge
                                email_queue.enqueue_threadsafe(payload)
                            else:
                                await email_queue.enqueue_email(payload)
                        except RuntimeError:
                            # No running loop — use threadsafe bridge
                            email_queue.enqueue_threadsafe(payload)
                        queued_count += 1
            
            if queued_count > 0:
                yield _sse("log", {"message": f"⏳ Queued {queued_count} emails for staggered dispatch with DB tracking."})
        else:
            yield _sse("log", {
                "message": f"⚠️ DB save returned {persist_resp.status_code}: {persist_resp.text[:200]}"
            })
    except Exception as exc:
        logger.error("Failed to persist outreach results: %s", exc)
        yield _sse("log", {"message": f"⚠️ Could not save results: {exc}"})
        
    # ── Send Email Notification ─────────────────────────────────────────
    try:
        from services import NotificationService
        
        yield _sse("log", {"message": "📧 Sending summary email notification via SalesTechBE …"})
        
        default_recipients = [
            "mounica@gravityer.com",
            "abhinaw@gravityer.com",
            "pr@gravityer.com",
            "raeessg22@gmail.com",
            "arindam@gravityer.com",
        ]
        recipients = list(default_recipients)
        if settings.notification_recipient and settings.notification_recipient not in recipients:
            recipients.append(settings.notification_recipient)
            
        notification_service = NotificationService(
            recipients=recipients
        )
        
        # Format the data for the existing NotificationService template
        # Reusing the existing discovery format since we just need the same visual email
        notification_data = {
            "companies": processed,
            "sources_used": ["ENRICHMENT ENGINE + MISTRAL AI"],
            "duration": 0.0, # Not tracked per session here
            "error": None
        }
        email_sent = notification_service.send_discovery_notification(notification_data, discovery_type="Daily Outreach")
        
        if email_sent:
            yield _sse("log", {"message": f"✅ Email notification sent successfully to {len(recipients)} recipients"})
        else:
            yield _sse("log", {"message": "⚠️ Email notification failed (check backend logs)"})
    except Exception as e:
        logger.error(f"Failed to send outreach email notification: {e}", exc_info=True)
        yield _sse("log", {"message": f"⚠️ Could not send email notification: {e}"})



# ─── Endpoint ───────────────────────────────────────────────────────────────

@router.get("/daily-hiring-outreach/")
async def daily_hiring_outreach(
    date: Optional[str] = Query(
        None,
        description="Override target date (YYYY-MM-DD). Defaults to yesterday.",
    ),
    page_size: int = Query(100, ge=1, le=500, description="Page size for company fetch"),
):
    """
    Stream daily hiring outreach via SSE.

    Events:
      - **log**      — progress messages
      - **company**  — per-company hiring + mail result
      - **summary**  — final JSON with all stats + processed list
    """
    if date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        # Validate
        try:
            datetime.strptime(date, "%Y-%m-%d")
            target_date = date
        except ValueError:
            return StreamingResponse(
                iter([_sse("summary", {"error": f"Invalid date format: {date}. Use YYYY-MM-DD."})]),
                media_type="text/event-stream",
            )

    logger.info("🚀 /daily-hiring-outreach/ called  date=%s  page_size=%d", target_date, page_size)

    return StreamingResponse(
        _stream(target_date, page_size),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx: don't buffer SSE
        },
    )
