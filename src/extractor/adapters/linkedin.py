import json
import re

from extractor.shared import (
    canonical_id, normalize_url, extract_level,
    parse_work_type, parse_employment_type, parse_salary, parse_seniority_level,
    parse_description_section,
    RESPONSIBILITIES_PATTERNS, REQUIREMENTS_PATTERNS, PREFERRED_PATTERNS,
)

_ATS_PATTERNS = [
    re.compile(r"boards\.greenhouse\.io/embed/job_app"),
    re.compile(r"job-boards\.greenhouse\.io"),
    re.compile(r"jobs\.lever\.co/.+/apply"),
    re.compile(r"jobs\.ashbyhq\.com"),
    re.compile(r"app\.ashbyhq\.com"),
    re.compile(r"jobs\.ashby\.io"),
    re.compile(r"myworkday\.com"),
    re.compile(r"apply\.workable\.com"),
    re.compile(r"careers\.smartrecruiters\.com"),
]


async def extract(page, url: str) -> dict | None:
    current_url = page.url
    if re.search(r"linkedin\.com/(login|authwall|checkpoint)", current_url):
        print("   ⚠  LinkedIn session expired — extracting public data only")

    try:
        await page.wait_for_selector(
            ".top-card-layout__title, .jobs-unified-top-card__job-title",
            timeout=10_000,
        )
    except Exception:
        pass

    show_more = page.locator(".show-more-less-html__button--more")
    if await show_more.count() > 0:
        try:
            await show_more.first().click()
            await page.wait_for_timeout(500)
        except Exception:
            pass

    data = await page.evaluate("""() => {
        const title = document.querySelector('.top-card-layout__title')?.innerText?.trim() || '';
        const company = (
            document.querySelector('.topcard__org-name-link') ||
            document.querySelector('.topcard__org-name')
        )?.innerText?.trim() || '';

        const bulletFlavors = Array.from(document.querySelectorAll('.topcard__flavor--bullet'))
            .map(el => el.innerText?.trim()).filter(Boolean);

        const salaryText = document.querySelector('.salary-main-rail__formatted-salary')?.innerText?.trim() || '';

        const criteriaLabels = Array.from(document.querySelectorAll('.description__job-criteria-subheader'))
            .map(el => el.innerText?.trim());
        const criteriaValues = Array.from(document.querySelectorAll('.description__job-criteria-text'))
            .map(el => el.innerText?.trim());

        const description = (
            document.querySelector('.show-more-less-html__markup') ||
            document.querySelector('.description__text')
        )?.innerText?.trim() || '';

        let externalUrl = null;
        try {
            const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
            for (const s of scripts) {
                const d = JSON.parse(s.textContent);
                const candidate = d.url || d['@graph']?.find?.(i => i.url)?.url;
                if (candidate && !candidate.includes('linkedin.com')) { externalUrl = candidate; break; }
            }
        } catch {}
        if (!externalUrl) {
            const atsPats = [
                /boards\\.greenhouse\\.io\\/embed\\/job_app/,
                /job-boards\\.greenhouse\\.io/,
                /jobs\\.lever\\.co\\/.+\\/apply/,
                /jobs\\.ashbyhq\\.com/, /app\\.ashbyhq\\.com/, /jobs\\.ashby\\.io/,
                /myworkday\\.com/, /apply\\.workable\\.com/,
                /careers\\.smartrecruiters\\.com/,
            ];
            for (const link of document.querySelectorAll('a[href]')) {
                if (atsPats.some(re => re.test(link.href))) { externalUrl = link.href; break; }
            }
        }
        return { title, company, bulletFlavors, salaryText, criteriaLabels, criteriaValues, description, externalUrl };
    }""")

    title = data.get("title") or ""
    company = data.get("company") or ""
    bullet_flavors = data.get("bulletFlavors") or []
    salary_text = data.get("salaryText") or ""
    criteria_labels = data.get("criteriaLabels") or []
    criteria_values = data.get("criteriaValues") or []
    description = data.get("description") or ""
    external_url = data.get("externalUrl") or None

    location = bullet_flavors[0] if bullet_flavors else None

    emp_type_idx = next(
        (i for i, l in enumerate(criteria_labels) if re.search(r"employment type", l, re.I)), -1
    )
    employment_type = parse_employment_type(
        [criteria_values[emp_type_idx]] if emp_type_idx >= 0 else bullet_flavors
    )

    work_type_idx = next(
        (i for i, l in enumerate(criteria_labels) if re.search(r"workplace type", l, re.I)), -1
    )
    work_type = parse_work_type(
        [criteria_values[work_type_idx], *bullet_flavors] if work_type_idx >= 0 else bullet_flavors,
        description,
        location,
    )

    salary_idx = next(
        (i for i, l in enumerate(criteria_labels) if re.search(r"salary", l, re.I)), -1
    )
    salary = parse_salary(
        [salary_text, criteria_values[salary_idx] if salary_idx >= 0 else ""],
        description,
    )

    seniority_level = parse_seniority_level(criteria_labels, criteria_values)
    level = extract_level(title, seniority_level, description)

    raw_content = "\n".join([
        f"TITLE: {title}", f"COMPANY: {company}", f"LOCATION: {location}",
        f"WORK_TYPE: {work_type}", f"EMPLOYMENT_TYPE: {employment_type}",
        f"SALARY_TEXT: {salary_text}",
        f"CRITERIA: {' | '.join(f'{l}: {criteria_values[i]}' for i, l in enumerate(criteria_labels) if i < len(criteria_values))}",
        f"DESCRIPTION: {description}",
    ])

    return {
        "canonical_id": canonical_id(url),
        "source_url": normalize_url(url),
        "external_url": external_url,
        "company": company or None,
        "title": title or None,
        "location": location,
        "work_type": work_type,
        "salary_min": salary["salary_min"],
        "salary_max": salary["salary_max"],
        "employment_type": employment_type,
        "seniority_level": seniority_level,
        "level": level,
        "responsibilities": parse_description_section(description, RESPONSIBILITIES_PATTERNS),
        "requirements": parse_description_section(description, REQUIREMENTS_PATTERNS),
        "preferred_qualifications": parse_description_section(description, PREFERRED_PATTERNS),
        "description": description or None,
        "raw_content": raw_content,
    }
