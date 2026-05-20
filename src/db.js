import sqlite3 from 'sqlite3';
import { open } from 'sqlite';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export async function initDb() {
    const db = await open({
        filename: join(__dirname, '../data/jobs.db'),
        driver: sqlite3.Database
    });

    await db.exec(`
        -- Queue of found URLs
        CREATE TABLE IF NOT EXISTS discovery_urls (
            normalized_url TEXT PRIMARY KEY,
            canonical_id TEXT, -- Populated after extraction
            status TEXT DEFAULT 'pending', -- 'pending', 'extracted', 'failed'
            discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Extracted canonical job data
        CREATE TABLE IF NOT EXISTS jobs (
            canonical_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            external_url TEXT,
            company TEXT,
            title TEXT,
            location TEXT,
            salary_min INTEGER,
            salary_max INTEGER,
            level TEXT,
            work_type TEXT,
            employment_type TEXT,
            raw_content TEXT,
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Evaluation results
        CREATE TABLE IF NOT EXISTS evaluations (
            job_id TEXT PRIMARY KEY,
            fit_score INTEGER,
            reasoning TEXT,
            evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(canonical_id)
        );
    `);
    return db;
}
