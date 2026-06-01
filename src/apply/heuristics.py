"""
Heuristic field matching — ported from apply_agent.js getKnownAnswer().
"""
import re


def normalize_text(value: str = "") -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


METRO_ALIASES: dict[str, list[str]] = {
    "san francisco": ["san francisco", "bay area", "sf bay", "silicon valley", "san jose", "east bay", "greater san francisco"],
    "new york": ["new york", "nyc", "new york city", "manhattan", "brooklyn", "greater new york"],
    "los angeles": ["los angeles", "la ", "l.a.", "socal", "southern california"],
    "seattle": ["seattle", "puget sound", "bellevue", "redmond"],
    "chicago": ["chicago", "chicagoland"],
    "boston": ["boston", "greater boston"],
    "austin": ["austin"],
    "denver": ["denver", "boulder"],
    "miami": ["miami", "south florida"],
    "portland": ["portland"],
    "atlanta": ["atlanta"],
    "dallas": ["dallas", "dfw", "fort worth"],
    "houston": ["houston"],
    "washington": ["washington dc", "washington, dc", "dc metro", "northern virginia", "nova"],
    "beijing": ["beijing", "peking"],
    "shanghai": ["shanghai"],
    "guangzhou": ["guangzhou", "canton"],
    "shenzhen": ["shenzhen"],
    "singapore": ["singapore", "one-north", "one north"],
    "tokyo": ["tokyo"],
    "london": ["london", "greater london"],
    "berlin": ["berlin"],
    "toronto": ["toronto"],
    "vancouver": ["vancouver"],
}

_DEGREE_EXPANSIONS = {
    "b.s.": "bachelor", "bs": "bachelor", "b.a.": "bachelor", "ba": "bachelor",
    "b.e.": "bachelor", "bsc": "bachelor", "beng": "bachelor",
    "m.s.": "master", "ms": "master", "m.a.": "master", "ma": "master",
    "msc": "master", "mba": "master", "m.b.a.": "master", "meng": "master",
    "ph.d.": "doctoral", "phd": "doctoral", "ph.d": "doctoral",
    "j.d.": "professional", "jd": "professional",
}


def is_user_in_area(label: str, user_location: str) -> bool | None:
    user_loc = normalize_text(user_location or "")
    for aliases in METRO_ALIASES.values():
        if not any(a in label for a in aliases):
            continue
        return any(a in user_loc for a in aliases)
    return None


def get_known_answer(field: dict, personal_info: dict) -> str | None:
    label = normalize_text(" ".join(
        str(v) for v in [field.get("label"), field.get("name"), field.get("id"),
                          field.get("placeholder"), field.get("ariaLabel")] if v
    ))
    if not label:
        return None

    own_attrs = normalize_text(" ".join(
        str(v) for v in [field.get("name"), field.get("id"),
                          field.get("ariaLabel"), field.get("placeholder")] if v
    ))

    is_choice = field.get("inputType") in ("checkbox", "radio")
    is_select = field.get("inputType") == "select-one"
    is_binary = is_choice or is_select  # any field that takes a discrete answer

    # File upload
    if field.get("inputType") == "file" and re.search(r"resume|cv", label):
        return "__UPLOAD_RESUME__"
    if field.get("inputType") == "file" and re.search(r"cover.?letter", label):
        return "__UPLOAD_COVER_LETTER__"

    # Work auth / sponsorship
    if is_binary and re.search(r"require.*sponsor|need.*sponsor|visa.*sponsor|sponsor.*visa|h[-–]?1b", label):
        return "no"
    if is_binary and re.search(r"located in the us|based in the us|eligible to work|legally authorized|legally work|can you work|right to work|work in the u\.?s\.?|work in the united states", label):
        return "yes"
    if is_binary and re.search(r"\bitar\b|export.*regulat|obtain.*authorization.*work|us person.*itar|itar.*us person", label, re.I):
        return "yes"
    if is_binary and re.search(r"\bu\.?s\.?\s*citizen|united states.{0,20}citizen|national of the united states", label, re.I):
        return "yes" if re.search(r"united states|us citizen", personal_info.get("citizenship") or "", re.I) else "no"
    if is_binary and re.search(r"18 or older|at least 18|18\+", label):
        return "yes"
    # Onsite availability — check city against user location
    if is_binary and re.search(r"able to work (?:on.?site|in.?person|in the office)", label, re.I):
        city_match = re.search(r"in ([A-Za-z\s]+),?\s*[A-Z]{2}", label)
        city = city_match.group(1).strip() if city_match else ""
        in_area = is_user_in_area(city.lower(), personal_info.get("location") or "") if city else None
        if in_area is not None:
            return "yes" if in_area else "no"
        return "yes" if re.match(r"^y", str(personal_info.get("willing_to_relocate") or "No"), re.I) else "no"
    # Company-specific history/conflict questions — safe defaults
    if is_binary and re.search(r"(?:ever )?(?:been )?employed by|previously worked (?:at|for)", label, re.I):
        return "no"
    if is_binary and re.search(r"conflict of interest", label, re.I):
        return "no"
    if is_binary and re.search(r"willing.*relocat|open.*relocat|relocat.*willing|relocat.*open", label):
        return "yes" if re.match(r"^y", str(personal_info.get("willing_to_relocate") or "No"), re.I) else "no"
    if is_binary and re.search(r"not open.*(?:other|location)|i(?:'m| am) not open|closed to other", label, re.I):
        return "yes" if re.match(r"^n", str(personal_info.get("willing_to_relocate") or "No"), re.I) else "no"
    if is_binary and re.search(r"based in|located in|do you (?:currently )?(?:live|reside|work) in", label):
        in_area = is_user_in_area(label, personal_info.get("location") or "")
        if in_area is not None:
            return "yes" if in_area else "no"
    if is_binary:
        in_area = is_user_in_area(label, personal_info.get("location") or "")
        if in_area is not None:
            if in_area:
                return "yes"
            return "yes" if re.match(r"^y", str(personal_info.get("willing_to_relocate") or "No"), re.I) else "no"

    # How did you hear — before name check (label may contain "their name" and "where did you hear")
    if not is_choice and re.search(r"how did you (?:hear|find|learn|discover|come to learn|come to know)|where did you (?:hear|find)|referral source", label, re.I):
        return personal_info.get("how_did_you_hear") or personal_info.get("application_source") or None

    # Name
    if re.search(r"first name|given name|preferred first", label):
        return personal_info.get("first_name") or (personal_info.get("full_name") or "").split()[0] or None
    if re.search(r"last name|family name|surname", label) and not re.search(r"first.{0,15}last|last.{0,15}first", label):
        parts = (personal_info.get("full_name") or "").split()
        return personal_info.get("last_name") or (" ".join(parts[1:]) if len(parts) > 1 else None)
    if re.search(r"full name|legal name|preferred name|\bname\b", label) and not re.search(r"company|employer|reference|school|university|college", label):
        return personal_info.get("full_name") or None

    # Contact
    if re.search(r"\bemail\b|e-mail", label) and not re.search(r"company|employer", label):
        return personal_info.get("email") or None
    if re.search(r"country", own_attrs) and re.search(r"phone", label):
        return personal_info.get("country") or "United States"
    if re.search(r"phone.*country|country\s*code|calling\s*code|dial.*code", own_attrs):
        return personal_info.get("country") or "United States"
    if re.search(r"phone|mobile|telephone|cell", label) and not re.search(r"country", own_attrs):
        return personal_info.get("phone") or None

    # Online profiles
    if not is_choice and re.search(r"\blinkedin\b", label) and not re.search(r"resume|reflect|know about|not reflected|tell us|describe|hear about", label, re.I):
        return personal_info.get("linkedin_url") or None
    if not is_choice and re.search(r"github", label):
        return personal_info.get("github_url") or None
    if not is_choice and re.search(r"twitter|x\.com", label):
        return personal_info.get("twitter_url") or None
    if not is_choice and re.search(r"portfolio|personal\s*site|personal\s*web", label):
        return personal_info.get("portfolio_url") or personal_info.get("github_url") or None
    if not is_choice and re.search(r"\bwebsite\b|\burl\b", label) and not re.search(r"company|employer", label):
        return personal_info.get("portfolio_url") or personal_info.get("github_url") or personal_info.get("linkedin_url") or None

    # Education
    edu_raw = personal_info.get("education") or {}
    edu = edu_raw[0] if isinstance(edu_raw, list) else edu_raw

    if not is_choice and re.search(r"university|college|school|institution", label) and not re.search(r"high school|secondary|employer|company|current|previous", label):
        return edu.get("school_full") or edu.get("school") or None
    if re.search(r"highest.*(?:level|degree)|level.*education|education.*level", label, re.I) and not is_choice:
        return edu.get("degree") or edu.get("degree_short") or None
    if re.search(r"\bdegree\b|\bmajor\b|field of study|discipline", label) and not re.search(r"how many|number of companies|life activit|activities|responsibilities|accomplishment", label, re.I):
        return edu.get("degree") or edu.get("degree_short") or None
    if is_choice and re.search(r"undergraduate|bachelor|graduate|master|doctoral|ph\.?d", label) and not re.search(r"concentration|minor|certificate|honor|award|program", label):
        deg = normalize_text(edu.get("degree") or "")
        if re.search(r"bachelor|undergrad", deg):
            return "Undergraduate"
        if re.search(r"master|mba|msc|meng", deg):
            return "Graduate"
        if re.search(r"doctor|ph\.?d", deg):
            return "Doctoral"
        return None
    if re.search(r"confirm.*graduation|graduation.*will be|graduation.*(?:fall|spring|summer|winter)", label, re.I):
        years = [int(m) for m in re.findall(r"\b(20\d{2})\b", label)]
        if years and edu.get("graduation_year"):
            return "yes" if int(edu["graduation_year"]) in years else "no"
    if re.search(r"end\s*(date\s*)?year|to\s*year|\bgrad(uation)?\s*year\b|class\s*of|expected\s*grad", label):
        return edu.get("graduation_year") or None
    if re.search(r"start\s*(date\s*)?year|from\s*year|begin.*year", label):
        if edu.get("start_year"):
            return edu["start_year"]
        grad_yr = int(edu.get("graduation_year") or 0)
        return str(grad_yr - 4) if grad_yr > 2000 else None
    if re.search(r"end\s*(date\s*)?month|to\s*month|grad.*month", label):
        date_str = edu.get("graduation_date") or ""
        m = re.match(r"(January|February|March|April|May|June|July|August|September|October|November|December)", date_str, re.I)
        return m.group(0) if m else None
    if re.search(r"start\s*(date\s*)?month|from\s*month|begin.*month", label):
        return "September"
    if re.search(r"^graduation date|^grad date|\bgraduation date\b$|\bgrad date\b$", label):
        return edu.get("graduation_date") or edu.get("graduation_year") or None
    if re.search(r"\bgpa\b", label):
        return edu.get("gpa") or None

    # Employment
    if re.search(r"current company|current employer|employer", label) and not re.search(r"school|university|any employer|authorized|eligible|work for|clearance|permit", label, re.I):
        return personal_info.get("current_company") or None
    if re.search(r"current title|job title|current role|current position", label):
        return personal_info.get("current_title") or None
    if re.search(r"years.*experience|experience.*years", label):
        return personal_info.get("years_experience") or None

    # Authorization text fields
    if re.search(r"authorized|work authorization|eligible to work|legally authorized|legally work|can you work", label) and not is_choice:
        return personal_info.get("work_authorization") or None
    if re.search(r"\bsponsorship?\b|\bvisa\b", label) and not is_choice:
        return personal_info.get("sponsorship_required") or None
    if re.search(r"citizenship|citizen\s*of|country\s*of\s*citizenship", label) and not is_choice:
        return personal_info.get("citizenship") or personal_info.get("country") or "United States"

    # Location
    if re.search(r"\bcountry\b|\bnationality\b", label) and not re.search(r"phone", own_attrs):
        return personal_info.get("country") or "United States"
    if re.search(r"\blocation\b|\bcity\b|\baddress\b", label) and not re.search(r"relocat|willing", label):
        return personal_info.get("location") or None
    if re.search(r"\bstate\b", label) and not re.search(r"united states|country|department of state|itar|export.*regulat|authorization|government", label, re.I) and len(label) < 120:
        loc = personal_info.get("location") or ""
        return personal_info.get("state") or (loc.split(",")[-1].strip() if "," in loc else None)
    if re.search(r"\bzip\b|\bpostal", label):
        return personal_info.get("zip_code") or None

    # Compensation / timeline
    if re.search(r"salary|compensation|pay expectation", label):
        return personal_info.get("desired_salary") or None
    if re.search(r"start date|available to start|when can you start|notice period|earliest.*start|available.*start", label):
        return personal_info.get("available_start_date") or None
    if re.search(r"onsite.*availab|availab.*onsite|on.?site.*availab", label, re.I):
        return personal_info.get("onsite_availability") or None

    # Employment type
    if re.search(r"employment type|job type|work type|position type|type of (?:work|employment|role|position)|full.time or part.time|full-time or part-time", label):
        return personal_info.get("commitment_type") or "Full-time"
    if is_choice and re.search(r"\bfull.time\b|\bpart.time\b|\binternship\b|\bcontract\b|\btemporary\b|\bboth\b", label) and not re.search(r"description|benefit|compensation|offer|package|eligible|basis|permanent|perm\b|\bexperience\b|\bindustry\b", label):
        return personal_info.get("commitment_type") or "Full-time"

    # Misc
    if re.search(r"pronoun", label):
        if is_choice:
            option_text0 = normalize_text(label.split("|")[0])
            user_pronouns = normalize_text(personal_info.get("pronouns") or "")
            if not user_pronouns or re.search(r"prefer not|decline", user_pronouns):
                return "yes" if re.search(r"prefer not|decline", option_text0) else "no"
            # Match first pronoun word (he/she/they/etc.)
            first_word = user_pronouns.split("/")[0].split()[0] if user_pronouns else ""
            return "yes" if first_word and first_word in option_text0 else "no"
        return personal_info.get("pronouns") or None

    if is_choice:
        # Use only the first token (actual option text) to avoid false matches from sibling options
        option_text = normalize_text(label.split("|")[0])
        has_source_context = bool(re.search(r"how did you hear|where did you hear|referral source|where did you find|how did you find|how did you learn", label))
        unambiguous_source = bool(re.search(r"\bindeed\b|\bhandshake\b|\bziprecruiter\b|\bglassdoor\b|\bemployee\s*referral\b|referral\s*from\s*(?:a\s*)?(?:friend|colleague|professor)|\bprofessional\s*organization\b|\bai\s*search\s*engine\b|\bperplexity\b|other\s*job\s*(?:website|board|site)|youtube.*facebook|facebook.*instagram|\blinkedin\b", option_text, re.I))
        if has_source_context or unambiguous_source:
            src = normalize_text(personal_info.get("how_did_you_hear") or personal_info.get("application_source") or "")
            if not src:
                return None
            if re.search(r"\blinkedin\b", option_text):
                return "yes" if "linkedin" in src else "no"
            if re.search(r"\bindeed\b", option_text):
                return "yes" if "indeed" in src else "no"
            if re.search(r"\bhandshake\b", option_text):
                return "yes" if "handshake" in src else "no"
            if re.search(r"\bziprecruiter\b", option_text):
                return "yes" if "ziprecruiter" in src or "zip" in src else "no"
            if re.search(r"\bglassdoor\b", option_text):
                return "yes" if "glassdoor" in src else "no"
            if re.search(r"\bemployee\s*referral\b", option_text):
                return "yes" if "employee referral" in src else "no"
            if re.search(r"referral\s*from\s*(?:a\s*)?(?:friend|colleague|professor)", option_text, re.I):
                return "yes" if ("referral" in src or "friend" in src or "colleague" in src) and "employee" not in src else "no"
            if re.search(r"\bprofessional\s*organization\b", option_text):
                return "yes" if "professional" in src else "no"
            if re.search(r"\bai\s*search\s*engine\b|\bperplexity\b", option_text):
                return "yes" if "ai search" in src or "perplexity" in src else "no"
            if re.search(r"other\s*job\s*(?:website|board|site)", option_text, re.I):
                return "yes" if "other" in src else "no"
            if re.search(r"youtube|facebook|instagram", option_text):
                return "yes" if any(s in src for s in ["facebook", "instagram", "youtube"]) else "no"
            if has_source_context:
                return "no"
            # Sibling options revealed this is a referral group — default not selected
            return "no"

    if is_choice and re.search(r"currently a student|are you a student|enrolled.*student", label):
        return "no" if personal_info.get("current_company") else None
    if re.search(r"remote.*preference|preferred.*work.*arrangement|on.?site.*remote|work.*style|hybrid|remote or on", label):
        return personal_info.get("remote_preference") or None
    if re.search(r"cover letter", label) and personal_info.get("cover_letter_template"):
        return personal_info.get("cover_letter_template") or None

    # EEOC / DEI — select, text, and checkbox/radio formats
    if re.search(r"hispanic|latino", label):
        if not is_choice:
            return personal_info.get("hispanic_latino") or "Decline to self-identify"
        # Checkbox/radio: match specific option (use opt_text only, not sibling context)
        user_hispanic = normalize_text(personal_info.get("hispanic_latino") or "no")
        opt_text_h = normalize_text(label.split("|")[0])
        if re.search(r"not hispanic|not latino|not of hispanic", opt_text_h, re.I):
            return "yes" if re.search(r"\bno\b|not", user_hispanic) else "no"
        if re.search(r"decline|prefer not", opt_text_h, re.I):
            return "yes" if re.search(r"decline|prefer not", user_hispanic) else "no"
        # This option IS "Hispanic or Latino"
        return "yes" if re.search(r"^yes\b|^hispanic\b|^latino\b", user_hispanic) else "no"
    _RACE_ETHNICITY_TERMS = re.compile(
        r"\brace\b|\bethnicity\b|white\s*/\s*caucasian|hispanic or latino|black or african|"
        r"native hawaiian|pacific islander|indigenous|first nations|native american|alaska native|"
        r"asian\b|middle eastern|north african|surveysresponses\[",
        re.I,
    )
    if _RACE_ETHNICITY_TERMS.search(label):
        if not is_choice:
            return personal_info.get("race_ethnicity") or "Decline to self-identify"
        # Checkbox: check if this option matches user's race
        user_race = normalize_text(personal_info.get("race_ethnicity") or "")
        if not user_race or re.search(r"decline|prefer not", user_race):
            return "no"
        opt_text = normalize_text(label.split("|")[0])
        return "yes" if any(w in opt_text for w in user_race.split() if len(w) > 3) else "no"
    if re.search(r"veteran", label):
        if not is_choice:
            return personal_info.get("veteran_status") or "I am not a protected veteran"
        user_vet = normalize_text(personal_info.get("veteran_status") or "not a protected veteran")
        opt_text = normalize_text(label.split("|")[0])
        if re.search(r"not a.*veteran|not a protected", opt_text):
            return "yes" if re.search(r"not a.*veteran|not a protected", user_vet) else "no"
        if re.search(r"decline|prefer not", opt_text):
            return "yes" if re.search(r"decline|prefer not", user_vet) else "no"
        return "no"
    if re.search(r"disability", label):
        if not is_choice:
            return personal_info.get("disability_status") or "No, I do not have a disability"
        user_dis = normalize_text(personal_info.get("disability_status") or "no, i do not")
        opt_text = normalize_text(label.split("|")[0])
        if re.search(r"^no,?|do not have", opt_text):
            return "yes" if re.search(r"^no,?|do not have", user_dis) else "no"
        if re.search(r"decline|prefer not", opt_text):
            return "yes" if re.search(r"decline|prefer not", user_dis) else "no"
        return "no"
    if re.search(r"\bgender\b", label):
        if not is_choice:
            return personal_info.get("gender") or "Prefer not to disclose"
        user_gender = normalize_text(personal_info.get("gender") or "prefer not to disclose")
        opt_text = normalize_text(label.split("|")[0])
        # Handle "prefer not to disclose" ↔ "decline to self-identify" etc.
        if re.search(r"prefer not|decline|not disclose|self-identify", user_gender):
            return "yes" if re.search(r"prefer not|decline|not disclose|self-identify", opt_text) else "no"
        return "yes" if any(w in opt_text for w in user_gender.split() if len(w) > 3) else "no"
    if re.search(r"sexual orientation|transgender", label):
        # Prefer-not-to-answer for these sensitive fields
        opt_text = normalize_text(label.split("|")[0])
        return "yes" if re.search(r"prefer not|decline", opt_text) else "no"
    # US work authorization multi-option dropdown (can work for any employer / OPT / H1B etc.)
    if re.search(r"u\.?s\.?\s*work\s*auth|authorization\s*status", label):
        if not is_choice:
            return personal_info.get("work_authorization") or None
        opt_text = normalize_text(label.split("|")[0])
        wa = normalize_text(personal_info.get("work_authorization") or "")
        if re.search(r"any employer|authorized|citizen|green card", opt_text) and re.search(r"authorized|citizen", wa):
            return "yes"
        if re.search(r"h.?1|opt|stem opt|h4|ead|sponsorship|seeking", opt_text):
            return "no"
        if re.search(r"prefer not|decline", opt_text):
            return "no"
        return None

    return None


def best_select_option(options: list[dict], suggested_value: str) -> str | None:
    """Fuzzy-match suggested_value against select option texts."""
    if not options or not suggested_value:
        return None

    sv = normalize_text(suggested_value)

    # Expand degree abbreviations
    for abbr, expansion in _DEGREE_EXPANSIONS.items():
        sv = re.sub(r"\b" + re.escape(abbr) + r"\b", expansion, sv)

    sv_words = set(w for w in sv.split() if len(w) >= 2)

    best_text = None
    best_score = 0

    for opt in options:
        opt_text = opt.get("text") or opt.get("value") or ""
        opt_norm = normalize_text(opt_text)

        # Expand degree abbreviations in option text too
        for abbr, expansion in _DEGREE_EXPANSIONS.items():
            opt_norm = re.sub(r"\b" + re.escape(abbr) + r"\b", expansion, opt_norm)

        # Exact match
        if sv == opt_norm:
            return opt_text

        # Keyword overlap
        opt_words = set(w for w in opt_norm.split() if len(w) >= 2)
        overlap = len(sv_words & opt_words)
        if overlap > best_score:
            best_score = overlap
            best_text = opt_text

    return best_text if best_score >= 1 else None


def annotate_snapshot(snapshot: dict, personal_info: dict) -> dict:
    """Add suggestedValue to each interactable."""
    for item in snapshot.get("interactables") or []:
        answer = get_known_answer(item, personal_info)
        if answer is not None:
            item["suggestedValue"] = answer
    return snapshot


def compact_snapshot(snapshot: dict) -> dict:
    """Remove optional DEI fields, already-checked options, truncate options."""
    EEOC_LABELS = re.compile(r"race|ethnicity|gender|veteran|disability|hispanic|latino", re.I)
    items = snapshot.get("interactables") or []
    compacted = []
    for item in items:
        label = item.get("label") or ""
        # Skip optional EEOC
        if EEOC_LABELS.search(label) and not item.get("required"):
            continue
        # Skip already-selected radio options
        if item.get("inputType") == "radio" and item.get("checked") and not item.get("required"):
            continue
        # Truncate options
        if item.get("options") and len(item["options"]) > 25:
            item = {**item, "options": item["options"][:25]}
        compacted.append(item)
    return {**snapshot, "interactables": compacted}
