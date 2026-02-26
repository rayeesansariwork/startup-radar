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

CRM_BASE_URL = settings.crm_base_url.rstrip("/")
CRM_CREDENTIALS = {
    "email": settings.crm_email,
    "password": settings.crm_password,
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
    '\n\n<img src="https://ci3.googleusercontent.com/mail-sig/AIorK4zzPing2FyYjR1YFA-fvADgwE2cUWzzqE3RXGzQjp5AKHwa7Prc33GyN-XnlAjsCkWjxa_f7p2rlRNd" '
    'width="100" height="29" alt="Gravity Engineering" '
    'style="display:block;border:none;" />'
)

SIGNATURE = (
    "\n\nBest,\n"
    "Shilpi Bhatia"
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
    Generate an outreach email following the same structure as the AI-generated
    emails but using a deterministic template (no Mistral call needed).
    """
    name = company.get("company_name", "there")
    funded = _has_funding_signal(company)
    snippet = _funding_snippet(company) if funded else ""
    team = _detect_team(company)
    roles = job_roles or []

    # Role label for subject + body
    primary_role = roles[0] if roles else team

    # Subject: Scaling {Company} | {role summary}
    subject = f"Scaling {name} | {primary_role}"

    # Funding congratulations line
    if funded and snippet:
        funding_line = f"Saw the news on {snippet} - an incredible milestone for {name}."
    elif funded:
        funding_line = f"Saw the news on the recent funding - an incredible milestone for {name}."
    else:
        funding_line = ""

    # Roles paragraph
    if is_hiring and roles:
        if len(roles) <= 3:
            role_list = ", ".join(roles)
        else:
            role_list = ", ".join(roles[:3]) + " and more"
        roles_sentence = f"Noticed {name} is hiring for roles like {role_list}."
    elif is_hiring:
        roles_sentence = f"Noticed you are actively scaling your {team} team."
    else:
        roles_sentence = f"As you continue to grow, I wanted to share how we help companies like {name} build great {team} teams."

    body_parts = []

    if funding_line:
        body_parts.append(funding_line)

    body_parts.append(
        f"{roles_sentence} As you scale, I'd love to share how Gravity helped companies like <b>New Balance</b>, <b>Landmark Group</b> etc. to build thier elite teams."
    )

    body_parts.append(
        f"We deliver pre-vetted, <b>top 3%</b> global {primary_role}s who integrate seamlessly from day one. "
        "If optimizing costs without compromising technical leadership is a priority, do you have <b>10 mins</b> next week?"
    )

    body = "\n\n".join(body_parts) + FULL_SIGNATURE

    return {"subject": subject, "body": body, "team_focus": team}


def generate_personalized_mail(
    company: dict, contact: dict, all_contacts: list[dict], base_mail: dict
) -> dict:
    """
    Re-address a generated email to a specific C-suite contact and cross-reference others.
    Returns {"to", "to_name", "to_title", "subject", "body"}.
    """
    first_name = contact["name"].split()[0]
    company_name = company.get("company_name", "there")

    # Pick a secondary contact to mention
    secondary_contact = None
    priority_titles = ["CTO", "VP Engineering", "COO", "CEO", "VP Sales"]
    
    other_contacts = [c for c in all_contacts if c["email"] != contact["email"]]
    
    if other_contacts:
        # Sort by priority to try and mention the most relevant technical peer if possible
        def get_priority(c):
            try:
                return priority_titles.index(c.get("title", ""))
            except ValueError:
                return 999
        
        other_contacts.sort(key=get_priority)
        secondary_contact = other_contacts[0]

    greeting = f"Hi {first_name},\n\n"
    
    if secondary_contact:
        sec_name = secondary_contact["name"].split()[0]
        sec_title = secondary_contact["title"]
        cross_ref = f"I'm also reaching out to {sec_name}, your {sec_title}, but wanted to drop you a quick note as well.\n\n"
        greeting += cross_ref

    # Clean up any residual placeholders Mistral might have theoretically left behind
    body = base_mail["body"].replace(
        "Hi [recipient first name, or just omit the greeting line if unknown],\n\n", ""
    ).replace(
        f"Hey {company_name} team,\n\n", ""
    ).strip()
    
    body = f"{greeting}{body}"

    return {
        "to": contact["email"],
        "to_name": contact["name"],
        "to_title": contact["title"],
        "subject": base_mail["subject"],
        "body": body,
    }


def fetch_processed_companies(token: str) -> set[str]:
    """
    Fetch the list of company names that already have Apollo contacts saved.
    Returns a set for fast lookup to prevent wasting Mistral/Apollo credits.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{CRM_BASE_URL}/hiring-outreach-results/processed_companies/"
    
    try:
        resp = sync_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return set(resp.json())
        else:
            logger.warning("⚠️ Failed to fetch processed companies: %d %s", resp.status_code, resp.text[:100])
    except Exception as e:
        logger.error("❌ Error fetching processed companies: %s", e)
    
    return set()


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

    # 4) Fetch deduplication list
    processed_companies_set = await loop.run_in_executor(None, fetch_processed_companies, token)
    if processed_companies_set:
        yield _sse("log", {"message": f"🛡️  Deduplication: Found {len(processed_companies_set)} previously processed companies with contacts."})

    processed: list[dict] = []
    hiring_calls = 0
    hiring_detected = 0
    mails_generated = 0
    errors = 0

    for idx, company in enumerate(companies, 1):
        name = company.get("company_name", "Unknown")
        website = company.get("website", "")
        
        # ── Deduplication Check ──
        if name in processed_companies_set:
            yield _sse("log", {"message": f"[{idx}/{len(companies)}] ⏭️ Skipping {name} — C-suite contacts already processed."})
            continue
            
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
                    # NOTE: analyzer.py already strips any LLM-written signature and
                    # re-adds "Best, Shilpi Bhatia" + CTA banner — do NOT append SIGNATURE here.
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
            contacts = await loop.run_in_executor(None, apollo_service.find_csuite_contacts, domain, name, 3)
            result_entry["found_contacts"] = contacts
            
            if contacts:
                yield _sse("log", {
                    "message": f"   ✅ Found {len(contacts)} leads: "
                               + ", ".join(f'{c["name"]} ({c["title"]}) - {c["email"]}' for c in contacts)
                })

                # ── Immediately sync contacts to CRM to prevent data loss ──
                try:
                    sync_headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    } if token else {}
                    
                    sync_resp = await loop.run_in_executor(
                        None,
                        lambda: sync_requests.post(
                            f"{CRM_BASE_URL}/hiring-outreach-results/sync_contacts/",
                            json={
                                "company_name": name,
                                "website": website,
                                "contacts": contacts
                            },
                            headers=sync_headers,
                            timeout=15
                        )
                    )
                    if sync_resp.status_code == 200:
                        yield _sse("log", {"message": f"   ✅ Apollo contacts saved to CRM for {name}"})
                    else:
                        yield _sse("log", {"message": f"   ⚠️ CRM sync returned {sync_resp.status_code}: {sync_resp.text[:200]}"})
                except Exception as e:
                    logger.error("Error syncing Apollo contacts to SalesTechBE for %s: %s", name, e)

                # Personalize mail to all found contacts
                if result_entry["custom_mail"]:
                    personalized_list = []
                    for contact in contacts:
                        personalized = generate_personalized_mail(
                            company, contact, contacts, result_entry["custom_mail"]
                        )
                        personalized_list.append(personalized)
                        yield _sse("log", {
                            "message": f"   ✉️  Personalized email prepared for {personalized['to']} ({personalized['to_title']})"
                        })
                    result_entry["personalized_email"] = personalized_list
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
        persist_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        } if token else {}
        
        persist_resp = sync_requests.post(
            f"{CRM_BASE_URL}/hiring-outreach-results/bulk_create/",
            json={"results": processed, "run_date": target_date},
            headers=persist_headers,
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
                personalized_data = r.get("personalized_email")
                if personalized_data and r.get("id"):
                    # Handle both new (list) and old (dict) structures
                    emails_to_send = personalized_data if isinstance(personalized_data, list) else [personalized_data]
                    already_emailed = r.get("email_sent", False) # The requested boolean 
                    
                    # Only enqueue if it hasn't somehow already been marked as sent
                    if not already_emailed:
                        for personalized in emails_to_send:
                            payload = {
                                "result_id": r["id"],
                                "to": personalized["to"],
                                "to_name": personalized["to_name"],
                                "subject": personalized["subject"],
                                "body": personalized["body"],
                                "already_emailed": False 
                            }
                            
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
