import { GoogleGenerativeAI } from "@google/generative-ai";
import Browserbase from "@browserbasehq/sdk";
import { chromium } from "playwright-core";
import dotenv from 'dotenv';
import { normalizeUrl } from './utils.js';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { initDb } from './db.js';

dotenv.config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const bb = new Browserbase({ apiKey: process.env.BROWSERBASE_API_KEY });

let lastGeminiCall = 0;
const GEMINI_INTERVAL = 5000;

import { chromium as chromiumLocal } from "playwright";

export async function extractJobData(url) {
    console.log(`📄 Scraping: ${url}`);
    
    let browser;
    let rawContent = "";
    let context;

    try {
        if (process.env.BROWSERBASE_API_KEY && process.env.BROWSERBASE_API_KEY !== 'your_api_key_here') {
            try {
                const session = await bb.sessions.create({ projectId: process.env.BROWSERBASE_PROJECT_ID });
                browser = await chromium.connectOverCDP(session.connectUrl);
                context = browser.contexts()[0];
            } catch (e) {
                console.warn(`   ⚠️ Browserbase failed, falling back to local: ${e.message}`);
            }
        }

        if (!browser) {
            browser = await chromiumLocal.launch({ headless: true });
            context = await browser.newContext({
                userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
            });
        }

        const page = await context.newPage();
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
        await page.waitForTimeout(3000);

        const pageData = await page.evaluate(() => {
            const showMore = document.querySelector('.show-more-less-html__button--more');
            if (showMore) showMore.click();

            const desc = document.querySelector('.description__text')?.innerText || "";
            const title = document.querySelector('.top-card-layout__title')?.innerText || "";
            const company = document.querySelector('.topcard__org-name-link')?.innerText || "";
            const location = document.querySelector('.topcard__flavor--bullet')?.innerText || "";

            let internalId = null;
            try {
                const ld = JSON.parse(document.querySelector('script[type="application/ld+json"]')?.innerText || "{}");
                internalId = ld.identifier?.value;
            } catch (e) {}

            return { title, company, location, description: desc, internalId };
        });

        rawContent = `TITLE: ${pageData.title}\nCOMPANY: ${pageData.company}\nLOCATION: ${pageData.location}\nINTERNAL_ID: ${pageData.internalId}\nDESCRIPTION: ${pageData.description}`;

    } catch (err) {
        if (err.message.includes('402')) {
            throw new Error('FATAL_BROWSERBASE_LIMIT');
        }
        console.error(`   ❌ Scrape Failed:`, err.message);
        return null;
    } finally {
        if (browser) await browser.close();
    }

    // AI Extraction
    const now = Date.now();
    if (now - lastGeminiCall < GEMINI_INTERVAL) {
        await new Promise(r => setTimeout(r, GEMINI_INTERVAL - (now - lastGeminiCall)));
    }
    lastGeminiCall = Date.now();

    console.log(`   🧠 AI Data Normalization...`);
    const model = genAI.getGenerativeModel({ model: "gemini-flash-latest" });
    const prompt = `
Extract structured job data.
- INTERNAL ID: Look for company-specific IDs (e.g. JR123).
CONTENT:
${rawContent.substring(0, 5000)}

Return ONLY JSON:
{
  "company": "string",
  "title": "string",
  "internal_job_id": "string or null",
  "experience_level": "Junior" | "Mid" | "Senior" | "Lead",
  "salary_min": number | null,
  "salary_max": number | null,
  "location": "string",
  "work_type": "Onsite" | "Hybrid" | "Remote",
  "employment_type": "Full-time" | "Contract",
  "description_summary": "..."
}
`;

    try {
        const result = await model.generateContent(prompt);
        const text = (await result.response).text();
        const jsonMatch = text.match(/\{[\s\S]*\}/);
        const data = JSON.parse(jsonMatch ? jsonMatch[0] : text);
        
        const internalId = data.internal_job_id || "";
        const canonicalId = internalId
            ? `${data.company.replace(/\s+/g, '_')}_${internalId}`
            : normalizeUrl(url);

        return {
            ...data,
            canonical_id: canonicalId,
            source_url: normalizeUrl(url),
            raw_content: rawContent
        };
    } catch (e) {
        if (e.message.includes('429')) {
            throw new Error('FATAL_GEMINI_LIMIT');
        }
        console.error("   ❌ Gemini Error:", e.message);
        return null;
    }
}

// isDiscoveryDone: when running in parallel with discovery, pass a fn that returns true
// once discovery has finished so the extractor knows when to stop polling for new URLs.
// Defaults to () => true for standalone use (exit as soon as the queue is empty).
export async function runExtractor(isDiscoveryDone = () => true) {
    console.log("🚀 Starting Extraction Stage...");
    const db = await initDb();

    while (true) {
        const pending = await db.all("SELECT normalized_url FROM discovery_urls WHERE status = 'pending' LIMIT 50");

        if (pending.length === 0) {
            if (isDiscoveryDone()) break;
            await new Promise(r => setTimeout(r, 3000));
            continue;
        }

        console.log(`   📂 Processing ${pending.length} pending URLs...`);

        for (const record of pending) {
            const url = record.normalized_url;

            try {
                const existingJob = await db.get("SELECT canonical_id FROM jobs WHERE source_url = ?", [url]);
                if (existingJob) {
                    console.log(`   📦 URL already linked: ${existingJob.canonical_id}`);
                    await db.run("UPDATE discovery_urls SET status = 'extracted', canonical_id = ? WHERE normalized_url = ?", [existingJob.canonical_id, url]);
                    continue;
                }

                const jobData = await extractJobData(url);
                if (jobData) {
                    const canonicalMatch = await db.get("SELECT canonical_id FROM jobs WHERE canonical_id = ?", [jobData.canonical_id]);

                    if (!canonicalMatch) {
                        await db.run(
                            `INSERT OR REPLACE INTO jobs (canonical_id, source_url, company, title, location, salary_min, salary_max, level, work_type, employment_type, raw_content)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
                            [jobData.canonical_id, jobData.source_url, jobData.company, jobData.title, jobData.location, jobData.salary_min, jobData.salary_max, jobData.experience_level, jobData.work_type, jobData.employment_type, jobData.raw_content]
                        );
                    }
                    await db.run("UPDATE discovery_urls SET status = 'extracted', canonical_id = ? WHERE normalized_url = ?", [jobData.canonical_id, url]);
                    console.log(`   ✅ Extracted: ${jobData.company} (ID: ${jobData.canonical_id.split('_').pop()})`);
                } else {
                    await db.run("UPDATE discovery_urls SET status = 'failed' WHERE normalized_url = ?", [url]);
                }
            } catch (e) {
                if (e.message.startsWith('FATAL_')) {
                    console.error(`🛑 ABORTING: ${e.message}`);
                    throw e;
                }
                console.error(`   ⚠️ Error processing ${url}:`, e.message);
                await db.run("UPDATE discovery_urls SET status = 'failed' WHERE normalized_url = ?", [url]);
            }
        }
    }

    console.log("✅ Extraction Stage Finished.\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    runExtractor().catch(err => console.error("Extractor Fatal:", err));
}
