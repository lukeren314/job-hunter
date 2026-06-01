import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "jobs.db"


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS discovery_urls (
            normalized_url TEXT PRIMARY KEY,
            canonical_id TEXT,
            status TEXT DEFAULT 'pending',
            search_query TEXT,
            search_label TEXT,
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS jobs (
            canonical_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            external_url TEXT,
            company TEXT,
            title TEXT,
            location TEXT,
            salary_min INTEGER,
            salary_max INTEGER,
            work_type TEXT,
            employment_type TEXT,
            seniority_level TEXT,
            level TEXT,
            responsibilities TEXT,
            requirements TEXT,
            preferred_qualifications TEXT,
            description TEXT,
            raw_content TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            job_id TEXT PRIMARY KEY,
            fit_score INTEGER,
            reasoning TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(canonical_id)
        );
    """)
    # Migrations — safe to re-run, catch OperationalError if column exists
    for migration in [
        "ALTER TABLE jobs ADD COLUMN level TEXT",
        "ALTER TABLE discovery_urls ADD COLUMN search_query TEXT",
        "ALTER TABLE discovery_urls ADD COLUMN search_label TEXT",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def get_pending_urls(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT normalized_url FROM discovery_urls WHERE status = 'pending' LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_url(
    conn: sqlite3.Connection,
    url: str,
    search_query: str | None = None,
    search_label: str | None = None,
) -> bool:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO discovery_urls (normalized_url, search_query, search_label) VALUES (?, ?, ?)",
            (url, search_query, search_label),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error:
        return False


def mark_url_status(
    conn: sqlite3.Connection,
    url: str,
    status: str,
    canonical_id: str | None = None,
) -> None:
    conn.execute(
        "UPDATE discovery_urls SET status = ?, canonical_id = ? WHERE normalized_url = ?",
        (status, canonical_id, url),
    )
    conn.commit()


def job_exists(conn: sqlite3.Connection, canonical_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE canonical_id = ?", (canonical_id,)
    ).fetchone()
    return row is not None


def insert_job(conn: sqlite3.Connection, job: dict) -> None:
    cols = [
        "canonical_id", "source_url", "external_url", "company", "title",
        "location", "salary_min", "salary_max", "work_type", "employment_type",
        "seniority_level", "level", "responsibilities", "requirements",
        "preferred_qualifications", "description", "raw_content",
    ]
    values = [job.get(c) for c in cols]
    placeholders = ", ".join("?" * len(cols))
    col_names = ", ".join(cols)
    conn.execute(
        f"INSERT OR REPLACE INTO jobs ({col_names}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
