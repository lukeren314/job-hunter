"""Batch and survey apply modes."""
import asyncio
from apply.agent import run_agent


async def batch_apply(urls: list[str], headless: bool = True, survey: bool = False) -> dict:
    results = []
    for url in urls:
        print(f"\n{'='*60}\nApplying: {url}\n{'='*60}")
        try:
            result = await run_agent(url, headless=headless, collect_questions=survey, no_wait=True)
            results.append({"url": url, "status": "completed" if result["finished"] else "incomplete", **result})
        except Exception as e:
            results.append({"url": url, "status": "error", "error": str(e)})

    # Summary
    completed = sum(1 for r in results if r.get("finished"))
    print(f"\n{'='*60}")
    print(f"Batch complete: {completed}/{len(urls)} finished")
    if survey:
        all_questions = [q for r in results for q in r.get("pending_questions") or []]
        if all_questions:
            print(f"Collected {len(all_questions)} questions across all applications:")
            for q in all_questions:
                print(f"  [{q.get('field_key')}] {q.get('question')}")
    return {"results": results, "completed": completed, "total": len(urls)}
