const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  // Use a common User-Agent to avoid immediate bot detection
  await page.setExtraHTTPHeaders({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
  });

  const url = 'https://www.linkedin.com/jobs/search/?keywords=software%20engineer&location=Los%20Angeles%20Metropolitan%20Area&distance=25';
  
  console.log(`Navigating to: ${url}`);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    
    // Give it a bit more time to settle
    await page.waitForTimeout(5000);

    // Wait for the job list or an error/empty state
    const jobListFound = await page.waitForSelector('.jobs-search__results-list, .results-context-header', { timeout: 20000 }).catch(() => null);
    
    if (!jobListFound) {
      console.log('Job list selector not found. LinkedIn might be blocking or showing a different view.');
      await page.screenshot({ path: 'not_found.png' });
      return;
    }

    const jobs = await page.$$eval('.jobs-search__results-list li', elements => {
      return elements.map(el => {
        const titleEl = el.querySelector('.base-search-card__title');
        const companyEl = el.querySelector('.base-search-card__subtitle');
        const linkEl = el.querySelector('.base-card__full-link');
        return {
          title: titleEl ? titleEl.innerText.trim() : null,
          company: companyEl ? companyEl.innerText.trim() : null,
          link: linkEl ? linkEl.getAttribute('href') : null
        };
      });
    });

    console.log(`Found ${jobs.length} jobs on initial load.`);
    console.log('Top 3 jobs:', JSON.stringify(jobs.slice(0, 3), null, 2));

    // Check for pagination
    const hasPagination = await page.$('.infinite-scroller') !== null;
    console.log(`Infinite scrolling/Pagination present: ${hasPagination}`);

    // Check if we can extract the job detail HTML
    if (jobs.length > 0) {
      console.log('Attempting to extract detail for the first job...');
      
      // Close any initial modal if present
      const modalClose = await page.$('button[aria-label="Dismiss"]');
      if (modalClose) {
        console.log('Closing initial modal...');
        await modalClose.click();
      }

      // LinkedIn Guest view often uses direct links to job pages rather than a side pane.
      // Let's try to visit the first job link directly to see the description structure.
      const firstJobLink = jobs[0].link;
      console.log(`Navigating directly to job: ${firstJobLink}`);
      await page.goto(firstJobLink, { waitUntil: 'networkidle' });

      // Common selectors for description on LinkedIn guest pages
      const descriptionSelector = '.description__text';
      await page.waitForSelector(descriptionSelector, { timeout: 10000 });

      const description = await page.$eval(descriptionSelector, el => el.innerText.trim());
      console.log('Job Description Extracted (first 200 chars):');
      console.log(description.substring(0, 200) + '...');

      // Check for 'Show more' button which might hide tokens
      const showMore = await page.$('.show-more-less-html__button--more');
      console.log(`'Show more' button present: ${!!showMore}`);
    }

  } catch (err) {
    console.error('Error during research:', err.message);
    // Take a screenshot on failure for debugging
    await page.screenshot({ path: 'error.png' });
  } finally {
    await browser.close();
  }
})();
