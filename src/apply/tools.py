"""
Playwright browser tools for apply agent.
JS evaluation blocks ported verbatim from agent_tools.js.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
RESUME_PATH = ROOT / "config" / "resume.pdf"
_LINKEDIN_SESSION = ROOT / "config" / "linkedin_session.json"


def load_linkedin_cookies() -> list[dict]:
    """Load saved LinkedIn session cookies if file exists."""
    if _LINKEDIN_SESSION.exists():
        try:
            data = json.loads(_LINKEDIN_SESSION.read_text())
            cookies = data.get("cookies", data) if isinstance(data, dict) else data
            return [c for c in cookies if isinstance(c, dict)]
        except Exception:
            pass
    return []

# ── JS: page content extraction (verbatim from agent_tools.js getPageContent) ─

_GET_PAGE_CONTENT_JS = """() => {
    let nextRef = 1;
    const existingRefs = Array.from(document.querySelectorAll('[data-agent-ref]'))
      .map(el => Number((el.getAttribute('data-agent-ref') || '').replace('el-', '')))
      .filter(Number.isFinite);
    if (existingRefs.length) nextRef = Math.max(...existingRefs) + 1;

    const isVisible = el => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        rect.width > 0 &&
        rect.height > 0 &&
        !el.disabled &&
        el.getAttribute('aria-hidden') !== 'true';
    };

    const textOf = el => (el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();

    const getRef = el => {
      if (!el.getAttribute('data-agent-ref')) {
        el.setAttribute('data-agent-ref', `el-${nextRef++}`);
      }
      return el.getAttribute('data-agent-ref');
    };

    const labelFor = el => {
      const pieces = [];
      if (el.id) {
        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (label) pieces.push(textOf(label));
      }
      const wrappingLabel = el.closest('label');
      if (wrappingLabel) pieces.push(textOf(wrappingLabel));
      const optionContainer = el.closest('[class*="option"], [role="radio"], [role="checkbox"]');
      if (optionContainer) pieces.push(textOf(optionContainer));
      const describedBy = (el.getAttribute('aria-describedby') || '').split(/\\s+/).filter(Boolean);
      for (const id of describedBy) {
        const described = document.getElementById(id);
        if (described) pieces.push(textOf(described));
      }
      const fieldContainer = el.closest('fieldset, [data-qa], [data-testid], .field, .form-field, .application-field, .ashby-application-form-field, .job-application-question');
      if (fieldContainer) {
        const heading = fieldContainer.querySelector('legend, label, [class*="label"], [class*="question"]');
        if (heading) pieces.push(textOf(heading));
        if (fieldContainer.tagName.toLowerCase() === 'fieldset') {
          pieces.push(textOf(fieldContainer));
        }
      }
      // Lever custom questions: question text lives in li.application-question > div (first child)
      const leverCard = el.closest('li.application-question, .custom-question');
      if (leverCard) {
        const qDiv = leverCard.querySelector(':scope > div:first-child');
        if (qDiv) pieces.push(textOf(qDiv));
      }
      pieces.push(el.getAttribute('aria-label'), el.placeholder, el.name, el.id);
      return [...new Set(pieces.filter(Boolean))].join(' | ');
    };

    const optionData = el => {
      if (el.tagName.toLowerCase() === 'select') {
        return Array.from(el.options).map(option => ({
          text: textOf(option),
          value: option.value,
          selected: option.selected
        }));
      }
      if (el.type === 'radio') {
        const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`));
        return group.map(input => ({
          text: labelFor(input),
          value: input.value,
          selected: input.checked,
          selector: `[data-agent-ref="${getRef(input)}"]`
        }));
      }
      return undefined;
    };

    const interactables = [];
    document.querySelectorAll('input, select, textarea').forEach(el => {
      const tag = el.tagName.toLowerCase();
      const inputType = (el.type || tag).toLowerCase();
      if (inputType === 'hidden' || !isVisible(el)) return;

      const ref = getRef(el);

      interactables.push({
        type: tag === 'select' ? 'select' : tag === 'textarea' ? 'textarea' : 'input',
        ref,
        selector: `[data-agent-ref="${ref}"]`,
        tag,
        inputType,
        label: labelFor(el) || 'Unknown field',
        name: el.name || '',
        id: el.id || '',
        placeholder: el.placeholder || '',
        ariaLabel: el.getAttribute('aria-label') || '',
        required: Boolean(el.required || el.getAttribute('aria-required') === 'true'),
        value: inputType === 'password' ? '[redacted]' : el.value,
        checked: Boolean(el.checked),
        options: optionData(el)
      });
    });

    document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"]').forEach(el => {
      if (!isVisible(el)) return;
      const text = textOf(el) || el.value || el.getAttribute('aria-label') || '';
      if (!text || text.length > 50) return;
      const tag = el.tagName.toLowerCase();
      const inputType = (el.getAttribute('type') || '').toLowerCase();
      const isLikelyButton =
        tag === 'button' ||
        tag === 'input' ||
        el.getAttribute('role') === 'button' ||
        el.classList.contains('button') ||
        el.classList.contains('btn') ||
        /apply|submit|continue|next|start|review|save|upload/i.test(text);

      if (isLikelyButton) {
        const ref = getRef(el);
        interactables.push({
          type: tag === 'a' ? 'link' : 'button',
          ref,
          selector: `[data-agent-ref="${ref}"]`,
          label: labelFor(el),
          text,
          tag,
          inputType,
          id: el.id || '',
          className: typeof el.className === 'string' ? el.className : '',
          ariaLabel: el.getAttribute('aria-label') || '',
          href: tag === 'a' ? el.href : '',
          isTerminalSubmit: /^(submit|send application|submit application|complete application|final submit)$/i.test(text) || /^apply$/i.test(text)
        });
      }
    });

    return {
      url: window.location.href,
      title: document.title,
      interactables: interactables.slice(0, 120),
      summary: document.body.innerText.replace(/\\s+/g, ' ').trim().substring(0, 2500)
    };
}"""

_TRY_CLICK_DROPDOWN_JS = """(value) => {
    const DROPDOWN_ITEM_SELECTORS = [
      '[role="listbox"] [role="option"]',
      '[role="listbox"] li',
      '[role="option"]',
      '.select2-results__option',
      '.chosen-results li',
      '[class*="autocomplete"] [class*="option"]',
      '[class*="autocomplete"] li',
      '[class*="dropdown"] [class*="item"]:not([class*="button"])',
      '[class*="suggestion"]',
      '[class*="typeahead"] li',
      '[id*="-listbox"] [role="option"]',
      '[id*="react-select"] [role="option"]',
    ];
    const normalize = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const valNorm = normalize(value);
    const valWords = valNorm.split(/\\W+/).filter(w => w.length > 2);

    for (const sel of DROPDOWN_ITEM_SELECTORS) {
      const options = Array.from(document.querySelectorAll(sel)).filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
      if (!options.length) continue;
      const scored = options.map((el, i) => {
        const tn = normalize(el.innerText || el.textContent || '');
        const wordScore = valWords.filter(w => tn.includes(w)).length;
        const containScore = tn.includes(valNorm) ? 10 : valNorm.includes(tn) ? 5 : 0;
        return { el, score: wordScore + containScore };
      }).sort((a, b) => b.score - a.score);
      const best = scored[0];
      if (best && best.score > 0) {
        best.el.click();
        return true;
      }
      return false;
    }
    return false;
}"""

_ATS_PATTERNS_RE = re.compile(
    r"greenhouse\.io|lever\.co|workday\.com|ashbyhq\.com|myworkdayjobs\.com"
    r"|icims\.com|breezy\.hr|recruitee\.com|smartrecruiters\.com|taleo\.net"
    r"|bamboohr\.com|jobvite\.com|apply\.|careers\.",
    re.I,
)
_SKIP_PATTERNS_RE = re.compile(
    r"recaptcha|captcha|analytics|tracking|pixel|tag|gtm|ads|doubleclick"
    r"|facebook\.com|twitter\.com|youtube\.com|maps\.google|googleapis\.com/static|content\.googleapis",
    re.I,
)


def _score_match(candidate: str, query: str) -> int:
    haystack = re.sub(r"\s+", " ", str(candidate or "")).strip().lower()
    needle = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    if not haystack or not needle:
        return 0
    if haystack == needle:
        return 100
    if needle in haystack:
        return 80
    if haystack in needle:
        return 65
    words = re.split(r"\W+", needle)
    words = [w for w in words if w]
    if not words:
        return 0
    matched = sum(1 for w in words if w in haystack)
    return round((matched / len(words)) * 60)


async def get_page_content(page) -> dict:
    await page.wait_for_load_state("domcontentloaded")
    try:
        await page.wait_for_timeout(500)
    except Exception:
        pass

    result = await page.evaluate(_GET_PAGE_CONTENT_JS)

    # Iframe detection when no interactables found
    if not result.get("interactables"):
        found_iframe_url = None
        frames = page.frames
        main_frame = page.main_frame

        for frame in frames:
            if frame == main_frame:
                continue
            frame_url = frame.url
            if not frame_url or frame_url == "about:blank":
                continue
            if _SKIP_PATTERNS_RE.search(frame_url):
                continue
            if _ATS_PATTERNS_RE.search(frame_url):
                found_iframe_url = frame_url
                break

        if not found_iframe_url:
            for frame in frames:
                if frame == main_frame:
                    continue
                frame_url = frame.url
                if not frame_url or frame_url == "about:blank":
                    continue
                if _SKIP_PATTERNS_RE.search(frame_url):
                    continue
                try:
                    frame_result = await frame.evaluate(
                        "() => ({ count: document.querySelectorAll('input:not([type=hidden]), select, textarea').length })"
                    )
                    if frame_result.get("count", 0) > 0:
                        found_iframe_url = frame_url
                        break
                except Exception:
                    pass

        if found_iframe_url:
            result["iframeUrl"] = found_iframe_url
            result["iframeHint"] = (
                f"Application form is inside an iframe at {found_iframe_url}. "
                f"Navigate directly to that URL to interact with the form."
            )

    return result


async def fill_field(page, selector: str, value: str) -> None:
    print(f"Filling {selector} with {value}")
    control = await _find_control(page, selector)
    tag_name = await control.evaluate("el => el.tagName.toLowerCase()")
    input_type = await control.evaluate("el => (el.type || '').toLowerCase()")

    if tag_name == "select":
        result = None
        try:
            result = await control.select_option(label=value)
        except Exception:
            pass
        if not result:
            try:
                result = await control.select_option(value=value)
            except Exception:
                pass
        if not result:
            options = await control.evaluate(
                "sel => Array.from(sel.options).map(o => ({ text: o.text.trim(), value: o.value }))"
            )
            meaningful = [o for o in options if o["value"] != ""]
            val_norm = value.lower()
            val_words = [w for w in re.split(r"\W+", val_norm) if len(w) > 3]
            scored = []
            for o in meaningful:
                ot = o["text"].lower()
                word_score = sum(1 for w in val_words if w in ot)
                contain_score = 5 if val_norm in ot or ot in val_norm else 0
                if word_score + contain_score > 0:
                    scored.append((word_score + contain_score, o))
            scored.sort(reverse=True)
            if scored:
                await control.select_option(value=scored[0][1]["value"])
        return

    if input_type == "checkbox":
        desired = not re.match(r"^(false|no|unchecked|0)$", str(value).strip(), re.I)
        if desired:
            await control.check()
        else:
            await control.uncheck()
        return

    if input_type == "radio":
        group_name = await control.get_attribute("name") or ""
        if not group_name:
            await control.check()
            return
        snapshot = await get_page_content(page)
        radio_options = []
        for item in snapshot.get("interactables") or []:
            if item.get("name") == group_name:
                for opt in item.get("options") or [item]:
                    radio_options.append(opt)
        ranked = [
            (max(_score_match(o.get("text"), value), _score_match(o.get("value"), value)), o)
            for o in radio_options if o.get("selector")
        ]
        ranked.sort(reverse=True)
        if not ranked or ranked[0][0] < 45:
            raise ValueError(f'Could not find radio option "{value}" for {selector}')
        await page.locator(ranked[0][1]["selector"]).check()
        return

    # Text / textarea / number
    await control.fill(str(value))

    placeholder = await control.get_attribute("placeholder") or ""
    role = await control.get_attribute("role") or ""
    has_popup = await control.get_attribute("aria-haspopup") or ""
    is_custom_select = (
        re.search(r"select\.\.\.|choose\.\.\.|search\.\.\.", placeholder, re.I)
        or role == "combobox"
        or bool(has_popup)
    )

    if is_custom_select:
        try:
            await control.click(force=True)
            await page.wait_for_timeout(200)
        except Exception:
            pass

    await page.wait_for_timeout(350)
    found = await page.evaluate(_TRY_CLICK_DROPDOWN_JS, value)

    if not found and is_custom_select:
        try:
            await control.clear()
        except Exception:
            pass
        await control.press_sequentially(str(value), delay=40)
        await page.wait_for_timeout(500)
        await page.evaluate(_TRY_CLICK_DROPDOWN_JS, value)


async def click_element(page, selector: str, allow_terminal_submit: bool = False) -> None:
    print(f"Clicking {selector}")
    clickable = await _find_clickable(page, selector, allow_terminal_submit=allow_terminal_submit)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    try:
        await clickable.click()
    except Exception as e:
        if "outside of the viewport" in str(e) or "not visible" in str(e) or "Timeout" in str(e):
            await clickable.evaluate("el => el.click()")
        else:
            raise
    await page.wait_for_timeout(500)


async def upload_resume(page, selector: str) -> None:
    print(f"Uploading resume to {selector}")
    if not RESUME_PATH.exists():
        raise FileNotFoundError(f"Resume not found at {RESUME_PATH}")
    control = await _find_control(page, selector, allowed_types=["input"])
    input_type = await control.evaluate("el => (el.type || '').toLowerCase()")
    if input_type != "file":
        raise ValueError(f'Matched "{selector}" but it is not a file input')
    await control.set_input_files(str(RESUME_PATH))


def resolve_apply_url(url: str) -> str:
    """Transform job-detail page URL → direct apply form URL for known ATSes."""
    import re as _re
    # Greenhouse: job-boards.greenhouse.io/co/jobs/ID  →  boards.greenhouse.io/co/jobs/ID
    # (form is embedded on the boards. domain; /question suffix causes 404)
    m = _re.match(r"(https?://)job-boards(\.greenhouse\.io/[^/?#]+/jobs/\d+)(.*)", url)
    if m:
        return m.group(1) + "boards" + m.group(2)
    # Ashby: jobs.ashbyhq.com/co/UUID  →  jobs.ashbyhq.com/co/UUID/application
    m = _re.match(
        r"(https?://jobs\.ashbyhq\.com/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?!/application)(/?)(\?.*)?$",
        url,
    )
    if m:
        return m.group(1) + "/application"
    # Lever: jobs.lever.co/co/UUID  →  jobs.lever.co/co/UUID/apply
    m = _re.match(
        r"(https?://jobs\.lever\.co/[^/?#]+/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?!/apply)(/?)(\?.*)?$",
        url,
    )
    if m:
        return m.group(1) + "/apply"
    return url


async def navigate(page, url: str) -> None:
    # Sanitize embedded /apply query-string bug (e.g. "?source=...&apply=true/apply")
    clean_url = re.sub(r"(/apply)\?.*$", r"\1", url) if re.search(r"/apply\?", url) else url
    print(f"Navigating to {clean_url}")
    # SPA-based ATSes need networkidle to render form fields
    is_spa = any(k in clean_url for k in ("greenhouse.io", "ashbyhq.com", "linkedin.com"))
    wait = "networkidle" if is_spa else "domcontentloaded"
    await page.goto(clean_url, wait_until=wait, timeout=30_000)
    await page.wait_for_timeout(1000 if not is_spa else 2000)


async def _find_control(page, selector_or_hint: str, allowed_types=None):
    if allowed_types is None:
        allowed_types = ["input", "select", "textarea"]
    locator = page.locator(selector_or_hint).first
    try:
        if await locator.count() > 0:
            return locator
    except Exception:
        pass

    snapshot = await get_page_content(page)
    candidates = [
        item for item in (snapshot.get("interactables") or [])
        if item.get("type") in allowed_types or item.get("tag") in allowed_types
    ]
    ranked = sorted(
        [
            (
                max(
                    _score_match(item.get("ref"), selector_or_hint),
                    _score_match(item.get("label"), selector_or_hint),
                    _score_match(item.get("name"), selector_or_hint),
                    _score_match(item.get("placeholder"), selector_or_hint),
                    _score_match(item.get("text"), selector_or_hint),
                    _score_match(item.get("ariaLabel"), selector_or_hint),
                ),
                item,
            )
            for item in candidates
        ],
        reverse=True,
    )
    ranked = [(score, item) for score, item in ranked if score >= 45]
    if not ranked:
        raise ValueError(f'Could not find a visible control matching "{selector_or_hint}"')
    return page.locator(ranked[0][1]["selector"]).first


async def _find_clickable(page, selector_or_hint: str, allow_terminal_submit: bool = False):
    locator = page.locator(selector_or_hint).first
    try:
        if await locator.count() > 0:
            is_terminal = await locator.evaluate(
                "el => { const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim(); "
                "return /^(submit|send application|submit application|complete application|final submit)$/i.test(text) || /^apply$/i.test(text); }"
            )
            if not allow_terminal_submit and is_terminal:
                raise ValueError(f'Refusing to click terminal submit/apply control "{selector_or_hint}"')
            return locator
    except ValueError:
        raise
    except Exception:
        pass

    snapshot = await get_page_content(page)
    buttons = [
        item for item in (snapshot.get("interactables") or [])
        if item.get("type") in ("button", "link")
    ]
    ranked = sorted(
        [
            (
                max(
                    _score_match(item.get("ref"), selector_or_hint),
                    _score_match(item.get("text"), selector_or_hint),
                    _score_match(item.get("label"), selector_or_hint),
                    _score_match(item.get("ariaLabel"), selector_or_hint),
                ),
                item,
            )
            for item in buttons
        ],
        reverse=True,
    )
    ranked = [(score, item) for score, item in ranked if score >= 45]
    if not ranked:
        raise ValueError(f'Could not find a visible clickable element matching "{selector_or_hint}"')
    score, item = ranked[0]
    if not allow_terminal_submit and item.get("isTerminalSubmit"):
        raise ValueError(f'Refusing to click terminal submit/apply control "{item.get("text") or selector_or_hint}"')
    return page.locator(item["selector"]).first
