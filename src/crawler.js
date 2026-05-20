import { chromium } from 'playwright';
import sqlite3 from 'sqlite3';
import { open } from 'sqlite';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function setupDatabase() {
    const db = await open({
        filename: join(__dirname, '../data/jobs.db'),
        driver: sqlite3.Database
    });
    await db.exec(`
        CREATE TABLE IF NOT EXISTS processed_jobs (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            company TEXT,
            fit_score TEXT,
            raw_content TEXT,
            date_processed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    `);
    return db;
}

class LinkedInWatcher {
    constructor() {
        this.db = null;
        this.browser = null;
        this.context = null;
    }

    async init() {
        this.db = await setupDatabase();
        this.browser = await chromium.launch({ headless: true });
        this.context = await this.browser.newContext({
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
        });
    }

    async close() {
        if (this.browser) await this.browser.close();
    }

    async watch(url) {
        const page = await this.context.newPage();
        console.log(`Navigating to LinkedIn search: ${url}`);
        
        try {
            await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
            await page.waitForTimeout(5000); // Wait for dynamic content

            // Extract job items
            const jobItems = await page.$$('.jobs-search__results-list li');
            console.log(`Found ${jobItems.length} jobs on search page.`);

            for (let i = 0; i < jobItems.length; i++) {
                const item = jobItems[i];
                
                // Extract metadata
                const info = await item.evaluate(el => {
                    const titleEl = el.querySelector('.base-search-card__title');
                    const companyEl = el.querySelector('.base-search-card__subtitle');
                    const linkEl = el.querySelector('.base-card__full-link');
                    return {
                        title: titleEl?.innerText.trim(),
                        company: companyEl?.innerText.trim(),
                        url: linkEl?.getAttribute('href')?.split('?')[0] // Clean URL
                    };
                });

                if (!info.url) continue;
                const jobId = info.url.match(/\/view\/(\d+)/)?.[1] || info.url;

                // Check cache
                const cached = await this.db.get('SELECT id FROM processed_jobs WHERE id = ?', [jobId]);
                if (cached) {
                    console.log(`Skipping processed job: ${info.title} at ${info.company}`);
                    continue;
                }

                console.log(`Extracting: ${info.title} | ${info.company}`);
                
                // Open job detail in new page to avoid losing search context
                const detailPage = await this.context.newPage();
                try {
                    await detailPage.goto(info.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
                    
                    // Wait for description
                    await detailPage.waitForSelector('.description__text', { timeout: 10000 }).catch(() => null);
                    
                    const description = await detailPage.evaluate(() => {
                        // Attempt to expand 'Show more' if it exists
                        const showMore = document.querySelector('.show-more-less-html__button--more');
                        if (showMore) showMore.click();
                        
                        const desc = document.querySelector('.description__text');
                        return desc ? desc.innerText.trim() : 'Content not found';
                    });

                    // Save to DB
                    await this.db.run(
                        'INSERT INTO processed_jobs (id, url, title, company, raw_content) VALUES (?, ?, ?, ?, ?)',
                        [jobId, info.url, info.title, info.company, description]
                    );

                    console.log(`Saved ${jobId}. Content length: ${description.length}`);

                } catch (err) {
                    console.error(`Failed to extract job ${jobId}: ${err.message}`);
                } finally {
                    await detailPage.close();
                }

                // Throttle a bit
                await page.waitForTimeout(1000 + Math.random() * 2000);
            }

            // Logic for "Next Page" could be added here
            // const nextButton = await page.$('button[aria-label="Next"]');
            
        } catch (err) {
            console.error(`Crawl error: ${err.message}`);
        } finally {
            await page.close();
        }
    }
}

async function start() {
    const watcher = new LinkedInWatcher();
    await watcher.init();
    await watcher.watch('https://www.linkedin.com/jobs/search/?keywords=software%20engineer&location=Los%20Angeles%20Metropolitan%20Area&distance=25');
    await watcher.close();
}

start();
