"""
Ashby ATS extractor using the public GraphQL API.
Handles: jobs.ashbyhq.com/{company}/{job_id}
"""
import re
import httpx
from extractor.shared import (
    canonical_id, normalize_url, html_to_text, extract_level,
    parse_work_type, parse_employment_type, parse_salary,
    parse_description_section,
    RESPONSIBILITIES_PATTERNS, REQUIREMENTS_PATTERNS, PREFERRED_PATTERNS,
)

_GQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"
_GQL_QUERY = """
query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
    jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
        id
        title
        descriptionHtml
        locationName
        employmentType
    }
}
"""

_EMP_MAP = {
    "FullTime": "Full-time",
    "PartTime": "Part-time",
    "Contract": "Contract",
    "Intern": "Internship",
}

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}


_KNOWN_CASINGS = {
    "openai": "OpenAI", "ai": "AI", "trm": "TRM", "nox": "NOX",
    "spruceid": "SprucID", "scribedinc": "Scribd", "vetcove": "Vetcove",
}

def _slug_to_company(slug: str) -> str:
    lower = slug.lower()
    if lower in _KNOWN_CASINGS:
        return _KNOWN_CASINGS[lower]
    return slug.replace("-", " ").title()


def extract(url: str) -> dict | None:
    m = re.match(r"https://jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if not m:
        return None
    company_slug, job_id = m.group(1), m.group(2)

    try:
        resp = httpx.post(
            _GQL_URL,
            json={
                "operationName": "ApiJobPosting",
                "variables": {
                    "organizationHostedJobsPageName": company_slug,
                    "jobPostingId": job_id,
                },
                "query": _GQL_QUERY,
            },
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Ashby API error: {e}") from e

    jp = (data.get("data") or {}).get("jobPosting")
    if not jp:
        return None

    title = jp.get("title") or ""
    company = _slug_to_company(company_slug)
    location = jp.get("locationName") or ""
    emp_raw = jp.get("employmentType") or ""
    employment_type = _EMP_MAP.get(emp_raw) or None
    raw_html = jp.get("descriptionHtml") or ""
    description = html_to_text(raw_html)

    sal = parse_salary([], description)
    salary_min, salary_max = sal["salary_min"], sal["salary_max"]

    work_type = parse_work_type([], description, location or None)
    level = extract_level(title, None, description)
    raw_content = f"TITLE: {title}\nCOMPANY: {company}\nLOCATION: {location}\nDESCRIPTION: {description}"

    return {
        "canonical_id": canonical_id(url),
        "source_url": normalize_url(url),
        "external_url": None,
        "company": company or None,
        "title": title or None,
        "location": location or None,
        "work_type": work_type,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "employment_type": employment_type,
        "seniority_level": None,
        "level": level,
        "responsibilities": parse_description_section(description, RESPONSIBILITIES_PATTERNS),
        "requirements": parse_description_section(description, REQUIREMENTS_PATTERNS),
        "preferred_qualifications": parse_description_section(description, PREFERRED_PATTERNS),
        "description": description or None,
        "raw_content": raw_content,
    }
