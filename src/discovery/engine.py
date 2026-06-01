from concurrent.futures import ThreadPoolExecutor, as_completed

from common.config import load_personal_info, load_requirements
from discovery.query_builder import build_queries
from discovery.worker import DiscoveryWorker


def run_discovery(max_workers: int = 8, dry_run: bool = False, db_path=None) -> int:
    personal_info = load_personal_info()
    requirements = load_requirements()
    queries = build_queries(personal_info, requirements)

    if not queries:
        print("No queries generated. Check requirements.json job_queries field.")
        return 0

    print(f"Discovery: {len(queries)} queries, {max_workers} workers")

    if dry_run:
        for q, label in queries:
            print(f"  [{label}] {q}")
        return 0

    total = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, len(queries))) as pool:
        futures = {
            pool.submit(DiscoveryWorker(q, label, db_path).run): label
            for q, label in queries
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                count = future.result()
                total += count
                print(f"  ✓ [{label}] +{count} URLs")
            except Exception as e:
                print(f"  ✗ [{label}] error: {e}")

    print(f"Discovery done. {total} new URLs inserted.")
    return total
