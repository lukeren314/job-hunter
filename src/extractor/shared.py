import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


# ─── HTML → plain text ───────────────────────────────────────────────────────

def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"</(div|section|article|h[1-6]|ul|ol)>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&#x27;", "'")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─── URL normalization ───────────────────────────────────────────────────────

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "trk", "trkCampaign", "sc_channel", "sc_campaign", "sc_outcome",
    "refId", "trackingId", "src", "ref",
}


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query).items() if k not in _TRACKING_PARAMS}
        clean = p._replace(query=urlencode(qs, doseq=True), fragment="")
        path = clean.path
        if 'lever.co' in (p.hostname or '') and path.endswith('/apply'):
            path = path[:-len('/apply')]
        clean = clean._replace(path=path)
        return urlunparse(clean).rstrip("/")
    except Exception:
        return url


# ─── Canonical ID ─────────────────────────────────────────────────────────────

def canonical_id(url: str) -> str:
    try:
        u = urlparse(url)
        host = u.hostname or ""

        if "linkedin.com" in host:
            m = re.search(r"/jobs/view/(?:[^?/]*-)?(\d{7,})", url)
            return f"linkedin_{m.group(1)}" if m else f"job_{normalize_url(url)}"

        if "ashbyhq.com" in host:
            m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url, re.I)
            return f"ashby_{m.group(1)}" if m else f"job_{normalize_url(url)}"

        if "greenhouse.io" in host:
            from urllib.parse import parse_qs
            qs = parse_qs(u.query)
            token = qs.get("token", [None])[0]
            job_match = re.search(r"/jobs/(\d+)", url)
            id_ = token or (job_match.group(1) if job_match else None)
            return f"greenhouse_{id_}" if id_ else f"job_{normalize_url(url)}"

        if "lever.co" in host:
            m = re.search(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url, re.I)
            return f"lever_{m.group(1)}" if m else f"job_{normalize_url(url)}"

        if "indeed.com" in host:
            from urllib.parse import parse_qs
            jk = parse_qs(u.query).get("jk", [None])[0]
            return f"indeed_{jk}" if jk else f"job_{normalize_url(url)}"

        if "amazon.jobs" in host:
            m = re.search(r"/jobs/(\d+)/", url)
            return f"amazon_{m.group(1)}" if m else f"job_{normalize_url(url)}"

        if "microsoft.com" in host and re.search(r"/job/\d", url):
            m = re.search(r"/job/(\d+)", url)
            return f"msft_{m.group(1)}" if m else f"job_{normalize_url(url)}"

        if "google.com" in host and re.search(r"/careers/|/about/careers", url):
            m = re.search(r"/results/(\d{10,})", url)
            return f"google_careers_{m.group(1)}" if m else f"job_{normalize_url(url)}"

    except Exception:
        pass
    return f"job_{normalize_url(url)}"


# ─── Line normalization ───────────────────────────────────────────────────────

def normalize_line(line: str) -> str:
    line = re.sub(r"^[^a-zA-Z]+", "", line)
    line = re.sub(r"[''ʼ]", "'", line)
    line = re.sub(r"(?:…|\.{2,})\s*$", "", line)
    line = re.sub(r":+\s*$", "", line)
    return line.strip()


SECTION_HEADER_RE = re.compile(
    r"^(?:about(?:\s+(?:us|the company|the role|the job|this role|the team|you))?|"
    r"the role(?:\s+(?:entails|will be centered on))?|your role|role overview|role|"
    r"overview|position summary|responsibilities|key responsibilities|core responsibilities|"
    r"major responsibilities|roles?\s+(?:&|and)\s+responsibilities|"
    r"responsibilities\s+and\s+duties(?:\s+of\s+the\s+role)?|what you'?ll do|"
    r"what you will do|what you'?ll be doing|what you will be doing|what you'?ll get to do|"
    r"in this role(?:[,\s]+you'?ll)?|on any given day[,\s]+you will|duties|you will|"
    r"requirements?|required(?: qualifications?)?|minimum (?:qualifications?|requirements?)|"
    r"basic qualifications?\b|qualifications?|what we'?re looking for|who we'?re looking for|"
    r"what (?:we are|we'?re) looking for(?: in you)?|"
    r"we'?re (?:excited about you because you have|looking for someone with)|"
    r"we'?d love to hear from you if you have|what you'?ll need|what you need|"
    r"what skills? you'?ll need|what you bring|what you'?ll bring|what you have|"
    r"the skillset you'?ll bring|skills? that (?:accelerate|supercharge) us|"
    r"required (?:competencies?|skills?)|you have|you'?re a fit if|what you'?re like|"
    r"an ideal candidate should have|what it takes to join|what you'?ve done|"
    r"you'?ll bring these qualifications|success criteria|must[- ]have|skills?|experience|"
    r"who you are|preferred(?: (?:qualifications?|requirements?))?|desired(?: qualifications?)?|"
    r"nice[- ]to[- ]have|bonus(?: (?:points?|if you have))?|"
    r"what (?:will|would|sets?) (?:you )?(?:set you |stand out with )?apart|"
    r"what you'?ll stand out with|it would be nice if you have|plus|benefits?|perks?|"
    r"what we offer|compensation|salary|who we are)$",
    re.I,
)


def is_section_header(line: str) -> bool:
    if len(line) > 100:
        return False
    return bool(SECTION_HEADER_RE.match(normalize_line(line)))


# ─── Section patterns ─────────────────────────────────────────────────────────

RESPONSIBILITIES_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^responsibilities$", r"^key responsibilities\b",
        r"^core responsibilities$", r"^major responsibilities$",
        r"^roles?\s+(?:&|and)\s+responsibilities$",
        r"^responsibilities\s+and\s+duties(?:\s+of\s+the\s+role)?$",
        r"^what you'?ll do$", r"^what you will do$",
        r"^what you'?ll be doing$", r"^what you will be doing$",
        r"^what you'?ll get to do$",
        r"^in this role(?:[,\s]+you'?ll)?$",
        r"^the role(?:\s+will be centered on)?$", r"^your role$",
        r"^about the role$", r"^about the job$", r"^about this role$",
        r"^role overview$", r"^role$", r"^the role entails$",
        r"^on any given day[,\s]+you will$",
        r"^you will$", r"^duties$",
    ]
]

REQUIREMENTS_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^requirements?$", r"^required qualifications?\b",
        r"^minimum qualifications?\b", r"^basic qualifications?\b",
        r"^qualifications?$", r"^must[- ]have$", r"^required\b",
        r"^required competencies?$", r"^required skills?$",
        r"^minimum requirements?$",
        r"^what we'?re looking for$", r"^who we'?re looking for$",
        r"^what (?:we are|we'?re) looking for(?: in you)?$",
        r"^we'?re (?:excited about you because you have|looking for someone with)$",
        r"^we'?d love to hear from you if you have$",
        r"^what you'?ll need$", r"^what you need$", r"^what skills? you'?ll need$",
        r"^what you bring$", r"^what you'?ll bring$", r"^what you have$",
        r"^the skillset you'?ll bring$",
        r"^skills? that (?:accelerate|supercharge) us$",
        r"^you have$", r"^you'?re a fit if$", r"^what you'?re like$",
        r"^who you are$", r"^skills?$",
        r"^about you$", r"^an ideal candidate should have$",
        r"^what it takes to join$", r"^what you'?ve done$",
        r"^you'?ll bring these qualifications\b", r"^success criteria$",
    ]
]

PREFERRED_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^preferred(?: qualifications?| requirements?)?$",
        r"^desired(?: qualifications?)?$",
        r"^nice[- ]to[- ]have$", r"^bonus(?: points?| if you have)?$", r"^bonus$",
        r"^what (?:will|would|sets?) (?:you )?(?:set you |stand out with)?apart$",
        r"^what (?:will|would) set you apart$", r"^what sets you apart$",
        r"^what you'?ll stand out with$",
        r"^it would be nice if you have$",
        r"^plus$",
    ]
]


# ─── Parsers ──────────────────────────────────────────────────────────────────

def parse_description_section(description: str, target_patterns: list) -> str | None:
    if not description:
        return None
    lines = [l.strip() for l in description.split("\n")]

    start_idx = -1
    for i, line in enumerate(lines):
        normalized = normalize_line(line)
        if any(p.match(normalized) for p in target_patterns):
            start_idx = i + 1
            break
    if start_idx == -1:
        return None

    content = []
    for line in lines[start_idx:]:
        if content and is_section_header(line):
            break
        if line:
            content.append(line)
    return "\n".join(content).strip() or None


def parse_work_type(
    labeled_texts: list[str],
    description: str = "",
    location: str | None = None,
) -> str | None:
    primary = " ".join(labeled_texts).lower()
    desc = description.lower()
    types = []

    if "remote" in primary or re.search(r"\bremote\b", desc):
        types.append("Remote")
    if "hybrid" in primary or re.search(r"\bhybrid\b", desc):
        types.append("Hybrid")
    if (
        "on-site" in primary or "onsite" in primary
        or "in person" in primary or "in-person" in primary
        or re.search(r"\bon[- ]?site\b", desc)
        or re.search(r"\bin[- ]?person\b", desc)
    ):
        types.append("Onsite")

    # Location fallback only when no work-type signal found
    if not types and location:
        types.append("Onsite")

    return ", ".join(types) if types else None


def parse_employment_type(texts: list[str]) -> str | None:
    combined = " ".join(texts).lower()
    if "contract" in combined or "contractor" in combined:
        return "Contract"
    if "full-time" in combined or "full time" in combined:
        return "Full-time"
    if "part-time" in combined or "part time" in combined:
        return "Part-time"
    return None


def _extract_salary_amounts(text: str) -> dict:
    if not text.strip():
        return {"salary_min": None, "salary_max": None}
    is_hourly = bool(re.search(r"\$[\d,.]+\s*/\s*h(?:r|our)", text, re.I))
    amounts = []
    for m in re.finditer(r"\$([\d,]+(?:\.\d+)?)\s*(K|k)?", text):
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000
        if is_hourly:
            val = round(val * 2080)
        amounts.append(val)
    if not amounts:
        return {"salary_min": None, "salary_max": None}
    return {
        "salary_min": amounts[0],
        "salary_max": amounts[1] if len(amounts) > 1 else None,
    }


def _extract_salary_from_description(desc: str) -> dict:
    if not desc:
        return {"salary_min": None, "salary_max": None}
    is_hourly = bool(re.search(r"\$[\d,.]+\s*/\s*h(?:r|our)", desc, re.I))

    for m in re.finditer(
        r"\$([\d,]+(?:\.\d+)?)\s*(K|k)?\s*[-–to]+\s*\$([\d,]+(?:\.\d+)?)\s*(K|k)?", desc
    ):
        min_val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        max_val = float(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1)
        if is_hourly:
            min_val, max_val = round(min_val * 2080), round(max_val * 2080)
        if 40000 <= min_val and max_val <= 600000 and max_val >= min_val:
            return {"salary_min": int(min_val), "salary_max": int(max_val)}

    m = re.search(
        r"(?:salary|compensation|base pay|total pay)[^$\n]{0,40}\$([\d,]+(?:\.\d+)?)\s*(K|k)?",
        desc,
        re.I,
    )
    if m:
        val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        if is_hourly:
            val = round(val * 2080)
        if 40000 <= val <= 600000:
            return {"salary_min": int(val), "salary_max": None}

    return {"salary_min": None, "salary_max": None}


def parse_salary(priority_texts: list[str], description: str = "") -> dict:
    result = _extract_salary_amounts(" ".join(priority_texts))
    if result["salary_min"] is not None:
        return result
    return _extract_salary_from_description(description)


def parse_seniority_level(
    criteria_labels: list[str], criteria_values: list[str]
) -> str | None:
    for i, label in enumerate(criteria_labels):
        if re.search(r"seniority level", label, re.I):
            raw = (criteria_values[i] if i < len(criteria_values) else "").lower()
            mapping = {
                "internship": "Internship",
                "entry level": "Entry",
                "associate": "Associate",
                "mid-senior level": "Mid-Senior",
                "senior level": "Senior",
                "director": "Director",
                "executive": "Executive",
                "not applicable": None,
            }
            return mapping.get(raw, criteria_values[i] if i < len(criteria_values) else None)
    return None


# ─── Level extraction (new) ───────────────────────────────────────────────────

_LEVEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bintern(?:ship)?\b", re.I), "intern"),
    (re.compile(r"\bjunior\b|\bjr\.?\b", re.I), "junior"),
    (re.compile(r"\bentry[\s-]?level\b", re.I), "entry"),
    (re.compile(r"\bassociate\b", re.I), "associate"),
    (re.compile(r"\bmid[\s-]?senior\b", re.I), "mid-senior"),
    (re.compile(r"\bmid[\s-]?level\b", re.I), "mid"),
    (re.compile(r"\bstaff\b", re.I), "staff"),
    (re.compile(r"\bprincipal\b", re.I), "principal"),
    (re.compile(r"\bdirector\b", re.I), "director"),
    (re.compile(r"\blead\b", re.I), "lead"),
    (re.compile(r"\bsenior\b|\bsr\.?\b", re.I), "senior"),
    (re.compile(r"\bvp\b|\bvice president\b", re.I), "vp"),
    (re.compile(r"\bmid\b", re.I), "mid"),
]


def extract_level(
    title: str,
    seniority_level: str | None = None,
    description: str | None = None,
) -> str | None:
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(title or ""):
            return level
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(seniority_level or ""):
            return level
    desc_head = (description or "")[:500]
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(desc_head):
            return level
    return None
