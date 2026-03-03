"""
Static Talent role/skill catalogs + fuzzy resolver.

These catalogs are used to map LLM output to known role/skill records before
posting external jobs.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional


def _norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


ROLE_CATALOG: List[Dict[str, str]] = [
    {"_id": "67ea7c3c26766a698e2249bd", "name": "Senior Odoo Engineer"},
    {"_id": "67e3d2717aebbb3cee849901", "name": "Frontend Engineer (React, Next Js)"},
    {"_id": "67e3d2717aebbb3cee8498fc", "name": "Lead MERN Engineer"},
    {"_id": "67eb843526766a698e224a2f", "name": "Senior Mern Developer"},
    {"_id": "67ea8c8026766a698e2249dd", "name": "Partnership Manager"},
    {"_id": "67eb843526766a698e224a2e", "name": "Lead HRM"},
    {"_id": "67ea8c8026766a698e2249e7", "name": "Devops Engineer"},
    {"_id": "67ea8c8026766a698e2249e6", "name": "Ass. HRM"},
    {"_id": "67ea8c8026766a698e2249e5", "name": "QA Automation Engineer"},
    {"_id": "67ea8c8026766a698e2249e4", "name": "React Engineer"},
    {"_id": "67ea8c8026766a698e2249e3", "name": "Email Marketing Specialist"},
    {"_id": "67ea8c8026766a698e2249e2", "name": "BDM"},
    {"_id": "67ea8c8026766a698e2249e1", "name": "Senior Finance Manager"},
    {"_id": "67ea8c8026766a698e2249e0", "name": "Lead Frontend Engineer"},
    {"_id": "67ea8c8026766a698e2249df", "name": "Senior Frontend Engineer"},
    {"_id": "67ea8c8026766a698e2249de", "name": "Director of Sales"},
    {"_id": "67e3d2717aebbb3cee8498fd", "name": "D365 Techno-Functional Consultant (Finance Focus)"},
    {"_id": "67eb843526766a698e224a30", "name": "Senior Automation Engineer"},
    {"_id": "67eb843526766a698e224a31", "name": "US Recruiter"},
    {"_id": "67eb843526766a698e224a32", "name": "Lead Odoo Engineer"},
    {"_id": "67eb843526766a698e224a33", "name": "Python Engineer"},
    {"_id": "67eb843526766a698e224a34", "name": "Senior Odoo Developer"},
    {"_id": "67eb843526766a698e224a35", "name": "Senior Java Developer"},
    {"_id": "67eb843526766a698e224a36", "name": "Node JS Developer"},
    {"_id": "67eb843526766a698e224a37", "name": "UIUX Designer"},
    {"_id": "67eb843526766a698e224a38", "name": "Lead Node.js Developer"},
    {"_id": "67eb843526766a698e224a39", "name": "Senior Java Engineer"},
    {"_id": "67eb843526766a698e224a3a", "name": "Senior HR Recruiter"},
    {"_id": "67eb843526766a698e224a3b", "name": "AI Engineer"},
    {"_id": "6825cc801ada1b444d7ccb26", "name": "HR Intern"},
    {"_id": "67ea8c8026766a698e2249db", "name": "SDR"},
    {"_id": "67e3d2717aebbb3cee8498fe", "name": "Lead Automation Engineer"},
    {"_id": "67e3d2717aebbb3cee8498ff", "name": "Senior Product Designer"},
    {"_id": "67e3d2717aebbb3cee849900", "name": "Lead Java Engineer"},
    {"_id": "67e3d2717aebbb3cee849902", "name": "Senior Graphic Designer"},
    {"_id": "67e3d2717aebbb3cee849903", "name": "Enterprise Sales & GTM Advisor (USA Market)"},
    {"_id": "67e3d2717aebbb3cee849904", "name": "Email Marketing Associate"},
    {"_id": "67e3d2717aebbb3cee849905", "name": "Senior Business Development Manager - USA"},
    {"_id": "67e3d2717aebbb3cee849906", "name": "Senior Business Development Manager - India"},
    {"_id": "67e3d2717aebbb3cee849907", "name": "Sales Development Representatives"},
    {"_id": "67ea8c8026766a698e2249cb", "name": "Lead PHP Engineer"},
    {"_id": "67ea8c8026766a698e2249cc", "name": "Lead Flutter Engineer"},
    {"_id": "67ea8c8026766a698e2249cd", "name": "Lead Python Engineer"},
    {"_id": "67ea8c8026766a698e2249ce", "name": "Product Manager"},
    {"_id": "67ea8c8026766a698e2249d0", "name": "Product Designer"},
    {"_id": "67ea8c8026766a698e2249dc", "name": "Director of HR"},
    {"_id": "67ea8c8026766a698e2249da", "name": "Lead Parnership Manager"},
    {"_id": "67ea8c8026766a698e2249d9", "name": "Marketing Manager"},
    {"_id": "67ea8c8026766a698e2249d8", "name": "Asst Partnership Manager"},
    {"_id": "67ea8c8026766a698e2249d7", "name": "Lead Flutter Developer"},
    {"_id": "67ea8c8026766a698e2249d6", "name": "Senior HRM"},
    {"_id": "67ea8c8026766a698e2249d5", "name": "Senior PHP Engineer"},
    {"_id": "67ea8c8026766a698e2249d4", "name": "React Frontend Engineer"},
    {"_id": "67ea8c8026766a698e2249d3", "name": "Engineering Manager"},
    {"_id": "67ea8c8026766a698e2249d2", "name": "Senior React Engineer"},
    {"_id": "67ea8c8026766a698e2249d1", "name": "Principal Frontend Engineer"},
    {"_id": "67ea8c8026766a698e2249cf", "name": "Lead UI/UX Designer"},
    {"_id": "6957b23fe027a97c952b500d", "name": "java php developer"},
    {"_id": "6957b2fa4f102ec10cae9da3", "name": "python java php developer"},
    {"_id": "69592a5b154626767030127f", "name": "Python Django Developer"},
    {"_id": "695cacb3a0821fa24cbb864a", "name": "Business Development Executive"},
    {"_id": "695e1249503ac648b15b96a3", "name": "Senior Odoo Engineer 1"},
    {"_id": "698429c9426f6eea6f69866d", "name": "RSA archer Developer"},
]


SKILL_CATALOG: List[Dict[str, str]] = [
    {"_id": "67e016547aebbb3cee84984d", "name": "Figma"},
    {"_id": "67e016547aebbb3cee849853", "name": "AngularJS"},
    {"_id": "67e016547aebbb3cee849857", "name": "Front-end"},
    {"_id": "67e016547aebbb3cee849858", "name": "Full-stack"},
    {"_id": "67e016547aebbb3cee849859", "name": "HTML5"},
    {"_id": "67e016547aebbb3cee84985a", "name": "iOS"},
    {"_id": "67e016547aebbb3cee84985d", "name": "Svelte Developers"},
    {"_id": "67e016547aebbb3cee849860", "name": "Web Developers"},
    {"_id": "67e016547aebbb3cee849862", "name": "WooCommerce"},
    {"_id": "67e016547aebbb3cee849870", "name": "AI Engineers"},
    {"_id": "67e016547aebbb3cee849871", "name": "Android"},
    {"_id": "67e016547aebbb3cee849872", "name": "Angular"},
    {"_id": "67e016547aebbb3cee849873", "name": "C# Developers"},
    {"_id": "67e016547aebbb3cee849875", "name": "DevOps"},
    {"_id": "67e016547aebbb3cee849877", "name": "Flutter Developers"},
    {"_id": "67e016547aebbb3cee849879", "name": "Java"},
    {"_id": "67e016547aebbb3cee84987a", "name": "JavaScript"},
    {"_id": "67e016547aebbb3cee84987b", "name": "Laravel"},
    {"_id": "67e016547aebbb3cee84987e", "name": "Node.js"},
    {"_id": "67e016547aebbb3cee84987f", "name": "Odoo"},
    {"_id": "67e016547aebbb3cee849882", "name": "PHP"},
    {"_id": "67e016547aebbb3cee849883", "name": "Power BI"},
    {"_id": "67e016547aebbb3cee849885", "name": "Python"},
    {"_id": "67e016547aebbb3cee849886", "name": "QA Engineers"},
    {"_id": "67e016547aebbb3cee849888", "name": "React.js"},
    {"_id": "67e016547aebbb3cee849889", "name": "React Native"},
    {"_id": "67e016547aebbb3cee84988d", "name": "Shopify"},
    {"_id": "67e016547aebbb3cee84988e", "name": "Software Developers"},
    {"_id": "67e016547aebbb3cee849894", "name": "WordPress Developers"},
    {"_id": "67e016547aebbb3cee849897", "name": "AWS Cloud Service"},
    {"_id": "67e016547aebbb3cee849898", "name": "Google Cloud Services"},
    {"_id": "67e016547aebbb3cee849899", "name": "Terraform Cloud"},
    {"_id": "67e016547aebbb3cee84989a", "name": "Flutter Development"},
    {"_id": "67e016547aebbb3cee84989b", "name": "Android Development"},
    {"_id": "67e016547aebbb3cee84989d", "name": "UI/UX Implementation"},
    {"_id": "67e016547aebbb3cee84989e", "name": "Wireframing & Prototyping"},
    {"_id": "67e016547aebbb3cee8498a0", "name": "API Integration"},
    {"_id": "67e016547aebbb3cee8498a1", "name": "Mysql"},
    {"_id": "67e016547aebbb3cee8498a2", "name": "Nosql"},
    {"_id": "67e016547aebbb3cee8498a3", "name": "Git-GitHub"},
    {"_id": "67e016547aebbb3cee8498a4", "name": "Selenium WebDriver"},
    {"_id": "67e016547aebbb3cee8498a5", "name": "Postman"},
    {"_id": "67e016547aebbb3cee8498a6", "name": "Docker / Kubernetes"},
    {"_id": "67e016547aebbb3cee8498a8", "name": "Automation Testing"},
    {"_id": "67e016547aebbb3cee8498a9", "name": "Backend"},
    {"_id": "67e016547aebbb3cee849851", "name": "Webflow Designers"},
    {"_id": "67e016547aebbb3cee849852", "name": "WordPress Designers"},
    {"_id": "67e016547aebbb3cee84984e", "name": "UX Researchers"},
    {"_id": "67e016547aebbb3cee849850", "name": "Web Designers"},
    {"_id": "6960c88186f5075dc8a56ee2", "name": "Video Editors"},
]


class TalentTaxonomyMatcher:
    def __init__(self):
        self.roles = ROLE_CATALOG
        self.skills = SKILL_CATALOG
        self._roles_norm = [(_norm(r["name"]), r) for r in self.roles]
        self._skills_norm = [(_norm(s["name"]), s) for s in self.skills]

    def resolve_role(
        self,
        role_hint: str,
        title: str,
        description: str = "",
        threshold: float = 0.58,
    ) -> Optional[Dict[str, str]]:
        candidates = [role_hint, title, f"{title} {description}"]
        best = None
        best_score = 0.0
        for c in candidates:
            if not c:
                continue
            cn = _norm(c)
            for rn, role in self._roles_norm:
                if not rn:
                    continue
                score = self._score(cn, rn)
                if score > best_score:
                    best_score = score
                    best = role
        if best and best_score >= threshold:
            return best
        return None

    def resolve_skills(
        self,
        skill_hints: List[str],
        title: str,
        description: str,
        limit: int = 6,
        threshold: float = 0.62,
    ) -> List[Dict[str, str]]:
        pool = list(skill_hints or [])
        pool.append(title or "")
        pool.append(description or "")
        ranked: List[tuple[float, Dict[str, str]]] = []

        for hint in pool:
            hn = _norm(hint)
            if not hn:
                continue
            for sn, skill in self._skills_norm:
                if not sn:
                    continue
                score = self._score(hn, sn)
                if score >= threshold:
                    ranked.append((score, skill))

        ranked.sort(key=lambda x: x[0], reverse=True)
        out: List[Dict[str, str]] = []
        seen = set()
        for _, skill in ranked:
            sid = skill["_id"]
            if sid in seen:
                continue
            out.append(skill)
            seen.add(sid)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _score(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.93
        return SequenceMatcher(None, a, b).ratio()

