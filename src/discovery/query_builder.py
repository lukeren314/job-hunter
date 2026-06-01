"""Build DDGS search queries from personal_info + requirements."""

_LOCATION_VARIANTS = ["remote"]
_JOB_URL_PATTERNS = [
    "site:linkedin.com/jobs",
    "site:greenhouse.io",
    "site:lever.co",
    "site:ashbyhq.com",
    "site:workday.com",
]


def build_queries(personal_info: dict, requirements: dict) -> list[tuple[str, str]]:
    """Return list of (query_string, label) pairs."""
    job_titles: list[str] = requirements.get("job_queries", [])
    if not job_titles:
        return []

    must_haves = requirements.get("must_haves", {})
    location_center = must_haves.get("location_center", {})
    user_location = personal_info.get("location", "")
    allow_remote: bool = must_haves.get("allow_remote", True)

    # Extract city from location string (e.g. "Los Angeles, CA" → "Los Angeles")
    city = location_center.get("name") or user_location
    city = city.split(",")[0].strip() if city else ""

    queries: list[tuple[str, str]] = []

    for title in job_titles:
        # Location-specific queries
        if city:
            for site_pattern in _JOB_URL_PATTERNS:
                q = f"{title} jobs {city} {site_pattern}"
                queries.append((q, f"{title}/{city}"))

        # Remote queries
        if allow_remote:
            for site_pattern in _JOB_URL_PATTERNS:
                q = f"{title} remote jobs {site_pattern}"
                queries.append((q, f"{title}/remote"))

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for item in queries:
        if item[0] not in seen:
            seen.add(item[0])
            deduped.append(item)
    return deduped


import re

# Require job-ID segment to filter out listing/board index pages
_JOB_URL_STRICT_PATTERNS = [
    # greenhouse: /jobs/{digits}
    r"(?:boards|job-boards)\.greenhouse\.io/[^/?#]+/jobs/\d+",
    # lever: UUID
    r"jobs\.lever\.co/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    # ashby: UUID
    r"jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    r"app\.ashbyhq\.com/[^/?#]+/[^/?#]+/[0-9a-f]{8}-",
    # linkedin: individual job view
    r"linkedin\.com/jobs/view/",
    # workday: job ID required
    r"myworkday\.com/.+/job/\d+",
    # others — no strict ID requirement yet
    r"apply\.workable\.com/",
    r"careers\.smartrecruiters\.com/",
]

_JOB_URL_RE = re.compile("|".join(_JOB_URL_STRICT_PATTERNS))


def is_job_url(url: str) -> bool:
    return bool(_JOB_URL_RE.search(url))
