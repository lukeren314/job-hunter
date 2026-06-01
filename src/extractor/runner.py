import asyncio
from common.db import init_db, get_pending_urls, mark_url_status, job_exists, insert_job
from extractor.router import route_extract
from extractor.shared import canonical_id


async def run_extractor(use_llm: bool = False, db_path=None) -> None:
    conn = init_db(db_path)
    print("Extractor running. Polling for pending URLs...")

    while True:
        pending = get_pending_urls(conn, limit=50)
        if not pending:
            break

        for row in pending:
            url = row["normalized_url"]
            cid = canonical_id(url)

            if job_exists(conn, cid):
                mark_url_status(conn, url, "extracted", cid)
                continue

            print(f"  Extracting: {url}")
            try:
                job = await route_extract(url, use_llm=use_llm)
                if job:
                    insert_job(conn, job)
                    mark_url_status(conn, url, "extracted", job["canonical_id"])
                    print(f"    ✓ {job.get('title') or 'unknown'} @ {job.get('company') or 'unknown'}")
                else:
                    mark_url_status(conn, url, "failed")
                    print(f"    ✗ no data extracted")
            except Exception as e:
                mark_url_status(conn, url, "failed")
                print(f"    ✗ error: {e}")

    conn.close()
    print("Extractor done.")
