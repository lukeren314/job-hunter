import json
import httpx
from pathlib import Path
from urllib.parse import urlparse

_LINKEDIN_SESSION = Path(__file__).parent.parent.parent / "config" / "linkedin_session.json"


def _load_linkedin_cookies() -> list[dict]:
    """Load saved LinkedIn session cookies if the file exists."""
    if _LINKEDIN_SESSION.exists():
        try:
            data = json.loads(_LINKEDIN_SESSION.read_text())
            # Accept either {"cookies": [...]} or a bare list
            cookies = data.get("cookies", data) if isinstance(data, dict) else data
            return [c for c in cookies if isinstance(c, dict)]
        except Exception:
            pass
    return []

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def detect_adapter(url: str) -> str:
    host = urlparse(url).hostname or ""
    path = urlparse(url).path
    if "linkedin.com" in host and "/jobs/" in path:
        return "linkedin"
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    return "generic"


async def route_extract(url: str, use_llm: bool = False) -> dict | None:
    adapter_name = detect_adapter(url)

    if adapter_name == "linkedin":
        from playwright.async_api import async_playwright
        from extractor.adapters import linkedin

        cookies = _load_linkedin_cookies()
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=_HEADERS["User-Agent"],
            )
            if cookies:
                await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(1500)
                result = await linkedin.extract(page, url)
            finally:
                await browser.close()
        return result

    # Static page adapters
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
        html = resp.text
    except httpx.HTTPError as e:
        print(f"   HTTP error fetching {url}: {e}")
        return None

    if adapter_name == "greenhouse":
        from extractor.adapters import greenhouse
        return greenhouse.extract(html, url)
    if adapter_name == "lever":
        from extractor.adapters import lever
        result = lever.extract(html, url)
        if result and result.get("title") and "sorry" in result["title"].lower():
            return None
        return result
    if adapter_name == "ashby":
        from extractor.adapters import ashby
        return ashby.extract(url)

    from extractor.adapters import generic
    return generic.extract(html, url, use_llm=use_llm)
