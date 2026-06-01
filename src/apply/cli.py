import argparse
import asyncio


def main():
    parser = argparse.ArgumentParser(description="Apply agent for job applications")
    parser.add_argument("url", nargs="?", help="Job application URL")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--no-wait", action="store_true", help="Skip 30s browser review pause")
    parser.add_argument("--survey", action="store_true", help="Collect questions without blocking for input")
    parser.add_argument("--batch", action="store_true", help="Batch mode: apply to all unapplied jobs in DB")
    args = parser.parse_args()

    if args.batch:
        from common.db import init_db
        conn = init_db()
        rows = conn.execute(
            "SELECT source_url, external_url FROM jobs WHERE canonical_id NOT IN (SELECT job_id FROM evaluations)"
        ).fetchall()
        # For LinkedIn jobs with an external ATS URL, apply via the ATS directly
        urls = [
            (r["external_url"] if r["external_url"] and "linkedin.com" in (r["source_url"] or "") else r["source_url"])
            for r in rows
            if r["source_url"]
        ]
        conn.close()
        if not urls:
            print("No unapplied jobs found in database.")
            return
        from apply.batch import batch_apply
        asyncio.run(batch_apply(urls, headless=args.headless, survey=args.survey))
    elif args.url:
        from apply.agent import run_agent
        result = asyncio.run(run_agent(
            args.url,
            headless=args.headless,
            collect_questions=args.survey,
            no_wait=args.no_wait,
        ))
        print(f"\nResult: {'finished' if result['finished'] else 'incomplete'} in {result['steps']} steps")
        if result["pending_questions"]:
            print(f"Questions collected: {len(result['pending_questions'])}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
