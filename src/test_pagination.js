import { chromium } from 'playwright';
import dotenv from 'dotenv';

dotenv.config();

async function testPagination() {
    console.log("Starting test: LinkedIn Pagination/Infinite Scroll");
    
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    const searchUrl = 'https://www.linkedin.com/jobs/search/?keywords=software%20engineer&location=Los%20Angeles%20Metropolitan%20Area&distance=25';
    
    console.log(`Navigating to: ${searchUrl}`);
    
    try {
        await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await page.waitForTimeout(5000);

        // Get initial count
        let jobCount = await page.$$eval('.jobs-search__results-list li', els => els.length);
        console.log(`Initial job count: ${jobCount}`);

        // Try to scroll and load more
        console.log("Scrolling and looking for 'See more jobs' button...");
        
        for (let i = 0; i < 3; i++) {
            console.log(`Step ${i + 1}: Scrolling to bottom...`);
            await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
            await page.waitForTimeout(3000);

            // Look for any button that contains "See more" or "Load more"
            const seeMoreButton = await page.$('button.infinite-scroller__show-more-button, button[aria-label="See more jobs"]');
            
            if (seeMoreButton) {
                const isVisible = await seeMoreButton.isVisible();
                if (isVisible) {
                    console.log(`Step ${i + 1}: Clicking 'See more' button...`);
                    await seeMoreButton.scrollIntoViewIfNeeded();
                    await seeMoreButton.click().catch(e => console.log("Click failed, probably invisible:", e.message));
                    await page.waitForTimeout(4000);
                } else {
                    console.log(`Step ${i + 1}: 'See more' button found but not visible.`);
                }
            } else {
                console.log(`Step ${i + 1}: No 'See more' button found.`);
            }
        }

        const finalCount = await page.$$eval('.jobs-search__results-list li', els => els.length);
        console.log(`Final job count after navigation attempts: ${finalCount}`);

        if (finalCount > jobCount) {
            console.log("✅ SUCCESS: Successfully navigated and loaded more jobs.");
        } else {
            console.log("⚠️ INFO: No additional jobs loaded. This might be the end of the list or requires a different selector.");
        }

    } catch (err) {
        console.error(`❌ TEST FAILED: ${err.message}`);
    } finally {
        await browser.close();
    }
}

testPagination();
