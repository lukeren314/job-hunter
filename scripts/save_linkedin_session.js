#!/usr/bin/env node
/**
 * One-time setup: saves your LinkedIn browser session for use by the crawler.
 *
 * A browser window opens. Log into LinkedIn normally, and the script will
 * automatically detect when you reach the feed and save the session.
 *
 * Session is saved to config/linkedin_session.json and used on every future run.
 * Re-run this script whenever the session expires (typically a few weeks).
 *
 * Usage:
 *   node scripts/save_linkedin_session.js
 *   npm run linkedin:login
 */

import { chromium } from 'playwright';
import path         from 'path';
import fs           from 'fs';
import { fileURLToPath } from 'url';

const __dirname    = path.dirname(fileURLToPath(import.meta.url));
const SESSION_PATH = path.resolve(__dirname, '../config/linkedin_session.json');
const CONFIG_DIR   = path.dirname(SESSION_PATH);

// LinkedIn URLs that indicate a successful login
const LOGGED_IN_RE = /linkedin\.com\/(feed|in\/|mynetwork|jobs|notifications|messaging)/;

async function main() {
    if (!fs.existsSync(CONFIG_DIR)) fs.mkdirSync(CONFIG_DIR, { recursive: true });

    console.log('\n🔑  LinkedIn Session Saver');
    console.log('─────────────────────────────────────────────');
    console.log('A browser window is opening — log into LinkedIn.');
    console.log('The session will be saved automatically once you reach the feed.\n');

    const browser = await chromium.launch({
        headless: false,
        args: ['--start-maximized'],
    });

    const context = await browser.newContext({
        viewport: null,
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    });

    const page = await context.newPage();
    await page.goto('https://www.linkedin.com/login', { waitUntil: 'domcontentloaded' });

    console.log('⏳  Waiting for you to log in…');

    // Wait until the URL indicates a successful login (with a generous timeout)
    await page.waitForURL(url => LOGGED_IN_RE.test(url), { timeout: 300_000 });

    // Small pause to let post-login cookies settle
    await page.waitForTimeout(2000);

    await context.storageState({ path: SESSION_PATH });
    console.log(`\n✅  Session saved → ${SESSION_PATH}`);
    console.log('   The crawler will now use this session automatically.\n');

    await browser.close();
    process.exit(0);
}

main().catch(err => {
    console.error('\n❌  Error:', err.message);
    process.exit(1);
});
