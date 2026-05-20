import { chromium } from 'playwright';
import dotenv from 'dotenv';

dotenv.config();

async function testSingleExtraction() {
    console.log("Starting surgical test: Single Job Extraction");
    
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    // Testing with a specific job URL (Sony New Grad position found in previous logs)
    const testUrl = 'https://www.linkedin.com/jobs/view/software-engineer-i-at-sony-interactive-entertainment-4412034983';
    
    console.log(`Navigating to: ${testUrl}`);
    
    try {
        await page.goto(testUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        
        // Wait for description to appear
        console.log("Waiting for description selector...");
        const descSelector = '.description__text';
        await page.waitForSelector(descSelector, { timeout: 15000 });

        const extraction = await page.evaluate(() => {
            const showMore = document.querySelector('.show-more-less-html__button--more');
            if (showMore) {
                showMore.click();
            }
            
            const desc = document.querySelector('.description__text');
            const title = document.querySelector('.top-card-layout__title')?.innerText;
            const company = document.querySelector('.topcard__org-name-link')?.innerText;
            
            return {
                title: title?.trim(),
                company: company?.trim(),
                description: desc ? desc.innerText.trim() : 'NOT_FOUND'
            };
        });

        console.log("--- Extraction Result ---");
        console.log(`Title: ${extraction.title}`);
        console.log(`Company: ${extraction.company}`);
        console.log(`Description Length: ${extraction.description.length}`);
        console.log(`Sample: ${extraction.description.substring(0, 200)}...`);
        console.log("--------------------------");

        if (extraction.description !== 'NOT_FOUND' && extraction.description.length > 100) {
            console.log("✅ SUCCESS: Core extraction logic is working.");
        } else {
            console.log("❌ FAILURE: Extraction returned empty or too short.");
        }

    } catch (err) {
        console.error(`❌ TEST FAILED: ${err.message}`);
    } finally {
        await browser.close();
    }
}

testSingleExtraction();
