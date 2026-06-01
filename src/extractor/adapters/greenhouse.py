import re
from bs4 import BeautifulSoup

from extractor.shared import (
    canonical_id, normalize_url, html_to_text,
    parse_work_type, parse_employment_type, parse_salary, extract_level,
    parse_description_section,
    RESPONSIBILITIES_PATTERNS, REQUIREMENTS_PATTERNS, PREFERRED_PATTERNS,
)


def extract(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    title = (
        _text(soup, "#app-title")
        or _text(soup, ".app-title")
        or _text(soup, "h1.heading")
        or _text(soup, "h1")
        or ""
    )

    meta_company = (
        _text(soup, '[class*="company-name"]')
        or _text(soup, '[class*="companyName"]')
        or _text(soup, ".company-name")
        or ""
    )

    location = (
        _text(soup, "#job-location")
        or _text(soup, ".location")
        or _text(soup, '[data-field="location"]')
        or _text(soup, '[class*="location"]')
        or ""
    )

    desc_el = (
        soup.select_one("#content")
        or soup.select_one(".job-post")
        or soup.select_one('[class*="job-description"]')
        or soup.select_one("main")
    )
    description = desc_el.get_text("\n", strip=True) if desc_el else ""
    all_text = soup.get_text(" ")

    slug_match = re.search(r"boards\.greenhouse\.io/([^/?#]+)", url) or re.search(
        r"job-boards\.greenhouse\.io/([^/?#]+)", url
    )
    company_from_slug = (
        slug_match.group(1).replace("-", " ").title() if slug_match else ""
    )
    company = meta_company or company_from_slug

    salary = parse_salary([], description)
    level = extract_level(title, None, description)

    return {
        "canonical_id": canonical_id(url),
        "source_url": normalize_url(url),
        "external_url": None,
        "company": company or None,
        "title": title or None,
        "location": location or None,
        "work_type": parse_work_type([], description, location or None),
        "salary_min": salary["salary_min"],
        "salary_max": salary["salary_max"],
        "employment_type": parse_employment_type([all_text]),
        "seniority_level": None,
        "level": level,
        "responsibilities": parse_description_section(description, RESPONSIBILITIES_PATTERNS),
        "requirements": parse_description_section(description, REQUIREMENTS_PATTERNS),
        "preferred_qualifications": parse_description_section(description, PREFERRED_PATTERNS),
        "description": description or None,
        "raw_content": f"TITLE: {title}\nCOMPANY: {company}\nLOCATION: {location}\nDESCRIPTION: {description}",
    }


def _text(soup: BeautifulSoup, selector: str) -> str:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else ""
