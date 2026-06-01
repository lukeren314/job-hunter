import { chromium } from "playwright-core";
import Browserbase from "@browserbasehq/sdk";
import dotenv from 'dotenv';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { initDb } from './db.js';
import { normalizeUrl } from './utils.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const bb = new Browserbase({
    apiKey: process.env.BROWSERBASE_API_KEY,
});

export class DiscoveryEngine {

    // ─── LinkedIn ─────────────────────────────────────────────────────────────

    async discoverLinkedIn(query, location, limit = 50) {
        console.log(`🔍 LinkedIn: "${query}" in "${location}" (limit: ${limit})`);
        const searchUrl = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(query)}&location=${encodeURIComponent(location)}`;

        let session, browser;
        try {
            session = await bb.sessions.create({ projectId: process.env.BROWSERBASE_PROJECT_ID });
            browser = await chromium.connectOverCDP(session.connectUrl);
            const defaultContext = browser.contexts()[0];
            const page = defaultContext.pages()[0];

            await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
            await page.waitForTimeout(3000);

            const hasResults = await page.$('.jobs-search__results-list');
            if (!hasResults) {
                console.warn(`   ⚠️  No results for "${query}" in "${location}" — skipping`);
                return [];
            }

            let results = [];
            let scrollAttempts = 0;
            while (results.length < limit && scrollAttempts < 3) {
                await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
                await page.waitForTimeout(2000);

                const currentJobs = await page.$$eval('.jobs-search__results-list li', elements =>
                    elements.map(el => el.querySelector('.base-card__full-link')?.getAttribute('href')?.split('?')[0])
                        .filter(Boolean)
                );

                results = [...new Set([...results, ...currentJobs])];
                if (results.length >= limit) break;

                const seeMore = await page.$('button.infinite-scroller__show-more-button');
                if (seeMore && await seeMore.isVisible()) {
                    await seeMore.click();
                    await page.waitForTimeout(3000);
                }
                scrollAttempts++;
            }

            return results.slice(0, limit);

        } catch (error) {
            if (error.message.includes('402')) throw new Error('FATAL_BROWSERBASE_LIMIT');
            console.error(`   ❌ LinkedIn discovery failed for "${query}":`, error.message);
            return [];
        } finally {
            if (browser) await browser.close();
        }
    }

    // ─── Indeed ───────────────────────────────────────────────────────────────

    async discoverIndeed(query, location, limit = 50) {
        console.log(`🔍 Indeed:   "${query}" in "${location}" (limit: ${limit})`);
        const searchUrl = `https://www.indeed.com/jobs?q=${encodeURIComponent(query)}&l=${encodeURIComponent(location)}`;

        let session, browser;
        try {
            session = await bb.sessions.create({ projectId: process.env.BROWSERBASE_PROJECT_ID });
            browser = await chromium.connectOverCDP(session.connectUrl);
            const defaultContext = browser.contexts()[0];
            const page = defaultContext.pages()[0];

            await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 });
            await page.waitForTimeout(4000);

            // Indeed renders results in a list; each job card carries a data-jk attribute
            const hasResults = await page.$('[data-testid="jobsearch-ResultsList"], .jobsearch-ResultsList, #mosaic-provider-jobcards');
            if (!hasResults) {
                console.warn(`   ⚠️  No Indeed results for "${query}" in "${location}" — skipping`);
                return [];
            }

            const jkSet = new Set();
            let scrollAttempts = 0;

            while (jkSet.size < limit && scrollAttempts < 5) {
                // Collect job keys via data-jk attribute or from href patterns
                const jks = await page.evaluate(() => {
                    const ids = new Set();
                    // data-jk on card containers
                    document.querySelectorAll('[data-jk]').forEach(el => ids.add(el.dataset.jk));
                    // jk= in job-card links
                    document.querySelectorAll('a[href*="jk="]').forEach(a => {
                        const m = a.href.match(/[?&]jk=([a-f0-9]+)/);
                        if (m) ids.add(m[1]);
                    });
                    return [...ids].filter(Boolean);
                });

                for (const jk of jks) {
                    jkSet.add(jk);
                    if (jkSet.size >= limit) break;
                }

                if (jkSet.size >= limit) break;

                await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
                await page.waitForTimeout(2000);

                // Try clicking "Next" for pagination
                const nextBtn = page.locator('a[data-testid="pagination-page-next"], [aria-label="Next Page"]').first();
                if (scrollAttempts >= 2 && await nextBtn.count() > 0) {
                    await nextBtn.click();
                    await page.waitForTimeout(3000);
                }

                scrollAttempts++;
            }

            return [...jkSet]
                .slice(0, limit)
                .map(jk => `https://www.indeed.com/viewjob?jk=${jk}`);

        } catch (error) {
            if (error.message.includes('402')) throw new Error('FATAL_BROWSERBASE_LIMIT');
            console.error(`   ❌ Indeed discovery failed for "${query}":`, error.message);
            return [];
        } finally {
            if (browser) await browser.close();
        }
    }

    // ─── Orchestration ────────────────────────────────────────────────────────

    async run() {
        console.log("🚀 Starting Discovery Stage...");
        const db = await initDb();
        const requirementsPath = join(__dirname, '../config/requirements.json');
        const config = JSON.parse(fs.readFileSync(requirementsPath, 'utf8'));
        const { job_queries, must_haves } = config;
        const location = must_haves.location_center.name;

        // Which sources to query — default: linkedin only; opt-in to indeed
        const sources = config.discovery_sources || ['linkedin'];

        const insertUrls = async (urls, label) => {
            console.log(`   📡 Found ${urls.length} candidate URLs (${label})`);
            for (const url of urls) {
                const normalized = normalizeUrl(url);
                try {
                    await db.run(
                        'INSERT OR IGNORE INTO discovery_urls (normalized_url) VALUES (?)',
                        [normalized]
                    );
                } catch (e) {
                    console.error(`      ❌ DB Error for ${normalized}:`, e.message);
                }
            }
        };

        const tasks = [];

        for (const query of job_queries) {
            if (sources.includes('linkedin')) {
                tasks.push(
                    this.discoverLinkedIn(query, location, 50)
                        .then(urls => insertUrls(urls, `LinkedIn / ${query}`))
                        .catch(e => {
                            if (e.message.startsWith('FATAL_')) throw e;
                            console.error(`   ⚠️  LinkedIn error for "${query}":`, e.message);
                        })
                );
            }

            if (sources.includes('indeed')) {
                tasks.push(
                    this.discoverIndeed(query, location, 50)
                        .then(urls => insertUrls(urls, `Indeed / ${query}`))
                        .catch(e => {
                            if (e.message.startsWith('FATAL_')) throw e;
                            console.error(`   ⚠️  Indeed error for "${query}":`, e.message);
                        })
                );
            }
        }

        await Promise.all(tasks);
        console.log("✅ Discovery Stage Finished.\n");
    }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    const engine = new DiscoveryEngine();
    engine.run().catch(err => console.error("Discovery Fatal:", err));
}
