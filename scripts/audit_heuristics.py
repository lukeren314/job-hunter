"""
Heuristic coverage audit.

For each job in DB, navigate to its apply page, snapshot the form fields,
run get_known_answer() on each, and report:
  - which field labels were filled vs not
  - aggregate coverage stats
  - which unfilled labels appear most (LLM candidates)

Usage:
    python scripts/audit_heuristics.py [--limit N] [--adapter greenhouse|lever|ashby]
"""
import asyncio
import argparse
import json
import sys
import re
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from apply.heuristics import get_known_answer
from apply.tools import get_page_content, resolve_apply_url, load_linkedin_cookies
from common.db import init_db
from common.config import load_personal_info

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_APPLY_BUTTON_RE = re.compile(r"^apply(?:\s+(?:now|for\s+this\s+(?:job|role|position)))?$", re.I)


async def get_apply_url(page, job_url: str) -> str:
    """Resolve the direct apply-form URL for a job page."""
    apply_url = resolve_apply_url(job_url)
    # SPA adapters need networkidle to render the form
    is_spa = any(k in job_url for k in ("ashby", "greenhouse", "linkedin"))
    try:
        wait = "networkidle" if is_spa else "domcontentloaded"
        await page.goto(apply_url, wait_until=wait, timeout=30_000)
        if is_spa:
            await page.wait_for_timeout(2000)
    except Exception:
        pass
    return apply_url


async def audit_job(page, job: dict, personal_info: dict) -> dict | None:
    source_url = job["source_url"]

    try:
        apply_url = await get_apply_url(page, source_url)
    except Exception as e:
        return {"url": source_url, "error": str(e), "fields": []}

    try:
        snapshot = await get_page_content(page)
    except Exception as e:
        return {"url": source_url, "error": str(e), "fields": []}

    fields = []
    for item in snapshot.get("interactables") or []:
        itype = item.get("inputType") or item.get("type") or "text"
        if itype in ("button", "link", "submit"):
            continue
        label = item.get("label") or item.get("placeholder") or item.get("name") or ""
        if not label:
            continue
        answer = get_known_answer(item, personal_info)
        fields.append({
            "label": label,
            "inputType": itype,
            "required": bool(item.get("required")),
            "filled": answer is not None,
            "answer_preview": (answer or "")[:40] if answer else None,
        })

    return {"url": source_url, "apply_url": page.url, "fields": fields}


async def main(limit: int, adapter_filter: str | None):
    from playwright.async_api import async_playwright

    personal_info = load_personal_info()
    conn = init_db()

    query = "SELECT canonical_id, source_url, title, company FROM jobs WHERE source_url IS NOT NULL"
    if adapter_filter:
        query += f" AND canonical_id LIKE '{adapter_filter}_%'"
    query += f" ORDER BY RANDOM() LIMIT {limit}"
    jobs = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()

    print(f"Auditing {len(jobs)} jobs...\n")

    results = []
    total_fields = 0
    filled_fields = 0
    required_total = 0
    required_filled = 0
    unfilled_labels: dict[str, int] = defaultdict(int)
    unfilled_required_labels: dict[str, int] = defaultdict(int)
    filled_label_examples: dict[str, str] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            user_agent=_HEADERS["User-Agent"],
        )
        li_cookies = load_linkedin_cookies()
        if li_cookies:
            await ctx.add_cookies(li_cookies)
        page = await ctx.new_page()

        for i, job in enumerate(jobs):
            adapter = job["canonical_id"].split("_")[0]
            label = f"{job['company'] or '?'} / {job['title'] or '?'}"
            print(f"[{i+1}/{len(jobs)}] [{adapter}] {label}")

            result = await audit_job(page, job, personal_info)
            if result is None or result.get("error"):
                print(f"  ✗ error: {result.get('error') if result else 'none'}")
                continue

            nf = len(result["fields"])
            nfilled = sum(1 for f in result["fields"] if f["filled"])
            nreq = sum(1 for f in result["fields"] if f["required"])
            nreq_filled = sum(1 for f in result["fields"] if f["required"] and f["filled"])

            print(f"  {nfilled}/{nf} filled ({nreq_filled}/{nreq} required)")

            total_fields += nf
            filled_fields += nfilled
            required_total += nreq
            required_filled += nreq_filled

            for f in result["fields"]:
                norm_label = re.sub(r"\s+", " ", f["label"].lower().strip())[:60]
                if f["filled"]:
                    if norm_label not in filled_label_examples:
                        filled_label_examples[norm_label] = f["answer_preview"] or ""
                else:
                    unfilled_labels[norm_label] += 1
                    if f["required"]:
                        unfilled_required_labels[norm_label] += 1

            results.append(result)

        await browser.close()

    print("\n" + "="*60)
    print(f"SUMMARY: {len(results)} jobs audited")
    print(f"  All fields:      {filled_fields}/{total_fields} filled ({filled_fields*100//max(total_fields,1)}%)")
    print(f"  Required fields: {required_filled}/{required_total} filled ({required_filled*100//max(required_total,1)}%)")

    print(f"\nTop 25 UNFILLED labels (any):")
    for label, count in sorted(unfilled_labels.items(), key=lambda x: -x[1])[:25]:
        req_count = unfilled_required_labels.get(label, 0)
        req_tag = f" [required x{req_count}]" if req_count else ""
        print(f"  {count:3d}x  {label}{req_tag}")

    print(f"\nTop 15 UNFILLED REQUIRED labels (need LLM or new heuristic):")
    for label, count in sorted(unfilled_required_labels.items(), key=lambda x: -x[1])[:15]:
        print(f"  {count:3d}x  {label}")

    print(f"\nSample FILLED labels (heuristic working):")
    for label, preview in list(filled_label_examples.items())[:20]:
        print(f"  {label!r:40s} → {preview!r}")

    # Save full results
    out = Path("data/heuristic_audit.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nFull results → {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--adapter", choices=["greenhouse", "lever", "ashby", "linkedin"])
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.adapter))
