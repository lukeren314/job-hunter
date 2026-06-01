import json
import re
from bs4 import BeautifulSoup

from extractor.shared import (
    canonical_id, normalize_url, html_to_text,
    parse_work_type, parse_employment_type, parse_salary, extract_level,
    parse_description_section, parse_seniority_level,
    _extract_salary_from_description,
    RESPONSIBILITIES_PATTERNS, REQUIREMENTS_PATTERNS, PREFERRED_PATTERNS,
)

_EMP_TYPE_MAP = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "CONTRACTOR": "Contract",
    "CONTRACT": "Contract",
    "TEMPORARY": "Contract",
    "INTERN": "Internship",
}

_GENERIC_TITLES = {
    "job details", "job listing", "careers", "jobs", "open positions",
    "job opportunities", "career opportunities", "apply now", "loading...",
}


def _is_generic_title(t: str) -> bool:
    return not t or t.lower().strip() in _GENERIC_TITLES


def _parse_job_posting(json_obj: dict) -> dict | None:
    title = json_obj.get("title") or None
    company = (json_obj.get("hiringOrganization") or {}).get("name") or None

    locs = json_obj.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    addr = (locs[0] if locs else {}).get("address") if locs else None
    location = None
    if addr and isinstance(addr, dict):
        parts = [
            addr.get("addressLocality") if isinstance(addr.get("addressLocality"), str) else None,
            addr.get("addressRegion") if isinstance(addr.get("addressRegion"), str) else None,
        ]
        parts = [p for p in parts if p]
        location = ", ".join(parts) or (
            addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None
        )
    elif locs and isinstance((locs[0] or {}).get("name"), str):
        location = locs[0]["name"]

    salary_min = salary_max = None
    bs = json_obj.get("baseSalary") or {}
    if isinstance(bs, dict) and bs.get("value"):
        v = bs["value"]
        if isinstance(v, dict):
            salary_min = v.get("minValue") if isinstance(v.get("minValue"), (int, float)) else (
                v.get("value") if isinstance(v.get("value"), (int, float)) else None
            )
            salary_max = v.get("maxValue") if isinstance(v.get("maxValue"), (int, float)) else None
            unit = (v.get("unitText") or "").upper()
            if unit == "MONTH":
                if salary_min: salary_min = round(salary_min * 12)
                if salary_max: salary_max = round(salary_max * 12)
            elif unit == "HOUR":
                if salary_min: salary_min = round(salary_min * 2080)
                if salary_max: salary_max = round(salary_max * 2080)

    raw_emp = json_obj.get("employmentType") or []
    if isinstance(raw_emp, str):
        raw_emp = [raw_emp]
    employment_type = next(
        (_EMP_TYPE_MAP.get(t.upper()) for t in raw_emp if _EMP_TYPE_MAP.get((t or "").upper())),
        None,
    )

    is_remote = json_obj.get("jobLocationType") == "TELECOMMUTE"
    raw_desc = json_obj.get("description") or ""
    description = html_to_text(raw_desc)

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "employment_type": employment_type,
        "is_remote": is_remote,
        "description": description,
    }


def _try_json_ld(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        try:
            if isinstance(data, dict) and "@graph" in data:
                data = data["@graph"]
            candidates = data if isinstance(data, list) else [data]
            posting = next((c for c in candidates if (c or {}).get("@type") == "JobPosting"), None)
            if not posting:
                continue
            parsed = _parse_job_posting(posting)
            if not parsed or not parsed.get("title"):
                continue
            if parsed["salary_min"] is None:
                sal = _extract_salary_from_description(parsed["description"])
                parsed.update(sal)
            desc = parsed["description"]
            work_type = parse_work_type(
                ["remote"] if parsed["is_remote"] else [],
                desc,
                parsed.get("location"),
            )
            return {
                **parsed,
                "work_type": work_type,
                "responsibilities": parse_description_section(desc, RESPONSIBILITIES_PATTERNS),
                "requirements": parse_description_section(desc, REQUIREMENTS_PATTERNS),
                "preferred_qualifications": parse_description_section(desc, PREFERRED_PATTERNS),
                "seniority_level": None,
            }
        except Exception:
            continue
    return None


def _parse_page_title_tag(raw: str) -> dict:
    if not raw:
        return {}
    cleaned = re.sub(
        r"\s*[-|]\s*(careers?|jobs?|greenhouse|lever|ashby|workday|glassdoor|indeed)\s*$",
        "",
        raw,
        flags=re.I,
    ).strip()
    m = re.search(r"\s[-|]\s", cleaned)
    if m:
        idx = m.start()
        return {
            "title": cleaned[:idx].strip(),
            "company": cleaned[idx + len(m.group()):].strip(),
        }
    return {"title": cleaned}


def _dom_heuristics(soup: BeautifulSoup, url: str) -> dict:
    # Title
    og_title = soup.select_one('meta[property="og:title"]')
    page_title_raw = soup.title.string.strip() if soup.title else ""
    h1_text = soup.select_one("h1")
    h1_text = h1_text.get_text(strip=True) if h1_text else ""

    og_title_text = og_title.get("content", "").strip() if og_title else ""
    parsed_page = _parse_page_title_tag(page_title_raw)

    title = ""
    company = ""
    if og_title_text and not _is_generic_title(og_title_text):
        title = og_title_text
    if not title and h1_text and not _is_generic_title(h1_text):
        title = h1_text
    if not title and parsed_page.get("title") and not _is_generic_title(parsed_page["title"]):
        title = parsed_page["title"]
        company = parsed_page.get("company", "")

    og_site = soup.select_one('meta[property="og:site_name"]')
    if not company and og_site:
        company = og_site.get("content", "").strip()

    # Location
    location = ""
    for sel in ['[class*="location"]', '[data-field="location"]', '[itemprop="jobLocation"]']:
        el = soup.select_one(sel)
        if el:
            location = el.get_text(strip=True)
            break

    # Description
    description = ""
    for sel in [
        '[class*="job-description"]', '[class*="jobDescription"]',
        '[class*="job-details"]', '[id*="job-description"]',
        "article", "main",
    ]:
        el = soup.select_one(sel)
        if el:
            description = el.get_text("\n", strip=True)
            break

    return {"title": title, "company": company, "location": location, "description": description}


def extract(html: str, url: str, use_llm: bool = False) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    # Strategy 1: JSON-LD
    result = _try_json_ld(soup)

    # Strategy 2: DOM heuristics
    if not result:
        dom = _dom_heuristics(soup, url)
        desc = dom["description"]
        sal = parse_salary([], desc)
        result = {
            "title": dom["title"] or None,
            "company": dom["company"] or None,
            "location": dom["location"] or None,
            "description": desc or None,
            "salary_min": sal["salary_min"],
            "salary_max": sal["salary_max"],
            "employment_type": parse_employment_type([desc]),
            "work_type": parse_work_type([], desc, dom["location"] or None),
            "seniority_level": None,
            "responsibilities": parse_description_section(desc, RESPONSIBILITIES_PATTERNS),
            "requirements": parse_description_section(desc, REQUIREMENTS_PATTERNS),
            "preferred_qualifications": parse_description_section(desc, PREFERRED_PATTERNS),
        }

    # Strategy 3: LLM fill (optional)
    if use_llm and not result.get("title"):
        try:
            from extractor.llm_fill import fill_missing_fields
            result = fill_missing_fields(result)
        except Exception:
            pass

    title = result.get("title") or ""
    company = result.get("company") or ""
    location = result.get("location") or ""
    description = result.get("description") or ""
    raw_content = f"TITLE: {title}\nCOMPANY: {company}\nLOCATION: {location}\nDESCRIPTION: {description}"

    return {
        "canonical_id": canonical_id(url),
        "source_url": normalize_url(url),
        "external_url": None,
        "company": company or None,
        "title": title or None,
        "location": location or None,
        "work_type": result.get("work_type"),
        "salary_min": result.get("salary_min"),
        "salary_max": result.get("salary_max"),
        "employment_type": result.get("employment_type"),
        "seniority_level": result.get("seniority_level"),
        "level": extract_level(title, result.get("seniority_level"), description),
        "responsibilities": result.get("responsibilities"),
        "requirements": result.get("requirements"),
        "preferred_qualifications": result.get("preferred_qualifications"),
        "description": description or None,
        "raw_content": raw_content,
    }
