import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const RESUME_PATH = join(__dirname, '../resume.pdf');

function normalizeText(value = '') {
  return String(value).replace(/\s+/g, ' ').trim().toLowerCase();
}

function scoreMatch(candidate, query) {
  const haystack = normalizeText(candidate);
  const needle = normalizeText(query);
  if (!haystack || !needle) return 0;
  if (haystack === needle) return 100;
  if (haystack.includes(needle)) return 80;
  if (needle.includes(haystack)) return 65;

  const words = needle.split(/\W+/).filter(Boolean);
  if (!words.length) return 0;
  const matched = words.filter(word => haystack.includes(word)).length;
  return Math.round((matched / words.length) * 60);
}

async function findControl(page, selectorOrHint, allowedTypes = ['input', 'select', 'textarea']) {
  const direct = page.locator(selectorOrHint).first();
  try {
    if (await direct.count()) return direct;
  } catch {
    // Treat invalid CSS/Playwright selectors as natural-language hints.
  }

  const candidates = await getPageContent(page);
  const filtered = candidates.interactables.filter(item =>
    allowedTypes.includes(item.type) || allowedTypes.includes(item.tag)
  );
  const ranked = filtered
    .map(item => ({
      item,
      score: Math.max(
        scoreMatch(item.ref, selectorOrHint),
        scoreMatch(item.label, selectorOrHint),
        scoreMatch(item.name, selectorOrHint),
        scoreMatch(item.placeholder, selectorOrHint),
        scoreMatch(item.text, selectorOrHint),
        scoreMatch(item.ariaLabel, selectorOrHint)
      )
    }))
    .filter(match => match.score >= 45)
    .sort((a, b) => b.score - a.score);

  if (!ranked.length) {
    throw new Error(`Could not find a visible control matching "${selectorOrHint}"`);
  }

  return page.locator(ranked[0].item.selector).first();
}

async function findClickable(page, selectorOrHint, { allowTerminalSubmit = false } = {}) {
  const direct = page.locator(selectorOrHint).first();
  try {
    if (await direct.count()) {
      if (!allowTerminalSubmit && await isTerminalSubmitLocator(direct)) {
        throw new Error(`Refusing to click terminal submit/apply control "${selectorOrHint}"`);
      }
      return direct;
    }
  } catch (error) {
    if (/Refusing/.test(error.message)) throw error;
  }

  const snapshot = await getPageContent(page);
  const ranked = snapshot.interactables
    .filter(item => item.type === 'button' || item.type === 'link')
    .map(item => ({
      item,
      score: Math.max(
        scoreMatch(item.ref, selectorOrHint),
        scoreMatch(item.text, selectorOrHint),
        scoreMatch(item.label, selectorOrHint),
        scoreMatch(item.ariaLabel, selectorOrHint)
      )
    }))
    .filter(match => match.score >= 45)
    .sort((a, b) => b.score - a.score);

  if (!ranked.length) {
    throw new Error(`Could not find a visible clickable element matching "${selectorOrHint}"`);
  }
  if (!allowTerminalSubmit && ranked[0].item.isTerminalSubmit) {
    throw new Error(`Refusing to click terminal submit/apply control "${ranked[0].item.text || selectorOrHint}"`);
  }
  return page.locator(ranked[0].item.selector).first();
}

async function isTerminalSubmitLocator(locator) {
  return await locator.evaluate(el => {
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    return /^(submit|send application|submit application|complete application|final submit)$/i.test(text) ||
      /^apply$/i.test(text);
  }).catch(() => false);
}

export async function getPageContent(page) {
  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForTimeout(500).catch(() => {});

  // Extract visible controls with stable references and enough context for the LLM
  // to choose fields by meaning instead of brittle generated CSS.
  const result = await page.evaluate(() => {
    let nextRef = 1;
    const existingRefs = Array.from(document.querySelectorAll('[data-agent-ref]'))
      .map(el => Number((el.getAttribute('data-agent-ref') || '').replace('el-', '')))
      .filter(Number.isFinite);
    if (existingRefs.length) nextRef = Math.max(...existingRefs) + 1;

    const isVisible = el => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== 'hidden' &&
        style.display !== 'none' &&
        rect.width > 0 &&
        rect.height > 0 &&
        !el.disabled &&
        el.getAttribute('aria-hidden') !== 'true';
    };

    const textOf = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();

    const getRef = el => {
      if (!el.getAttribute('data-agent-ref')) {
        el.setAttribute('data-agent-ref', `el-${nextRef++}`);
      }
      return el.getAttribute('data-agent-ref');
    };

    const labelFor = el => {
      const pieces = [];
      if (el.id) {
        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (label) pieces.push(textOf(label));
      }
      const wrappingLabel = el.closest('label');
      if (wrappingLabel) pieces.push(textOf(wrappingLabel));
      const optionContainer = el.closest('[class*="option"], [role="radio"], [role="checkbox"]');
      if (optionContainer) pieces.push(textOf(optionContainer));
      const describedBy = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      for (const id of describedBy) {
        const described = document.getElementById(id);
        if (described) pieces.push(textOf(described));
      }
      const fieldContainer = el.closest('fieldset, [data-qa], [data-testid], .field, .form-field, .application-field, .ashby-application-form-field, .job-application-question');
      if (fieldContainer) {
        const heading = fieldContainer.querySelector('legend, label, [class*="label"], [class*="question"]');
        if (heading) pieces.push(textOf(heading));
        if (fieldContainer.tagName.toLowerCase() === 'fieldset') {
          pieces.push(textOf(fieldContainer));
        }
      }
      pieces.push(el.getAttribute('aria-label'), el.placeholder, el.name, el.id);
      return [...new Set(pieces.filter(Boolean))].join(' | ');
    };

    const optionData = el => {
      if (el.tagName.toLowerCase() === 'select') {
        return Array.from(el.options).map(option => ({
          text: textOf(option),
          value: option.value,
          selected: option.selected
        }));
      }
      if (el.type === 'radio') {
        const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`));
        return group.map(input => ({
          text: labelFor(input),
          value: input.value,
          selected: input.checked,
          selector: `[data-agent-ref="${getRef(input)}"]`
        }));
      }
      return undefined;
    };

    const interactables = [];
    document.querySelectorAll('input, select, textarea').forEach(el => {
      const tag = el.tagName.toLowerCase();
      const inputType = (el.type || tag).toLowerCase();
      if (inputType === 'hidden' || !isVisible(el)) return;

      const ref = getRef(el);

      interactables.push({
        type: tag === 'select' ? 'select' : tag === 'textarea' ? 'textarea' : 'input',
        ref,
        selector: `[data-agent-ref="${ref}"]`,
        tag,
        inputType,
        label: labelFor(el) || 'Unknown field',
        name: el.name || '',
        id: el.id || '',
        placeholder: el.placeholder || '',
        ariaLabel: el.getAttribute('aria-label') || '',
        required: Boolean(el.required || el.getAttribute('aria-required') === 'true'),
        value: inputType === 'password' ? '[redacted]' : el.value,
        checked: Boolean(el.checked),
        options: optionData(el)
      });
    });

    document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"]').forEach(el => {
      if (!isVisible(el)) return;
      const text = textOf(el) || el.value || el.getAttribute('aria-label') || '';
      if (!text || text.length > 50) return;
      const tag = el.tagName.toLowerCase();
      const inputType = (el.getAttribute('type') || '').toLowerCase();
      const isLikelyButton = 
        tag === 'button' ||
        tag === 'input' ||
        el.getAttribute('role') === 'button' ||
        el.classList.contains('button') ||
        el.classList.contains('btn') ||
        /apply|submit|continue|next|start|review|save|upload/i.test(text);

      if (isLikelyButton) {
        const ref = getRef(el);
        interactables.push({
          type: tag === 'a' ? 'link' : 'button',
          ref,
          selector: `[data-agent-ref="${ref}"]`,
          label: labelFor(el),
          text,
          tag,
          inputType,
          id: el.id || '',
          className: typeof el.className === 'string' ? el.className : '',
          ariaLabel: el.getAttribute('aria-label') || '',
          href: tag === 'a' ? el.href : '',
          isTerminalSubmit: /^(submit|send application|submit application|complete application|final submit)$/i.test(text) || /^apply$/i.test(text)
        });
      }
    });

    return {
      url: window.location.href,
      title: document.title,
      interactables: interactables.slice(0, 120),
      summary: document.body.innerText.replace(/\s+/g, ' ').trim().substring(0, 2500)
    };
  });

  // If the main frame had no interactables, scan iframes for the application form
  if (!result.interactables.length) {
    const ATS_PATTERNS = /greenhouse\.io|lever\.co|workday\.com|ashbyhq\.com|myworkdayjobs\.com|icims\.com|breezy\.hr|recruitee\.com|smartrecruiters\.com|taleo\.net|bamboohr\.com|jobvite\.com|apply\.|careers\./i;
    const SKIP_PATTERNS = /recaptcha|captcha|analytics|tracking|pixel|tag|gtm|ads|doubleclick|facebook\.com|twitter\.com|youtube\.com|maps\.google|googleapis\.com\/static|content\.googleapis/i;

    const frames = page.frames().filter(f => f !== page.mainFrame());

    // First pass: look for known ATS iframes
    let found = null;
    for (const frame of frames) {
      const frameUrl = frame.url();
      if (!frameUrl || frameUrl === 'about:blank') continue;
      if (SKIP_PATTERNS.test(frameUrl)) continue;
      if (ATS_PATTERNS.test(frameUrl)) {
        found = frameUrl;
        break;
      }
    }

    // Second pass: any non-skip cross-origin iframe with form elements
    if (!found) {
      for (const frame of frames) {
        const frameUrl = frame.url();
        if (!frameUrl || frameUrl === 'about:blank') continue;
        if (SKIP_PATTERNS.test(frameUrl)) continue;
        const frameResult = await frame.evaluate(() => {
          const items = document.querySelectorAll('input:not([type=hidden]), select, textarea');
          return { count: items.length };
        }).catch(() => null);
        if (frameResult?.count > 0) {
          found = frameUrl;
          break;
        }
      }
    }

    if (found) {
      result.iframeUrl = found;
      result.iframeHint = `Application form is inside an iframe at ${found}. Navigate directly to that URL to interact with the form.`;
    }
  }

  return result;
}

export async function takeScreenshot(page, name) {
  const screenshotPath = join(__dirname, `../reports/screenshot_${name}_${Date.now()}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`Screenshot saved to ${screenshotPath}`);
  return screenshotPath;
}

export async function waitForTimeout(page, ms) {
  console.log(`Waiting for ${ms}ms...`);
  await page.waitForTimeout(ms);
}

export async function fillField(page, selector, value) {
  console.log(`Filling ${selector} with ${value}`);
  const control = await findControl(page, selector);
  const tagName = await control.evaluate(el => el.tagName.toLowerCase());
  const inputType = await control.evaluate(el => (el.type || '').toLowerCase());

  if (tagName === 'select') {
    const result = await control.selectOption({ label: value }).catch(async () =>
      control.selectOption({ value })
    );
    if (!result.length) throw new Error(`Could not select option "${value}" for ${selector}`);
    return;
  }

  if (inputType === 'checkbox') {
    const desired = !/^(false|no|unchecked|0)$/i.test(String(value).trim());
    if (desired) await control.check();
    else await control.uncheck();
    return;
  }

  if (inputType === 'radio') {
    const groupName = await control.getAttribute('name');
    if (!groupName) {
      await control.check();
      return;
    }
    const snapshot = await getPageContent(page);
    const radioOptions = snapshot.interactables
      .filter(item => item.name === groupName)
      .flatMap(item => item.options || [item]);
    const radio = radioOptions
      .filter(item => item.selector)
      .map(item => ({ item, score: Math.max(scoreMatch(item.text, value), scoreMatch(item.value, value)) }))
      .sort((a, b) => b.score - a.score)[0];
    if (!radio || radio.score < 45) throw new Error(`Could not find radio option "${value}" for ${selector}`);
    await page.locator(radio.item.selector).check();
    return;
  }

  await control.fill(String(value));
}

export async function clickElement(page, selector) {
  console.log(`Clicking ${selector}`);
  const clickable = await findClickable(page, selector);
  await Promise.all([
    page.waitForLoadState('domcontentloaded', { timeout: 10000 }).catch(() => {}),
    clickable.click().catch(async error => {
      if (!/outside of the viewport|not visible|Timeout/.test(error.message)) throw error;
      await clickable.evaluate(el => el.click());
    })
  ]);
  await page.waitForTimeout(500);
}

export async function uploadResume(page, selector) {
  console.log(`Uploading resume from ${RESUME_PATH} to ${selector}`);
  if (fs.existsSync(RESUME_PATH)) {
    const input = await findControl(page, selector, ['input']);
    const type = await input.evaluate(el => (el.type || '').toLowerCase());
    if (type !== 'file') {
      throw new Error(`Matched "${selector}", but it is not a file input`);
    }
    await input.setInputFiles(RESUME_PATH);
  } else {
    throw new Error(`Resume not found at ${RESUME_PATH}`);
  }
}

export function updatePersonalInfo(newData) {
  const infoPath = join(__dirname, '../config/personal_info.json');
  const currentInfo = JSON.parse(fs.readFileSync(infoPath, 'utf8'));
  const updatedInfo = { ...currentInfo, ...newData };
  fs.writeFileSync(infoPath, JSON.stringify(updatedInfo, null, 2));
  console.log('Updated personal_info.json with new memory.');
}
