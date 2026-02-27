"""
Daily Hiring Outreach Script
=============================
Runs daily to:
  1. Authenticate with the CRM (JWT)
  2. Fetch companies created YESTERDAY (source=ENRICHMENT ENGINE)
  3. Send each company to the hiring API for analysis
  4. Always generate a custom outreach email (funding-signal-aware)
  5. Print summary stats

Usage:
    python daily_outreach.py

Schedule via cron / Task Scheduler for daily execution.
"""

import requests
import json
import sys
from datetime import datetime, timedelta

# ─── Configuration ───────────────────────────────────────────────────────────

CRM_BASE_URL = "https://salesapi.gravityer.com/api/v1"
HIRING_API_URL = "https://startup-radar-1.onrender.com/api/hiring"

CRM_CREDENTIALS = {
    "email": "sankalp@admin.com",
    "password": "0h%Bx}jB*SO}"
}

# Funding signal keywords — trigger a stronger outreach email
FUNDING_KEYWORDS = ["raised", "funding", "$", "valuation", "million", "billion", "seed", "series"]

# Gravity signature
GRAVITY_SIGNATURE = "\n\nBest regards,\nGravity Team\ninfo@gravityer.com"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Timestamped log line."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def has_funding_signal(company: dict) -> bool:
    """Check if the company's annual_revenue or funding fields contain funding keywords."""
    fields_to_check = [
        company.get("annual_revenue", ""),
        company.get("latest_funding_amount", ""),
        company.get("total_funding", ""),
        company.get("last_raised_at", ""),
    ]
    text = " ".join(str(f) for f in fields_to_check if f).lower()
    return any(kw in text for kw in FUNDING_KEYWORDS)


def get_funding_snippet(company: dict) -> str:
    """Extract a human-readable funding snippet for the email opening."""
    for field in ["annual_revenue", "latest_funding_amount", "total_funding"]:
        val = company.get(field)
        if val and any(kw in str(val).lower() for kw in FUNDING_KEYWORDS):
            return str(val)
    return ""


def detect_team_focus(company: dict) -> str:
    """Heuristic guess at the main team a company would need."""
    industry = str(company.get("industry", "")).lower()
    techs = str(company.get("technologies", "")).lower()
    description = str(company.get("seo_description", "")).lower()
    combined = f"{industry} {techs} {description}"

    if any(w in combined for w in ["ai", "ml", "machine learning", "data"]):
        return "AI / Data Engineering"
    if any(w in combined for w in ["fintech", "finance", "banking", "payment"]):
        return "FinTech Engineering"
    if any(w in combined for w in ["health", "biotech", "medical"]):
        return "HealthTech Engineering"
    if any(w in combined for w in ["saas", "cloud", "devops", "infra"]):
        return "Cloud / Platform Engineering"
    if any(w in combined for w in ["ecommerce", "retail", "marketplace"]):
        return "Full-Stack Engineering"
    if any(w in combined for w in ["sales", "marketing", "growth"]):
        return "Sales & Growth"
    return "Engineering"


def generate_custom_mail(company: dict) -> dict:
    """
    Generate an outreach email for a company.
    Always generates — does NOT depend on is_hiring.
    Uses funding signals when available for a stronger opening.
    """
    name = company.get("company_name", "there")
    funding = has_funding_signal(company)
    snippet = get_funding_snippet(company) if funding else ""
    team = detect_team_focus(company)

    if funding and snippet:
        subject = f"Congrats on the recent raise, {name}! Let's help you scale {team}"
        opening = (
            f"Hi {name} team,\n\n"
            f"Congrats on your recent funding ({snippet}) — exciting times! "
            f"As you ramp up hiring for {team}, we'd love to help you move faster."
        )
    elif funding:
        subject = f"Exciting growth ahead, {name} — let's talk {team} staffing"
        opening = (
            f"Hi {name} team,\n\n"
            f"We noticed your recent funding round — congrats! "
            f"Growing your {team} team quickly and cost-effectively is what we do best."
        )
    else:
        subject = f"Scaling your {team} team, {name}?"
        opening = (
            f"Hi {name} team,\n\n"
            f"We help ambitious companies like yours build world-class {team} teams "
            f"through cost-effective staff augmentation."
        )

    body = (
        f"{opening}\n\n"
        f"Gravity provides pre-vetted, full-time remote engineers who integrate directly "
        f"with your team — at a fraction of local hiring costs. Whether you need 1 engineer "
        f"or 10, we can move in days, not months.\n\n"
        f"Would love to have a quick chat to see if there's a fit. "
        f"Just reply here or reach out at info@gravityer.com."
        f"{GRAVITY_SIGNATURE}"
    )

    return {
        "subject": subject,
        "body": body,
        "team_focus": team,
    }


# ─── Core Functions ──────────────────────────────────────────────────────────

def obtain_token() -> str | None:
    """Obtain a fresh JWT access token from the CRM."""
    url = f"{CRM_BASE_URL}/token/obtain/"
    log("🔑 Obtaining JWT access token...")

    try:
        resp = requests.post(url, json=CRM_CREDENTIALS, timeout=10)
        if resp.status_code == 200:
            token = resp.json().get("access")
            log("✅ Token obtained successfully.")
            return token
        else:
            log(f"❌ Token request failed: {resp.status_code} — {resp.text[:200]}")
            return None
    except requests.RequestException as e:
        log(f"❌ Token request error: {e}")
        return None


def fetch_yesterday_companies(token: str) -> list[dict]:
    """
    Fetch all companies created yesterday from CRM.
    Handles pagination via the 'next' field.
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    log(f"📅 Fetching companies created on {yesterday} (source=ENRICHMENT ENGINE)...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url = (
        f"{CRM_BASE_URL}/companies/"
        f"?created_on_after={yesterday}&source=ENRICHMENT ENGINE&page_size=5"
    )

    all_companies: list[dict] = []
    page = 1

    while url:
        try:
            resp = requests.get(url, headers=headers, timeout=180)

            if resp.status_code == 401:
                log("🔄 Token expired during fetch — re-authenticating...")
                new_token = obtain_token()
                if not new_token:
                    log("❌ Re-authentication failed. Aborting fetch.")
                    break
                headers["Authorization"] = f"Bearer {new_token}"
                resp = requests.get(url, headers=headers, timeout=180)

            if resp.status_code != 200:
                log(f"❌ Fetch failed (page {page}): {resp.status_code} — {resp.text[:200]}")
                break

            data = resp.json()

            # Support both paginated ({"results": [...], "next": ...}) and flat list responses
            if isinstance(data, list):
                all_companies.extend(data)
                url = None  # No pagination for flat list
            elif isinstance(data, dict):
                results = data.get("results", [])
                all_companies.extend(results)
                url = data.get("next")  # None when no more pages
                log(f"   Page {page}: {len(results)} companies (total so far: {len(all_companies)})")
            else:
                log(f"⚠️ Unexpected response format on page {page}")
                break

            page += 1

        except requests.RequestException as e:
            log(f"❌ Request error on page {page}: {e}")
            break

    log(f"📦 Total companies fetched: {len(all_companies)}")
    return all_companies


def send_to_hiring_api(company: dict) -> dict | None:
    """
    Send a single company to the hiring endpoint for analysis.
    POST https://startup-radar-1.onrender.com/api/hiring
    """
    payload = {
        "companies": [company]
    }

    try:
        resp = requests.post(HIRING_API_URL, json=payload, timeout=60)

        if resp.status_code == 200:
            return resp.json()
        else:
            log(f"   ⚠️ Hiring API returned {resp.status_code} for {company.get('company_name', '?')}")
            return None
    except requests.RequestException as e:
        log(f"   ❌ Hiring API error for {company.get('company_name', '?')}: {e}")
        return None


# ─── Main Runner ─────────────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("🚀 DAILY HIRING OUTREACH — Starting")
    log("=" * 60)

    # Step 1 — Authenticate
    token = obtain_token()
    if not token:
        log("🛑 Cannot proceed without a valid token. Exiting.")
        sys.exit(1)

    # Step 2 — Fetch yesterday's companies
    companies = fetch_yesterday_companies(token)

    if not companies:
        log("ℹ️  No companies found for yesterday. Nothing to process.")
        log("=" * 60)
        log("✅ DONE — 0 companies, 0 hiring calls, 0 emails.")
        return

    # Step 3 & 4 — Process each company
    hiring_calls = 0
    hiring_true_count = 0
    mail_generated_count = 0
    errors = 0

    for idx, company in enumerate(companies, start=1):
        company_name = company.get("company_name", "Unknown")
        log(f"\n--- [{idx}/{len(companies)}] {company_name} ---")

        # 3a) Send to hiring API
        hiring_result = send_to_hiring_api(company)
        hiring_calls += 1

        is_hiring = False
        if hiring_result and hiring_result.get("success"):
            results = hiring_result.get("results", [])
            if results:
                is_hiring = results[0].get("is_hiring", False)
                if is_hiring:
                    hiring_true_count += 1
                    log(f"   ✅ is_hiring = True ({results[0].get('job_count', 0)} jobs)")
                else:
                    log(f"   ℹ️  is_hiring = False")
        elif hiring_result is None:
            errors += 1

        # 4) Always generate custom_mail
        mail = generate_custom_mail(company)
        mail_generated_count += 1

        funding_flag = "🔥 FUNDING" if has_funding_signal(company) else ""
        log(f"   ✉️  Mail generated | Subject: {mail['subject'][:60]}... | Focus: {mail['team_focus']} {funding_flag}")

    # Step 5 — Summary
    log("\n" + "=" * 60)
    log("📊 DAILY OUTREACH SUMMARY")
    log("=" * 60)
    log(f"   Companies fetched:      {len(companies)}")
    log(f"   Hiring API calls made:  {hiring_calls}")
    log(f"   is_hiring = True:       {hiring_true_count}")
    log(f"   custom_mail generated:  {mail_generated_count}")
    log(f"   Errors / failures:      {errors}")
    log("=" * 60)
    log("✅ DONE")


if __name__ == "__main__":
    main()
