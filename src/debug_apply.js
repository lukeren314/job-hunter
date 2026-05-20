import { chromium } from "playwright-core";
import Browserbase from "@browserbasehq/sdk";
import dotenv from 'dotenv';

dotenv.config();

const bb = new Browserbase({ apiKey: process.env.BROWSERBASE_API_KEY });

async function debugApplyButton() {
    const testUrl = 'https://www.linkedin.com/jobs/view/software-engineer-i-at-sony-interactive-entertainment-4412034983';
    console.log(`Debugging Apply Button for: ${testUrl}`);

    let browser;
    try {
        const session = await bb.sessions.create({ projectId: process.env.BROWSERBASE_PROJECT_ID });
        browser = await chromium.connectOverCDP(session.connectUrl);
        const page = browser.contexts()[0].pages()[0];

        await page.goto(testUrl, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(5000);

        const links = await page.evaluate(() => {
            const allLinks = Array.from(document.querySelectorAll('a'));
            return allLinks
                .filter(a => a.innerText.toLowerCase().includes('apply') || a.href.includes('apply'))
                .map(a => ({ text: a.innerText.trim(), href: a.href, classes: a.className }));
        });

        const buttons = await page.evaluate(() => {
            const allBtns = Array.from(document.querySelectorAll('button'));
            return allBtns
                .filter(b => b.innerText.toLowerCase().includes('apply'))
                .map(b => ({ text: b.innerText.trim(), classes: b.className }));
        });

        console.log("--- Links Found ---");
        console.table(links);
        console.log("--- Buttons Found ---");
        console.table(buttons);

    } catch (err) {
        console.error("Debug failed:", err.message);
    } finally {
        if (browser) await browser.close();
    }
}

debugApplyButton();
