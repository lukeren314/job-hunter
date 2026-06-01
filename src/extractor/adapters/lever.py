import re
from bs4 import BeautifulSoup

from extractor.shared import (
    canonical_id, normalize_url,
    parse_work_type, parse_employment_type, parse_salary, extract_level,
    parse_description_section,
    RESPONSIBILITIES_PATTERNS, REQUIREMENTS_PATTERNS, PREFERRED_PATTERNS,
)


def extract(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    title = (
        _text(soup, ".posting-headline h2")
        or _text(soup, 'h2[data-qa="posting-name"]')
        or _text(soup, '[data-qa="posting-name"]')
        or _text(soup, "h2")
        or _text(soup, "h1")
        or ""
    )

    company = (
        _text(soup, ".main-header-text h2")
        or _text(soup, '[class*="company-name"]')
        or _text(soup, "header h2")
        or ""
    )
    if not company:
        img = soup.select_one("img[alt]")
        company = img.get("alt", "").strip() if img else ""
    company = re.sub(r'\s*logo\s*$', '', company, flags=re.I).strip()
    # Discard if we grabbed the ATS platform name itself
    if company.lower() in ("lever", "greenhouse", "ashby", "workday"):
        company = ""

    location = (
        _text(soup, '[data-qa="posting-location"]')
        or _text(soup, ".sort-by-time.location")
        or _text(soup, ".posting-categories .location")
        or _text(soup, '[class*="location"]')
        or ""
    )

    work_type_text = (
        _text(soup, ".workplaceTypes")
        or _text(soup, '[data-qa="posting-workplace-type"]')
        or ""
    )

    desc_el = (
        soup.select_one(".section-wrapper")
        or soup.select_one(".posting-content")
        or soup.select_one('[class*="posting-description"]')
        or soup.select_one("main")
    )
    description = desc_el.get_text("\n", strip=True) if desc_el else ""

    slug_match = re.search(r"jobs\.lever\.co/([^/?#]+)/", url)
    company_from_slug = (
        slug_match.group(1).replace("-", " ").title() if slug_match else ""
    )
    company_from_slug = re.sub(r'\s*logo\s*$', '', company_from_slug, flags=re.I).strip()

    salary = parse_salary([], description)
    level = extract_level(title, None, description)

    return {
        "canonical_id": canonical_id(url),
        "source_url": normalize_url(url),
        "external_url": None,
        "company": company or company_from_slug or None,
        "title": title or None,
        "location": location or None,
        "work_type": parse_work_type([work_type_text], description, location or None),
        "salary_min": salary["salary_min"],
        "salary_max": salary["salary_max"],
        "employment_type": parse_employment_type([work_type_text, description]),
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
