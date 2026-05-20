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
    async discoverLinkedIn(query, location, limit = 50) {
        console.log(`🔍 Discovering: "${query}" in "${location}" (limit: ${limit})`);
        const searchUrl = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(query)}&location=${encodeURIComponent(location)}`;
        
        let session;
        let browser;
        try {
            session = await bb.sessions.create({ projectId: process.env.BROWSERBASE_PROJECT_ID });
            browser = await chromium.connectOverCDP(session.connectUrl);
            const defaultContext = browser.contexts()[0];
            const page = defaultContext.pages()[0];

            await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
            await page.waitForSelector('.jobs-search__results-list', { timeout: 30000 });

            let results = [];
            let scrollAttempts = 0;
            while (results.length < limit && scrollAttempts < 3) {
                await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
                await page.waitForTimeout(2000);
                
                const currentJobs = await page.$$eval('.jobs-search__results-list li', elements => {
                    return elements.map(el => {
                        const linkEl = el.querySelector('.base-card__full-link');
                        return linkEl?.getAttribute('href')?.split('?')[0];
                    }).filter(Boolean);
                });
                
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
            if (error.message.includes('402')) {
                throw new Error('FATAL_BROWSERBASE_LIMIT');
            }
            console.error(`   ❌ Discovery failed for ${query}:`, error.message);
            return [];
        } finally {
            if (browser) await browser.close();
        }
    }

    async run() {
        console.log("🚀 Starting Discovery Stage...");
        const db = await initDb();
        const watchlist = JSON.parse(fs.readFileSync(join(__dirname, '../config/watchlist.json'), 'utf8'));

        for (const item of watchlist) {
            try {
                const urls = await this.discoverLinkedIn(item.query, item.location, item.limit);
                console.log(`   📡 Found ${urls.length} candidate URLs for "${item.query}"`);
                
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
            } catch (e) {
                if (e.message.startsWith('FATAL_')) {
                    console.error(`🛑 ABORTING: ${e.message}`);
                    throw e;
                }
                console.error(`   ⚠️ Discovery loop error:`, e.message);
            }
        }
        console.log("✅ Discovery Stage Finished.\n");
    }
}

// Allow standalone execution
if (process.argv[1] === fileURLToPath(import.meta.url)) {
    const engine = new DiscoveryEngine();
    engine.run().catch(err => console.error("Discovery Fatal:", err));
}
