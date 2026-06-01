from ddgs import DDGS
from common.db import init_db, insert_url
from extractor.shared import normalize_url
from discovery.query_builder import is_job_url


class DiscoveryWorker:
    def __init__(self, query: str, label: str, db_path=None):
        self.query = query
        self.label = label
        self.db_path = db_path

    def run(self) -> int:
        conn = init_db(self.db_path)
        inserted = 0
        try:
            results = DDGS().text(self.query, max_results=50)
            for r in (results or []):
                href = r.get("href", "")
                if href and is_job_url(href):
                    url = normalize_url(href)
                    if insert_url(conn, url, search_query=self.query, search_label=self.label):
                        inserted += 1
        except Exception as e:
            print(f"   Worker [{self.label}] error: {e}")
        finally:
            conn.close()
        return inserted
