"""
Talent API external jobs sync helpers.

This module is intentionally isolated so daily outreach logic can stay unchanged
when the feature is disabled.
"""

import hashlib
import html
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests

from services.talent_taxonomy import ROLE_CATALOG, SKILL_CATALOG, TalentTaxonomyMatcher
from utils.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

_OBJECT_ID_RE = re.compile(r"^[a-f0-9]{24}$", re.IGNORECASE)
_ALLOWED_LEVELS = {
    "lead": "Lead",
    "senior": "Senior",
    "mid-level": "Mid-Level",
    "junior": "Junior",
    "entry-level": "Entry-Level",
    "executive": "Executive",
    "research associate": "Research Associate",
}

# Keep to the known accepted values on Talent API side.
_ALLOWED_JOB_TYPES = {"remote", "hybrid", "onsite"}
_JOB_TYPE_ALIASES = {
    "remote": "remote",
    "work from home": "remote",
    "wfh": "remote",
    "hybrid": "hybrid",
    "on-site": "onsite",
    "onsite": "onsite",
    "on site": "onsite",
    "office": "onsite",
    "in office": "onsite",
}

# Based on Talent API enum validation errors observed in runtime logs.
_ALLOWED_DEPARTMENTS = {
    "Business", "Design", "Engineering", "General",
    "Operations", "Product", "Research", "Support",
}
_ROLE_CATEGORIES = {"Designer", "Developer", "HR", "Manager", "Marketing", "Partnership", "Sales"}

_UNSUPPORTED_TITLE_KEYWORDS = (
    "restaurant",
    "dishwasher",
    "prep cook",
    "line cook",
    "food service",
    "kitchen",
    "chef",
    "barista",
    "waiter",
    "waitress",
    "hostess",
)
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_RETRYABLE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_DISALLOWED_SCRIPT_RE = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff]"
)

try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False


def build_job_fingerprint(company_name: str, payload: Dict) -> str:
    """Create a stable fingerprint for run-level deduplication."""
    parts = [
        (company_name or "").strip().lower(),
        str(payload.get("title", "")).strip().lower(),
        str(payload.get("country", "")).strip().lower(),
        str(payload.get("state", "")).strip().lower(),
        str(payload.get("city", "")).strip().lower(),
        str(payload.get("tenure", "")).strip().lower(),
    ]
    return "|".join(parts)


class TalentAPIClient:
    """Client for posting external jobs to Talent API."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        timeout_seconds: int = 20,
        max_requests_per_window: int = 10,
        request_window_seconds: int = 300,
        request_max_retries: int = 3,
        request_backoff_seconds: float = 1.5,
        debug: bool = False,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.email = email or ""
        self.password = password or ""
        self.timeout_seconds = timeout_seconds
        self.max_requests_per_window = max(1, int(max_requests_per_window))
        self.request_window_seconds = max(1, int(request_window_seconds))
        self.request_max_retries = max(1, int(request_max_retries))
        self.request_backoff_seconds = max(0.25, float(request_backoff_seconds))
        self._token: Optional[str] = None
        self._role_cache: Dict[str, str] = {}
        self._skill_cache: set[str] = set()
        self._roles_index_ready = False
        self._skills_index_ready = False
        self._request_timestamps: List[float] = []
        self.debug = bool(debug)
        self._seed_local_role_cache()
        self._seed_local_skill_cache()

    def _log_debug(self, message: str, *args) -> None:
        if self.debug:
            logger.info("[TalentDebug] " + message, *args)

    @staticmethod
    def _redact_email(email: str) -> str:
        raw = str(email or "").strip()
        if "@" not in raw:
            return "***"
        user, domain = raw.split("@", 1)
        if not user:
            return f"***@{domain}"
        if len(user) == 1:
            return f"{user}***@{domain}"
        return f"{user[0]}***{user[-1]}@{domain}"

    @staticmethod
    def _redact_sensitive_text(text: str) -> str:
        redacted = str(text or "")
        redacted = re.sub(
            r'("?(?:token|access|jwt|refreshToken|refresh_token|password)"?\s*:\s*")([^"]+)(")',
            r"\1***REDACTED***\3",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            r"(Bearer\s+)[A-Za-z0-9\-_\.=]+",
            r"\1***REDACTED***",
            redacted,
            flags=re.IGNORECASE,
        )
        return redacted

    def _debug_json_snippet(self, payload: Optional[Dict], limit: int = 600) -> str:
        try:
            serialized = json.dumps(payload or {}, ensure_ascii=False)
        except Exception:
            serialized = str(payload or {})
        return self._redact_sensitive_text(serialized)[:limit]

    def _response_snippet(self, response: requests.Response, limit: int = 700) -> str:
        return self._redact_sensitive_text((response.text or "")[:limit])

    def _retry_delay_seconds(
        self,
        *,
        attempt: int,
        response: Optional[requests.Response] = None,
    ) -> float:
        retry_after_seconds: Optional[float] = None
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    retry_after_seconds = max(0.0, float(retry_after))
                except Exception:
                    retry_after_seconds = None
        if retry_after_seconds is not None:
            return min(retry_after_seconds + 0.2, 120.0)
        exp_backoff = self.request_backoff_seconds * (2 ** max(0, attempt - 1))
        return min(exp_backoff + 0.2, 30.0)

    @staticmethod
    def _normalize_location_text(value) -> str:
        if value is None:
            return ""
        normalized = str(value).strip()
        if not normalized:
            return ""
        if normalized.lower() in {"n/a", "na", "none", "null", "-"}:
            return ""
        return normalized

    @staticmethod
    def _normalize_country_text(value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parts = re.split(r"\s+", raw.lower())
        return " ".join(p.capitalize() for p in parts if p)

    @staticmethod
    def _build_ascii_slug(text: str, *, seed: str = "") -> str:
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
        if slug:
            return slug[:120]
        digest_source = (seed or text or "external-job").encode("utf-8", errors="ignore")
        digest = hashlib.sha1(digest_source).hexdigest()[:12]
        return f"job-{digest}"

    def _prepare_external_job_payload(self, payload: Dict) -> Dict:
        prepared = dict(payload or {})

        title = str(prepared.get("title") or "").strip()
        if title:
            prepared["title"] = title

        # Keep API payload type-compatible for optional fields.
        prepared["state"] = self._normalize_location_text(prepared.get("state"))
        prepared["city"] = self._normalize_location_text(prepared.get("city"))
        prepared["country"] = self._normalize_country_text(prepared.get("country")) or "India"

        slug_input = str(prepared.get("slug") or "").strip()
        slug_seed = f"{prepared.get('title') or ''}|{prepared.get('roleName') or prepared.get('role') or ''}|{prepared.get('department') or ''}"
        prepared["slug"] = self._build_ascii_slug(slug_input or title, seed=slug_seed)

        return prepared

    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.password)

    def ensure_authenticated(self) -> bool:
        if self._token:
            return True
        return self._login()

    def _login(self) -> bool:
        if not self.is_configured():
            logger.warning("Talent API client is missing configuration")
            return False

        url = f"{self.base_url}/api/auth/login/"
        payload = {"email": self.email, "password": self.password}

        try:
            self._log_debug("Login request: %s (email=%s)", url, self._redact_email(self.email))
            self._respect_request_window()
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
            self._log_debug(
                "Login response: status=%s body=%s",
                response.status_code,
                self._response_snippet(response, limit=500),
            )
            if response.status_code != 200:
                logger.error(
                    "Talent API login failed: %s %s",
                    response.status_code,
                    self._response_snippet(response, limit=200),
                )
                return False

            data = response.json()
            token = (
                data.get("token")
                or data.get("access")
                or data.get("jwt")
                or (data.get("data") or {}).get("token")
            )
            if not token:
                logger.error("Talent API login response missing token")
                return False

            self._token = token
            logger.info("Talent API authentication successful")
            return True
        except Exception as exc:
            logger.error("Talent API login error: %s", exc)
            return False

    def _respect_request_window(self) -> None:
        """
        Keep total Talent API calls under provider rolling-window limits.
        Observed limit: 10 requests per 5 minutes.
        """
        now = time.monotonic()
        cutoff = now - float(self.request_window_seconds)
        self._request_timestamps = [ts for ts in self._request_timestamps if ts >= cutoff]

        if len(self._request_timestamps) >= self.max_requests_per_window:
            oldest = self._request_timestamps[0]
            wait_seconds = max(0.0, float(self.request_window_seconds) - (now - oldest) + 0.5)
            if wait_seconds > 0:
                logger.info(
                    "Talent API global throttle: waiting %.1fs to stay within %d/%ds limit",
                    wait_seconds,
                    self.max_requests_per_window,
                    self.request_window_seconds,
                )
                time.sleep(wait_seconds)
            now = time.monotonic()
            cutoff = now - float(self.request_window_seconds)
            self._request_timestamps = [ts for ts in self._request_timestamps if ts >= cutoff]

        self._request_timestamps.append(time.monotonic())

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _skill_key(name: str) -> str:
        return " ".join(str(name or "").strip().lower().split())

    @staticmethod
    def _role_key(name: str) -> str:
        raw = str(name or "").strip().lower()
        raw = raw.replace("_", " ").replace("-", " ").replace("/", " ")
        raw = re.sub(r"[^a-z0-9\s]+", " ", raw)
        return " ".join(raw.split())

    @staticmethod
    def _format_role_name(name: str) -> str:
        """
        Normalize slug/snake_case role hints into human-readable role names.
        Example: customer_support_agent -> Customer Support Agent
        """
        raw = str(name or "").strip()
        if not raw:
            return ""

        if "_" in raw:
            raw = raw.replace("_", " ")
        if "-" in raw and " " not in raw and "/" not in raw:
            raw = raw.replace("-", " ")
        raw = re.sub(r"\s+", " ", raw).strip()

        acronym_map = {
            "ai": "AI",
            "ml": "ML",
            "qa": "QA",
            "ui": "UI",
            "ux": "UX",
            "hr": "HR",
            "sde": "SDE",
            "sre": "SRE",
            "cto": "CTO",
            "ceo": "CEO",
            "coo": "COO",
            "cfo": "CFO",
            "vp": "VP",
            "av": "A/V",
            "a/v": "A/V",
            "devops": "DevOps",
        }
        lower_words = {"and", "or", "of", "for", "to", "in", "on", "with", "the", "a", "an"}

        tokens = raw.split(" ")
        formatted_tokens: List[str] = []
        for token in tokens:
            low = token.lower()
            if low in acronym_map:
                formatted_tokens.append(acronym_map[low])
            elif low in lower_words and formatted_tokens:
                formatted_tokens.append(low)
            elif token.isupper() and len(token) <= 4:
                formatted_tokens.append(token)
            elif token.islower() or token.isupper():
                formatted_tokens.append(token.capitalize())
            else:
                formatted_tokens.append(token)

        return " ".join(formatted_tokens)

    def _seed_local_role_cache(self) -> None:
        for item in ROLE_CATALOG:
            name = str(item.get("name") or "").strip()
            role_id = str(item.get("_id") or item.get("id") or "").strip()
            if name and role_id:
                self._role_cache[self._role_key(name)] = role_id

    def _seed_local_skill_cache(self) -> None:
        """
        Seed cache from local static skill catalog so known skills never trigger
        create API calls.
        """
        for item in SKILL_CATALOG:
            name = str(item.get("name") or "").strip()
            if name:
                self._skill_cache.add(self._skill_key(name))

    @staticmethod
    def _extract_id(data: Dict) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        direct = data.get("_id") or data.get("id")
        if direct:
            return str(direct)
        nested = data.get("data")
        if isinstance(nested, dict):
            nested_id = nested.get("_id") or nested.get("id")
            if nested_id:
                return str(nested_id)
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: Optional[Dict] = None,
        max_attempts: Optional[int] = None,
    ):
        if not self.ensure_authenticated():
            return None
        method_upper = str(method or "GET").upper()
        attempts = max(1, int(max_attempts or self.request_max_retries))
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            try:
                self._log_debug(
                    "Request: %s %s payload=%s",
                    method_upper,
                    path,
                    self._debug_json_snippet(json_payload),
                )
                self._respect_request_window()
                response = requests.request(
                    method=method_upper,
                    url=url,
                    json=json_payload,
                    headers=self._headers(),
                    timeout=self.timeout_seconds,
                )

                if response.status_code == 401:
                    self._token = None
                    if self._login():
                        self._respect_request_window()
                        response = requests.request(
                            method=method_upper,
                            url=url,
                            json=json_payload,
                            headers=self._headers(),
                            timeout=self.timeout_seconds,
                        )

                self._log_debug(
                    "Response: %s %s status=%s body=%s",
                    method_upper,
                    path,
                    response.status_code,
                    self._response_snippet(response, limit=500),
                )

                if (
                    response.status_code in _TRANSIENT_STATUS_CODES
                    and method_upper in _RETRYABLE_METHODS
                    and attempt < attempts
                ):
                    delay = self._retry_delay_seconds(attempt=attempt, response=response)
                    logger.warning(
                        "Talent API transient response (%s %s status=%s). Retrying in %.1fs (attempt %d/%d)",
                        method_upper,
                        path,
                        response.status_code,
                        delay,
                        attempt,
                        attempts,
                    )
                    time.sleep(delay)
                    continue

                return response

            except requests.RequestException as exc:
                last_exc = exc
                if method_upper in _RETRYABLE_METHODS and attempt < attempts:
                    delay = self._retry_delay_seconds(attempt=attempt)
                    logger.warning(
                        "Talent API request exception (%s %s): %s. Retrying in %.1fs (attempt %d/%d)",
                        method_upper,
                        path,
                        exc,
                        delay,
                        attempt,
                        attempts,
                    )
                    time.sleep(delay)
                    continue
                logger.error("Talent API request error (%s %s): %s", method_upper, path, exc)
                return None
            except Exception as exc:
                logger.error("Talent API request error (%s %s): %s", method_upper, path, exc)
                return None

        if last_exc:
            logger.error("Talent API request exhausted retries (%s %s): %s", method_upper, path, last_exc)
        return None

    @staticmethod
    def _extract_records(payload) -> List[Dict]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("results", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            data = payload.get("data")
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
            if isinstance(data, dict):
                for key in ("results", "items"):
                    value = data.get(key)
                    if isinstance(value, list):
                        return [x for x in value if isinstance(x, dict)]
        return []

    def _load_existing_skills_once(self, force: bool = False) -> None:
        if self._skills_index_ready and not force:
            return
        paths = ["/api/skills/?page_size=1000", "/api/skills?page_size=1000", "/api/skills/"]
        for path in paths:
            response = self._request("GET", path)
            if response is None or response.status_code != 200:
                continue
            try:
                payload = response.json() if response.text else {}
            except Exception:
                continue
            records = self._extract_records(payload)
            if not records and isinstance(payload, list):
                records = payload
            for item in records:
                name = str(item.get("name") or "").strip()
                if name:
                    self._skill_cache.add(self._skill_key(name))
            self._skills_index_ready = True
            return

        # Mark as ready even on failure to avoid repeated expensive probes;
        # future forced refreshes can still override this.
        self._skills_index_ready = True

    def _search_skill_exists(self, skill_name: str) -> bool:
        query = quote_plus(skill_name)
        paths = [
            f"/api/skills/?search={query}",
            f"/api/skills?search={query}",
            f"/api/skills/?name={query}",
        ]
        for path in paths:
            response = self._request("GET", path)
            if response is None or response.status_code != 200:
                continue
            try:
                payload = response.json() if response.text else {}
            except Exception:
                continue
            records = self._extract_records(payload)
            target = self._skill_key(skill_name)
            for item in records:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                key = self._skill_key(name)
                self._skill_cache.add(key)
                if key == target:
                    return True
        return False

    def _load_existing_roles_once(self, force: bool = False) -> None:
        if self._roles_index_ready and not force:
            return
        paths = ["/api/jobroles?page_size=1000", "/api/jobroles/?page_size=1000", "/api/jobroles"]
        for path in paths:
            response = self._request("GET", path)
            if response is None or response.status_code != 200:
                continue
            try:
                payload = response.json() if response.text else {}
            except Exception:
                continue
            records = self._extract_records(payload)
            if not records and isinstance(payload, list):
                records = payload
            for item in records:
                name = str(item.get("name") or "").strip()
                role_id = str(item.get("_id") or item.get("id") or "").strip()
                if name and role_id:
                    self._role_cache[self._role_key(name)] = role_id
            self._roles_index_ready = True
            return
        self._roles_index_ready = True

    def _search_role_id_by_name(self, role_name: str) -> Optional[str]:
        query = quote_plus(role_name)
        paths = [
            f"/api/jobroles?search={query}",
            f"/api/jobroles/?search={query}",
            f"/api/jobroles?name={query}",
        ]
        target = self._role_key(role_name)
        for path in paths:
            response = self._request("GET", path)
            if response is None or response.status_code != 200:
                continue
            try:
                payload = response.json() if response.text else {}
            except Exception:
                continue
            records = self._extract_records(payload)
            if not records and isinstance(payload, list):
                records = payload
            for item in records:
                name = str(item.get("name") or "").strip()
                role_id = str(item.get("_id") or item.get("id") or "").strip()
                if not name or not role_id:
                    continue
                key = self._role_key(name)
                self._role_cache[key] = role_id
                if key == target:
                    return role_id
        return None

    @staticmethod
    def _infer_role_category(role_name: str, department: Optional[str]) -> str:
        source = f"{role_name or ''} {department or ''}".lower()
        if any(k in source for k in ("design", "ui", "ux", "graphic")):
            return "Designer"
        if any(k in source for k in ("hr", "recruit", "talent")):
            return "HR"
        if any(k in source for k in ("sales", "account executive", "bdr", "business development", "sdr")):
            return "Sales"
        if any(k in source for k in ("marketing", "seo", "content", "growth")):
            return "Marketing"
        if any(k in source for k in ("partnership", "alliances")):
            return "Partnership"
        if any(k in source for k in ("manager", "director", "head", "lead")):
            return "Manager"
        return "Developer"

    def create_job_role(self, role_name: str, department: Optional[str] = None) -> Optional[str]:
        original_name = str(role_name or "").strip()
        name = self._format_role_name(original_name)
        if not name:
            return None
        key = self._role_key(name)
        if key in self._role_cache:
            self._log_debug("Role cache hit: '%s' -> %s", name, self._role_cache[key])
            return self._role_cache[key]
        self._load_existing_roles_once()
        if key in self._role_cache:
            self._log_debug("Role resolved from remote list: '%s' -> %s", name, self._role_cache[key])
            return self._role_cache[key]

        category = self._infer_role_category(name, department)
        if category not in _ROLE_CATEGORIES:
            category = "Developer"

        response = self._request(
            "POST",
            "/api/jobroles",
            json_payload={"name": name, "category": category},
        )
        if response is None:
            return None

        # Created / already-existing behavior differs by backend; try to parse id from body.
        try:
            data = response.json() if response.text else {}
        except Exception:
            data = {}
        role_id = self._extract_id(data)
        if role_id:
            self._role_cache[key] = role_id
            if original_name:
                self._role_cache[self._role_key(original_name)] = role_id
            logger.info("Created/resolved Talent role '%s' -> %s", name, role_id)
            return role_id

        body = (response.text or "").lower()
        if response.status_code in (400, 409) and ("exist" in body or "duplicate" in body):
            self._load_existing_roles_once(force=True)
            if key in self._role_cache:
                return self._role_cache[key]
            found = self._search_role_id_by_name(name) or self._search_role_id_by_name(original_name)
            if found:
                self._role_cache[key] = found
                return found

        if response.status_code == 500 and "failed to create data" in body:
            self._load_existing_roles_once(force=True)
            if key in self._role_cache:
                return self._role_cache[key]
            found = self._search_role_id_by_name(name) or self._search_role_id_by_name(original_name)
            if found:
                self._role_cache[key] = found
                return found

        logger.warning(
            "Unable to create/resolve role '%s' (status=%s, body=%s)",
            name,
            response.status_code,
            (response.text or "")[:200],
        )
        return None

    def create_skill(self, skill_name: str) -> bool:
        name = str(skill_name or "").strip()
        if not name:
            return False
        key = self._skill_key(name)
        if key in self._skill_cache:
            self._log_debug("Skill cache hit: '%s'", name)
            return True
        self._load_existing_skills_once()
        if key in self._skill_cache:
            self._log_debug("Skill resolved from remote list: '%s'", name)
            return True

        response = self._request(
            "POST",
            "/api/skills/",
            json_payload={"name": name, "description": name},
        )
        if response is None:
            return False

        # Treat any 2xx as success; for conflicts/duplicates we still mark as seen to avoid retry spam.
        if 200 <= response.status_code < 300:
            self._skill_cache.add(key)
            self._log_debug("Skill created: '%s'", name)
            return True

        body = (response.text or "").lower()
        if response.status_code in (400, 409) and ("exist" in body or "duplicate" in body):
            self._skill_cache.add(key)
            self._log_debug("Skill already exists per API response: '%s'", name)
            return True

        # Some backend paths return 500 on duplicate/conflict. Re-check before failing.
        if response.status_code == 500 and "failed to create data" in body:
            self._load_existing_skills_once(force=True)
            if key in self._skill_cache or self._search_skill_exists(name):
                self._skill_cache.add(key)
                self._log_debug("Skill inferred existing after 500 fallback: '%s'", name)
                return True

        logger.warning(
            "Unable to create skill '%s' (status=%s, body=%s)",
            name,
            response.status_code,
            (response.text or "")[:200],
        )
        return False

    def ensure_payload_taxonomy(self, payload: Dict) -> Dict:
        result = self.ensure_payload_taxonomy_with_audit(payload)
        return result.get("payload", dict(payload or {}))

    def ensure_payload_taxonomy_with_audit(self, payload: Dict) -> Dict:
        """
        Pass-through taxonomy step.

        Role and skill creation via API is intentionally removed.  We now rely on
        the backend to create the role from ``roleName`` + ``categoryName`` fields
        and accept ``skills`` as a plain array of strings — no pre-creation needed.
        """
        updated = dict(payload or {})
        audit = {
            "role_resolved": None,
            "skills_resolved": [],
        }
        self._log_debug(
            "Taxonomy input payload summary: title=%s roleName=%s skills=%s country=%s state=%s city=%s",
            updated.get("title"),
            updated.get("roleName"),
            updated.get("skills"),
            updated.get("country"),
            updated.get("state"),
            updated.get("city"),
        )

        # Skills: clean list only — no API calls, no catalog lookup.
        skills = updated.get("skills")
        if isinstance(skills, list):
            updated["skills"] = [str(s).strip() for s in skills if str(s).strip()]

        self._log_debug("Taxonomy audit result: %s", json.dumps(audit, ensure_ascii=False))

        return {
            "payload": updated,
            "audit": audit,
        }

    def post_external_job(self, payload: Dict) -> Dict:
        """
        Post one external job payload.

        Returns:
            {
              "success": bool,
              "status_code": int,
              "data": dict|None,
              "error": str|None
            }
        """
        if not self.ensure_authenticated():
            return {
                "success": False,
                "status_code": 0,
                "data": None,
                "error": "Talent API authentication failed",
            }

        post_payload = self._prepare_external_job_payload(payload)
        self._log_debug(
            "Posting external job payload: %s",
            json.dumps(
                {
                    "title": post_payload.get("title"),
                    "slug": post_payload.get("slug"),
                    "roleName": post_payload.get("roleName"),
                    "categoryName": post_payload.get("categoryName"),
                    "department": post_payload.get("department"),
                    "level": post_payload.get("level"),
                    "country": post_payload.get("country"),
                    "state": post_payload.get("state"),
                    "city": post_payload.get("city"),
                    "jobType": post_payload.get("jobType"),
                    "tenure": post_payload.get("tenure"),
                    "skills": post_payload.get("skills"),
                },
                ensure_ascii=False,
            ),
        )

        try:
            response = self._request(
                "POST",
                "/api/jobs/external/",
                json_payload=post_payload,
                max_attempts=self.request_max_retries,
            )
            if response is None:
                return {
                    "success": False,
                    "status_code": 0,
                    "data": None,
                    "error": "Talent API request failed after retries",
                    "is_duplicate_title": False,
                }

            self._log_debug(
                "Post external response: status=%s body=%s",
                response.status_code,
                self._response_snippet(response, limit=1000),
            )

            # Recover from non-ASCII title slug issues by forcing deterministic ASCII slug.
            body_lower = (response.text or "").lower()
            if response.status_code == 400 and "slug" in body_lower and "required" in body_lower:
                forced_slug = self._build_ascii_slug(
                    str(post_payload.get("title") or "external-job"),
                    seed=f"{post_payload.get('title') or ''}|{time.time_ns()}",
                )
                post_payload["slug"] = forced_slug
                self._log_debug("Retrying post with forced slug fallback: %s", forced_slug)
                retry_response = self._request(
                    "POST",
                    "/api/jobs/external/",
                    json_payload=post_payload,
                    max_attempts=self.request_max_retries,
                )
                if retry_response is not None:
                    response = retry_response
                    body_lower = (response.text or "").lower()
                    self._log_debug(
                        "Post external response after slug-retry: status=%s body=%s",
                        response.status_code,
                        self._response_snippet(response, limit=1000),
                    )

            if response.status_code in (200, 201):
                data = response.json() if response.text else {}
                created_id = (
                    data.get("_id")
                    or data.get("id")
                    or (data.get("data") or {}).get("_id")
                    or (data.get("data") or {}).get("id")
                )
                self._log_debug(
                    "Post external parsed success: created_id=%s slug=%s",
                    created_id,
                    data.get("slug") or (data.get("data") or {}).get("slug"),
                )
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "data": data,
                    "error": None,
                    "is_duplicate_title": False,
                }

            error_text = response.text[:400]
            is_duplicate_title = (
                response.status_code in (400, 409)
                and "job title must be unique" in body_lower
            )
            return {
                "success": False,
                "status_code": response.status_code,
                "data": None,
                "error": error_text,
                "is_duplicate_title": is_duplicate_title,
            }

        except Exception as exc:
            return {
                "success": False,
                "status_code": 0,
                "data": None,
                "error": str(exc),
                "is_duplicate_title": False,
            }


class ExternalJobPayloadBuilder:
    """Build and validate external-job payloads from detected hiring roles."""

    def __init__(self, mistral_api_key: Optional[str], default_role_id: Optional[str] = None):
        self.default_role_id = (default_role_id or "").strip() or None
        self.mistral = None
        self.taxonomy = TalentTaxonomyMatcher()
        self._rate_limited_until = 0.0
        if mistral_api_key and MISTRAL_AVAILABLE:
            try:
                self.mistral = Mistral(api_key=mistral_api_key)
            except Exception as exc:
                logger.warning("Mistral init failed for external job payloads: %s", exc)

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "429" in msg or "rate limit" in msg or "rate_limited" in msg

    def _chat_complete_with_retry(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        max_attempts: int = 2,
        initial_backoff_seconds: float = 12.0,
    ):
        if not self.mistral:
            raise RuntimeError("Mistral client not initialized")

        now = time.time()
        if now < self._rate_limited_until:
            remaining = int(self._rate_limited_until - now)
            raise RuntimeError(
                f"Mistral payload generation cooldown active ({remaining}s remaining)"
            )

        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                rate_limiter.acquire()
                return self.mistral.chat.complete(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_error = exc
                if self._is_rate_limit_error(exc) and attempt < max_attempts:
                    sleep_s = min(initial_backoff_seconds * (2 ** (attempt - 1)), 120.0)
                    logger.warning(
                        "Payload LLM hit 429/rate limit (attempt %d/%d). Backing off %.1fs",
                        attempt,
                        max_attempts,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                if self._is_rate_limit_error(exc):
                    # Avoid hammering the endpoint repeatedly in the same run.
                    self._rate_limited_until = time.time() + 300
                    logger.warning("Payload LLM entering 300s cooldown after repeated 429")
                raise
        if last_error:
            raise last_error
        raise RuntimeError("Unknown payload LLM failure")

    def build_payloads(
        self,
        company_name: str,
        website: str,
        career_page_url: Optional[str],
        job_roles: List[str],
        max_jobs: int = 5,
    ) -> List[Dict]:
        role_list = [r.strip() for r in (job_roles or []) if r and str(r).strip()]
        if not role_list:
            return []

        role_list = role_list[:max_jobs]
        llm_items = self._build_with_llm(company_name, website, career_page_url, role_list)

        payloads: List[Dict] = []
        seen_titles = set()

        # Keep LLM output first
        for item in llm_items:
            payload = self._sanitize_payload(
                item,
                company_name=company_name,
                website=website,
                career_page_url=career_page_url,
            )
            if not payload:
                continue
            title_key = payload["title"].strip().lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            payloads.append(payload)

        # Fill any missing roles deterministically
        for role in role_list:
            role_key = role.strip().lower()
            if role_key in seen_titles:
                continue
            fallback = self._fallback_payload(
                role,
                company_name=company_name,
                website=website,
                career_page_url=career_page_url,
            )
            payload = self._sanitize_payload(
                fallback,
                company_name=company_name,
                website=website,
                career_page_url=career_page_url,
            )
            if not payload:
                continue
            payloads.append(payload)
            seen_titles.add(payload["title"].strip().lower())

        return payloads[:max_jobs]

    def _build_with_llm(
        self,
        company_name: str,
        website: str,
        career_page_url: Optional[str],
        job_roles: List[str],
    ) -> List[Dict]:
        if not self.mistral:
            return []

        prompt = f"""You are converting detected job role strings from a company's career page into structured JSON payloads for a job board API.

Company: {company_name}
Website: {website}
Career Page: {career_page_url or "N/A"}
Detected Roles: {json.dumps(job_roles)}

## OUTPUT FORMAT
Return ONLY a valid JSON array (no markdown, no explanation). One object per role:
[
  {{
    "title": "Senior Backend Engineer",
    "roleName": "Backend Engineer",
    "categoryName": "Engineering",
    "experience": 5,
    "vacancy": 1,
    "status": "open",
    "tenure": "full-time",
    "jobType": ["remote"],
    "country": "India",
    "state": null,
    "city": null,
    "department": "Engineering",
    "level": "Senior",
    "maxBudget": null,
    "startDate": "2026-04-01T00:00:00.000Z",
    "endDate": null,
    "skills": ["Python", "Node.js"],
    "description": "<p><strong>Role Overview:</strong> ...</p>",
    "shortDescription": "Short one-line generic summary of the role.",
    "source": "external"
  }}
]

## STRICT QUALITY RULES — READ CAREFULLY

### Title Formatting
- Title must be a clean, professional job title in Title Case. Example: "Senior Backend Engineer", NOT "senior backend engineer", NOT "SENIOR BACKEND ENGINEER", NOT "backend-engineer".
- Keep the seniority prefix if present (e.g., Senior, Lead, Junior, Principal). De-slug any slugged or snake_case input: "senior_backend_engineer" → "Senior Backend Engineer".
- Remove trailing punctuation, trailing numbers, and internal parentheses noise.
- Do NOT include department/team info in the title (e.g., NOT "Backend Engineer - Engineering Team").
- Expand well-known abbreviations: "SWE" → "Software Engineer", "SDE" → "Software Development Engineer", "QA" → "QA Engineer".

### Garbage / Skip Rules — OMIT any detected role that matches these:
- Non-English titles (Chinese, Korean, Japanese, Arabic, Cyrillic, etc.).
- Physical / non-tech / non-professional roles: cook, dishwasher, driver, janitor, security guard, barista, waiter, cleaner, packer, labourer, factory worker, delivery, retail associate.
- Vague or nonsensical strings: single characters, numbers only, internal codes (e.g., "REQ-1234"), URLs, email addresses.
- Roles with no real job-title meaning after de-slugging.
- Duplicate roles that are essentially the same as an already-included item (keep only the best-worded version).
- Internships at a company that only detects one role AND that role is "intern" (skip to avoid noise).

### Field Rules
- `roleName`: The core role name without seniority prefix. Example: title="Senior Backend Engineer" → roleName="Backend Engineer".
- `categoryName`: Must be one of: Engineering, Design, Product, Sales, Marketing, Operations, HR, Finance, Research, Support, General.
- `department`: Must be one of: Engineering, Design, Product, Sales, Marketing, Operations, Research, Support, Business, General.
- `level`: Must be one of: Junior, Mid-Level, Senior, Lead, Principal, Executive, Research Associate. Infer from title or context.
- `experience`: Integer years, minimum 0. Infer from seniority: Junior=0-2, Mid-Level=2-4, Senior=4-8, Lead/Principal=6+.
- `tenure`: Must be one of: full-time, part-time, contract, internship.
- `jobType`: Array, values from: remote, hybrid, onsite. Default to ["remote"] if unknown.
- `skills`: Array of 3–6 relevant, specific technology/skill strings. Must match the role (e.g., a DevOps role gets ["Docker", "Kubernetes", "Terraform"] not ["React", "Figma"]).
- `maxBudget`: Use null if unknown. Do NOT guess a number for senior roles.
- `startDate`: ISO 8601 UTC. Use a reasonable near-future date (within 60 days from today: 2026-03-06T00:00:00.000Z).
- `endDate`: Use null.
- `source`: Always "external".

### Description Rules
- Length: 150–250 words.
- Format: HTML with `<p><strong>heading</strong></p>` and `<ul><li>...</li></ul>` lists.
- Sections to include: Role Overview, Key Responsibilities (4–6 bullets), Requirements (3–5 bullets).
- Do NOT mention the company name, website, or any brand.
- Do NOT copy-paste boilerplate such as "We are an equal opportunity employer" or generic HR filler.
- Keep it focused, realistic, and specific to the role's actual skills.

### shortDescription Rules
- 20–40 words. One sentence. Generic, no company name.
- Example: "We're looking for a Senior Backend Engineer to design scalable microservices, optimize APIs, and lead cloud deployment initiatives."

### Final Checklist before outputting
- Every title is correctly Title Cased and de-slugged.
- No garbage or non-tech roles in the output.
- No duplicate titles.
- skills array is role-specific (not generic).
- Valid JSON only — no trailing commas, no markdown fences.
"""
        try:
            response = self._chat_complete_with_retry(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.05,
                max_tokens=1800,
                max_attempts=3,
                initial_backoff_seconds=12.0,
            )
            raw = response.choices[0].message.content.strip()
            data = self._parse_json(raw)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
            if isinstance(data, dict):
                jobs = data.get("jobs")
                if isinstance(jobs, list):
                    return [d for d in jobs if isinstance(d, dict)]
        except Exception as exc:
            logger.warning("LLM payload build failed: %s", exc)
        return []

    @staticmethod
    def _parse_json(raw: str):
        cleaned = raw.strip()
        cleaned = re.sub(r"^```json\s*", "", cleaned)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

        # 1) Fast path: valid JSON as-is.
        try:
            return json.loads(cleaned)
        except Exception as first_exc:
            candidates: List[str] = []

            # 2) Try extracting top-level JSON array/object from wrapped text.
            arr_start = cleaned.find("[")
            arr_end = cleaned.rfind("]")
            if arr_start != -1 and arr_end > arr_start:
                candidates.append(cleaned[arr_start : arr_end + 1])

            obj_start = cleaned.find("{")
            obj_end = cleaned.rfind("}")
            if obj_start != -1 and obj_end > obj_start:
                candidates.append(cleaned[obj_start : obj_end + 1])

            # Avoid duplicate parsing attempts.
            seen = set()
            unique_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    unique_candidates.append(c)

            for candidate in unique_candidates:
                # 3) Candidate direct parse.
                try:
                    return json.loads(candidate)
                except Exception:
                    pass

                # 4) Light repair for common LLM formatting issues.
                repaired = candidate
                repaired = repaired.replace("\u201c", '"').replace("\u201d", '"')
                repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")
                repaired = re.sub(r",\s*([}\]])", r"\1", repaired)  # trailing commas
                repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", repaired)

                try:
                    return json.loads(repaired)
                except Exception:
                    # 5) Last-chance recovery: parse individual JSON objects from a broken array.
                    objects: List[Dict] = []
                    for obj_text in ExternalJobPayloadBuilder._extract_json_objects(repaired):
                        try:
                            parsed = json.loads(obj_text)
                            if isinstance(parsed, dict):
                                objects.append(parsed)
                        except Exception:
                            continue
                    if objects:
                        return objects
                    continue

            raise first_exc

    @staticmethod
    def _extract_json_objects(text: str) -> List[str]:
        """
        Extract top-level JSON object snippets from mixed/broken text.
        Useful when an LLM returns a mostly-valid array with one malformed item.
        """
        chunks: List[str] = []
        depth = 0
        start = -1
        in_string = False
        escape = False

        for idx, ch in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        chunks.append(text[start : idx + 1])
                        start = -1

        return chunks

    def _fallback_payload(
        self,
        role_title: str,
        company_name: str,
        website: str,
        career_page_url: Optional[str],
    ) -> Dict:
        now = datetime.now(timezone.utc)
        start = self._to_iso_utc(now)
        end = self._to_iso_utc(now + timedelta(days=90))
        clean_title = (role_title or "Software Engineer").strip()
        return {
            "title": clean_title,
            "experience": 4,
            "vacancy": 1,
            "status": "open",
            "tenure": "full-time",
            "jobType": ["remote"],
            "country": "India",
            "state": None,
            "city": None,
            "department": self._infer_department(clean_title),
            "roleName": TalentAPIClient._format_role_name(clean_title),
            "categoryName": self._infer_department(clean_title),
            "level": self._infer_level(clean_title),
            "maxBudget": 1500000,
            "startDate": start,
            "endDate": end,
            "skills": self._infer_skills(clean_title),
            "description": self._build_generic_description(
                title=clean_title,
                department=self._infer_department(clean_title),
                level=self._infer_level(clean_title),
                skills=self._infer_skills(clean_title),
            ),
            "shortDescription": self._build_generic_short_description(
                title=clean_title,
                department=self._infer_department(clean_title),
                skills=self._infer_skills(clean_title),
            ),
            "source": "external",
        }

    def _sanitize_payload(
        self,
        payload: Dict,
        company_name: str,
        website: str,
        career_page_url: Optional[str],
    ) -> Optional[Dict]:
        if not isinstance(payload, dict):
            return None

        title = str(payload.get("title") or payload.get("role") or "").strip()
        if not title:
            title = "Software Engineer"

        default = self._fallback_payload(title, company_name, website, career_page_url)
        merged = {**default, **payload}

        merged["title"] = str(merged.get("title", "")).strip() or default["title"]
        merged["experience"] = self._as_int(merged.get("experience"), default=default["experience"], min_value=0)
        merged["vacancy"] = self._as_int(merged.get("vacancy"), default=default["vacancy"], min_value=1)
        merged["status"] = str(merged.get("status", "open")).strip().lower() or "open"
        merged["tenure"] = str(merged.get("tenure", "full-time")).strip() or "full-time"
        merged["jobType"] = self._normalize_job_types(
            self._as_str_list(merged.get("jobType"), default=default["jobType"])
        )
        merged["country"] = self._normalize_country(merged.get("country", default["country"])) or default["country"]
        merged["state"] = self._normalize_optional_location(merged.get("state"))
        merged["city"] = self._normalize_optional_location(merged.get("city"))
        merged["department"] = self._normalize_department(
            value=merged.get("department"),
            title=merged["title"],
            fallback=default["department"],
        )

        initial_role_hint = str(merged.get("role", "")).strip()
        initial_skills = self._as_str_list(merged.get("skills"), default=default["skills"])
        if self._contains_non_english_job_data(
            title=merged["title"],
            role_hint=initial_role_hint,
            skills=initial_skills,
        ):
            logger.info(
                "Skipping non-English external job: title='%s' role='%s' skills=%s",
                merged["title"],
                initial_role_hint,
                initial_skills,
            )
            return None

        if self._should_skip_title(merged["title"]):
            logger.info("Skipping unsupported external job title: %s", merged["title"])
            return None

        # ── Role: pass roleName + categoryName directly; no ObjectId creation ──
        # Prefer explicit roleName from LLM output; fall back to de-slugged title.
        role_name_raw = (
            str(merged.get("roleName") or merged.get("role") or "").strip()
            or merged["title"]
        )
        # Strip any leftover ObjectId so we never send a hex string as roleName.
        if _OBJECT_ID_RE.match(role_name_raw):
            role_name_raw = merged["title"]
        merged["roleName"] = TalentAPIClient._format_role_name(role_name_raw)
        merged["categoryName"] = str(
            merged.get("categoryName") or merged.get("department") or "Engineering"
        ).strip()
        # Remove the legacy 'role' ObjectId field — backend no longer expects it.
        merged.pop("role", None)

        merged["level"] = self._normalize_level(
            value=merged.get("level"),
            fallback=default["level"],
        )
        # maxBudget: keep null if not explicitly set; don't force a default number.
        raw_budget = merged.get("maxBudget")
        if raw_budget is not None:
            try:
                budget_int = int(float(raw_budget))
                merged["maxBudget"] = max(0, budget_int) if budget_int > 0 else None
            except Exception:
                merged["maxBudget"] = None
        else:
            merged["maxBudget"] = None

        merged["startDate"] = self._normalize_date(merged.get("startDate"), default["startDate"])
        merged["endDate"] = self._normalize_date(merged.get("endDate"), None)

        # ── Skills: plain string array, no catalog lookup or API creation ──
        raw_skills = self._as_str_list(merged.get("skills"), default=default["skills"])
        # Deduplicate while preserving order.
        seen_skills: set = set()
        clean_skills = []
        for s in raw_skills:
            key = s.strip().lower()
            if key and key not in seen_skills:
                seen_skills.add(key)
                clean_skills.append(s.strip())
        merged["skills"] = clean_skills or default["skills"]
        if self._contains_non_english_job_data(
            title=merged["title"],
            role_hint=str(merged.get("roleName") or ""),
            skills=merged.get("skills") or [],
        ):
            logger.info("Skipping non-English external job after taxonomy: title='%s'", merged["title"])
            return None

        description = str(merged.get("description", default["description"])).strip()
        short_description = str(merged.get("shortDescription", default["shortDescription"])).strip()
        description = self._redact_company_mentions(description, company_name, website)
        short_description = self._redact_company_mentions(short_description, company_name, website)
        merged["description"] = self._ensure_detailed_generic_description(
            description=description or default["description"],
            title=merged["title"],
            department=merged.get("department"),
            level=merged.get("level"),
            skills=self._as_str_list(merged.get("skills"), default=default["skills"]),
        )
        merged["shortDescription"] = self._ensure_generic_short_description(
            short_description=short_description or default["shortDescription"],
            title=merged["title"],
            department=merged.get("department"),
            skills=self._as_str_list(merged.get("skills"), default=default["skills"]),
        )
        merged["source"] = "external"

        return merged

    @staticmethod
    def _as_int(value, default: int, min_value: int = 0) -> int:
        try:
            parsed = int(float(value))
        except Exception:
            parsed = default
        return max(min_value, parsed)

    @staticmethod
    def _as_str_list(value, default: List[str]) -> List[str]:
        if isinstance(value, list):
            cleaned = [str(v).strip() for v in value if str(v).strip()]
            return cleaned or default
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return default

    @staticmethod
    def _contains_disallowed_script(text: str) -> bool:
        return bool(_DISALLOWED_SCRIPT_RE.search(str(text or "")))

    def _contains_non_english_job_data(self, title: str, role_hint: str, skills: List[str]) -> bool:
        if self._contains_disallowed_script(title):
            return True
        if self._contains_disallowed_script(role_hint):
            return True
        for skill in skills or []:
            if self._contains_disallowed_script(skill):
                return True
        return False

    @staticmethod
    def _dedupe_preserve_order(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            key = " ".join(str(item or "").strip().lower().split())
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(str(item).strip())
        return out

    def _align_skills_to_title(self, title: str, skills: List[str]) -> List[str]:
        aligned = self._derive_title_aligned_skills(title)
        if aligned:
            normalized_aligned = self._dedupe_preserve_order(aligned)
            logger.info(
                "Skill alignment applied for title='%s': %s",
                title,
                normalized_aligned,
            )
            return normalized_aligned
        return self._dedupe_preserve_order(skills or ["Communication"])

    @staticmethod
    def _derive_title_aligned_skills(title: str) -> Optional[List[str]]:
        t = str(title or "").lower()
        if not t:
            return None

        if "a/v" in t or "av technician" in t:
            return ["A/V Systems", "Troubleshooting", "Technical Support"]
        if any(k in t for k in ("customer support", "support agent", "helpdesk", "customer success")):
            return ["Customer Service", "Communication", "Problem-Solving"]
        if any(k in t for k in ("program manager", "project manager")):
            return ["Project Management", "Stakeholder Management", "Cross-functional Collaboration"]
        if any(k in t for k in ("security", "cyber")):
            return ["Cybersecurity", "Network Security", "Risk Assessment"]
        if any(k in t for k in ("electrical", "electronics", "electronic engineer")):
            return ["Electrical Systems", "Troubleshooting", "Technical Documentation"]
        if "mechanical" in t:
            return ["Mechanical Design", "Troubleshooting", "Technical Documentation"]
        if any(k in t for k in ("manufacturing", "quality inspector", "material associate", "assembly technician")):
            return ["Quality Control", "Safety Protocols", "Troubleshooting"]
        if any(k in t for k in ("recruiter", "talent acquisition", "human resources", "hr ")):
            return ["Communication", "Talent Acquisition", "Stakeholder Management"]
        if any(k in t for k in ("designer", "ui", "ux", "graphic design")):
            return ["Figma", "Wireframing & Prototyping", "UI/UX Implementation"]
        if any(k in t for k in ("frontend", "react")):
            return ["JavaScript", "React.js", "HTML5"]
        if any(k in t for k in ("devops", "site reliability", "sre", "platform engineer")):
            return ["DevOps", "AWS Cloud Service", "Docker / Kubernetes"]
        if any(k in t for k in ("ai ", " ai", "machine learning", "ml ", "data scientist")):
            return ["Python", "AI Engineers", "Mysql"]
        return None

    @staticmethod
    def _to_iso_utc(dt: datetime) -> str:
        utc = dt.astimezone(timezone.utc)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @staticmethod
    def _normalize_country(value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parts = re.split(r"\s+", raw.lower())
        return " ".join(p.capitalize() for p in parts if p)

    @staticmethod
    def _normalize_optional_location(value):
        if value is None:
            return ""
        raw = str(value).strip()
        if not raw:
            return ""
        if raw.lower() in {"n/a", "na", "none", "null", "-"}:
            return ""
        return raw

    def _normalize_date(self, value, default: str) -> str:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return default
            # Keep existing ISO values as-is (most permissive for API)
            if "T" in raw and raw.endswith("Z"):
                return raw
            # Try plain date
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return self._to_iso_utc(parsed)
            except Exception:
                return default
        return default

    @staticmethod
    def _redact_company_mentions(text: str, company_name: str, website: str) -> str:
        cleaned = str(text or "")
        if not cleaned:
            return cleaned

        targets = []
        if company_name:
            targets.append(company_name.strip())

        domain = str(website or "").strip().lower()
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        if domain:
            targets.append(domain)
            base = domain.split("/")[0]
            if base.startswith("www."):
                base = base[4:]
            if base:
                targets.append(base)
                targets.append(base.split(".")[0])

        for t in [x for x in targets if x]:
            cleaned = re.sub(re.escape(t), "the organization", cleaned, flags=re.IGNORECASE)

        lines = []
        for line in cleaned.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = re.sub(r"[ \t]+", " ", line).strip()
            lines.append(line)
        return "\n".join(lines).strip()

    def _build_generic_description(
        self,
        title: str,
        department: str,
        level: str,
        skills: List[str],
    ) -> str:
        skill_text = ", ".join(skills[:6]) if skills else "relevant tools and frameworks"
        return (
            f"<p><strong>Role Overview:</strong> "
            f"We are hiring a {html.escape(level)} {html.escape(title)} to contribute to a high-impact "
            f"{html.escape(department)} function. This role focuses on delivering reliable outcomes, "
            f"improving execution quality, and driving measurable impact.</p>"
            f"<p><strong>Key Responsibilities:</strong></p>"
            f"<ul>"
            f"<li>Translate business and technical requirements into clear execution plans and deliverables.</li>"
            f"<li>Build, enhance, and maintain scalable solutions with strong quality and performance standards.</li>"
            f"<li>Collaborate with cross-functional stakeholders to align priorities, timelines, and technical decisions.</li>"
            f"<li>Participate in design reviews, implementation planning, testing, and release readiness.</li>"
            f"</ul>"
            f"<p><strong>Required Qualifications:</strong></p>"
            f"<ul>"
            f"<li>Strong hands-on experience with {html.escape(skill_text)}.</li>"
            f"<li>Solid problem-solving, communication, and prioritization skills in fast-moving environments.</li>"
            f"<li>Practical understanding of testing strategy, maintainability, and documentation best practices.</li>"
            f"</ul>"
            f"<p><strong>Preferred Qualifications:</strong></p>"
            f"<ul>"
            f"<li>Experience improving workflows, automation, and delivery efficiency.</li>"
            f"<li>Ability to mentor peers and contribute to process and quality improvements.</li>"
            f"</ul>"
            f"<p><strong>Work Style &amp; Collaboration:</strong></p>"
            f"<ul>"
            f"<li>Work closely with product, operations, and technical peers to deliver high-quality outcomes.</li>"
            f"<li>Take ownership of commitments, communicate proactively, and continuously improve team execution.</li>"
            f"</ul>"
        )

    def _build_generic_short_description(self, title: str, department: str, skills: List[str]) -> str:
        skill_text = ", ".join(skills[:3]) if skills else "modern tooling"
        return (
            f"{title} role in {department}, focused on building scalable solutions, collaborating with cross-functional teams, "
            f"and delivering reliable outcomes using {skill_text}."
        )

    def _ensure_detailed_generic_description(
        self,
        description: str,
        title: str,
        department: str,
        level: str,
        skills: List[str],
    ) -> str:
        clean = str(description or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if self._looks_like_html_description(clean):
            return clean

        converted = self._convert_plain_description_to_html(clean)
        if converted and self._looks_like_html_description(converted):
            return converted

        return self._build_generic_description(
            title=title,
            department=str(department or "Engineering"),
            level=str(level or "Mid-Level"),
            skills=skills or [],
        )

    @staticmethod
    def _looks_like_html_description(text: str) -> bool:
        t = str(text or "").lower()
        return ("<li>" in t and "<strong>" in t) or ("<br" in t and "<strong>" in t)

    def _convert_plain_description_to_html(self, text: str) -> str:
        """
        Convert LLM/plain-text sectioned JD into HTML section + bullet format.
        """
        if not text:
            return ""

        working = text
        markers = [
            "Role Overview:",
            "Key Responsibilities:",
            "Required Qualifications:",
            "Preferred Qualifications:",
            "Work Style & Collaboration:",
            "Work Style & Collaboration -",
        ]
        for marker in markers[1:]:
            working = working.replace(marker, f"\n\n{marker}")

        # Break inline bullet-like text into lines if model returned one paragraph.
        working = re.sub(r"\s+-\s+", "\n- ", working)
        lines = [ln.strip() for ln in working.split("\n") if ln.strip()]
        if not lines:
            return ""

        out: List[str] = []
        in_list = False

        def close_list():
            nonlocal in_list
            if in_list:
                out.append("</ul>")
                in_list = False

        for line in lines:
            if re.match(r"^[-*]\s+", line):
                if not in_list:
                    out.append("<ul>")
                    in_list = True
                item = re.sub(r"^[-*]\s+", "", line).strip()
                out.append(f"<li>{html.escape(item)}</li>")
                continue

            close_list()
            if line.endswith(":"):
                head = html.escape(line[:-1].strip())
                out.append(f"<p><strong>{head}:</strong></p>")
            else:
                out.append(f"<p>{html.escape(line)}</p>")

        close_list()
        return "".join(out)

    def _ensure_generic_short_description(
        self,
        short_description: str,
        title: str,
        department: str,
        skills: List[str],
    ) -> str:
        clean = re.sub(r"\s+", " ", str(short_description or "")).strip()
        if 10 <= len(clean.split()) <= 40:
            return clean
        return self._build_generic_short_description(
            title=title,
            department=str(department or "Engineering"),
            skills=skills or [],
        )

    @staticmethod
    def _infer_department(title: str) -> str:
        t = title.lower()
        if any(x in t for x in ("research", "scientist", "r&d")):
            return "Research"
        if any(x in t for x in ("support", "customer success", "helpdesk")):
            return "Support"
        if any(x in t for x in ("operations", "operator", "ops", "support")):
            return "Operations"
        if any(x in t for x in ("product manager", "product owner")):
            return "Product"
        if any(x in t for x in ("designer", "ux", "ui")):
            return "Design"
        if any(x in t for x in ("sales", "account executive", "business development", "marketing", "hr", "finance")):
            return "Business"
        return "Engineering"

    @staticmethod
    def _normalize_job_types(values: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for raw in values:
            key = str(raw or "").strip().lower()
            if not key:
                continue
            mapped = _JOB_TYPE_ALIASES.get(key)
            if not mapped:
                if "remote" in key:
                    mapped = "remote"
                elif "hybrid" in key:
                    mapped = "hybrid"
                elif "site" in key or "office" in key or "onsite" in key:
                    mapped = "onsite"
            if mapped and mapped in _ALLOWED_JOB_TYPES and mapped not in seen:
                seen.add(mapped)
                normalized.append(mapped)
        return normalized or ["remote"]

    @staticmethod
    def _normalize_department(value, title: str, fallback: str) -> str:
        raw = str(value or "").strip()
        if raw in _ALLOWED_DEPARTMENTS:
            return raw

        low = raw.lower()
        if any(x in low for x in ("design", "ux", "ui")):
            return "Design"
        if any(x in low for x in ("product",)):
            return "Product"
        if any(x in low for x in ("research", "r&d")):
            return "Research"
        if any(x in low for x in ("support", "customer success", "helpdesk")):
            return "Support"
        if any(x in low for x in ("ops", "operation", "support")):
            return "Operations"
        if any(x in low for x in ("sales", "business", "marketing", "finance", "hr")):
            return "Business"
        if any(x in low for x in ("engineer", "developer", "software", "data", "ml", "ai")):
            return "Engineering"

        inferred = ExternalJobPayloadBuilder._infer_department(title or fallback or "")
        if inferred in _ALLOWED_DEPARTMENTS:
            return inferred
        return "Engineering"

    @staticmethod
    def _should_skip_title(title: str) -> bool:
        t = str(title or "").strip().lower()
        if not t:
            return True
        return any(k in t for k in _UNSUPPORTED_TITLE_KEYWORDS)

    @staticmethod
    def _infer_level(title: str) -> str:
        t = title.lower()
        if any(x in t for x in ("principal", "staff", "lead", "architect")):
            return "Lead"
        if any(x in t for x in ("senior", "sr")):
            return "Senior"
        if any(x in t for x in ("intern", "trainee")):
            return "Entry-Level"
        if any(x in t for x in ("junior", "jr")):
            return "Junior"
        return "Mid-Level"

    @staticmethod
    def _normalize_level(value, fallback: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return fallback

        # Exact allowed value passthrough
        if raw in _ALLOWED_LEVELS.values():
            return raw

        key = raw.lower().replace("_", "-")
        key = re.sub(r"\s+", " ", key).strip()
        if key in ("mid", "mid level"):
            key = "mid-level"
        elif key in ("entry", "intern", "trainee", "entry level"):
            key = "entry-level"
        elif key in ("exec", "c-level", "c suite", "c-suite"):
            key = "executive"
        elif key in ("research", "researcher"):
            key = "research associate"
        elif key in ("sr", "senior engineer", "senior developer"):
            key = "senior"

        return _ALLOWED_LEVELS.get(key, fallback)

    @staticmethod
    def _infer_skills(title: str) -> List[str]:
        t = title.lower()
        if "python" in t:
            return ["Python"]
        if "java" in t:
            return ["Java"]
        if "react" in t or "frontend" in t:
            return ["JavaScript", "React"]
        if "data" in t or "ml" in t or "ai" in t:
            return ["Python", "SQL"]
        return ["Communication"]
