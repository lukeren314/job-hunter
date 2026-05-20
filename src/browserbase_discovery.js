import { chromium } from "playwright-core";
import Browserbase from "@browserbasehq/sdk";
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const bb = new Browserbase({
  apiKey: process.env.BROWSERBASE_API_KEY,
});

async function runDiscovery() {
    console.log("🚀 Starting LinkedIn Discovery via Browserbase...");
    
    try {
        // 1. Create a session
        const session = await bb.sessions.create({
            projectId: process.env.BROWSERBASE_PROJECT_ID,
        });
        console.log(`Session created: ${session.id}`);

        // 2. Connect Playwright
        const browser = await chromium.connectOverCDP(session.connectUrl);
        const defaultContext = browser.contexts()[0];
        const page = defaultContext.pages()[0];

        // 3. Navigate to LinkedIn Guest Search
        const searchUrl = 'https://www.linkedin.com/jobs/search/?keywords=software%20engineer&location=Los%20Angeles%20Metropolitan%20Area&distance=25';
        console.log(`Navigating to: ${searchUrl}`);
        
        await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
        
        // Wait for job list to load
        console.log("Waiting for job list...");
        await page.waitForSelector('.jobs-search__results-list', { timeout: 30000 });

        // 4. Extract Jobs
        const jobs = await page.$$eval('.jobs-search__results-list li', elements => {
            return elements.map(el => {
                const titleEl = el.querySelector('.base-search-card__title');
                const companyEl = el.querySelector('.base-search-card__subtitle');
                const linkEl = el.querySelector('.base-card__full-link');
                const metadataEl = el.querySelector('.job-search-card__metadata');
                
                return {
                    title: titleEl?.innerText.trim(),
                    company: companyEl?.innerText.trim(),
                    url: linkEl?.getAttribute('href')?.split('?')[0],
                    posted: metadataEl?.querySelector('time')?.innerText.trim() || 'N/A'
                };
            });
        });

        console.log(`✅ Successfully discovered ${jobs.length} jobs!`);
        console.log("\n--- DISCOVERY SAMPLE ---");
        console.table(jobs.slice(0, 5));
        console.log("------------------------");

        // 5. Clean up
        await page.close();
        await browser.close();
        console.log(`Discovery complete. Recording: https://www.browserbase.com/sessions/${session.id}`);

    } catch (error) {
        console.error("❌ Discovery Failed:", error.message);
    }
}

runDiscovery();
