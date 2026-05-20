import { chromium } from 'playwright';
import { GoogleGenerativeAI } from "@google/generative-ai";
import dotenv from 'dotenv';
import fs from 'fs';
import readline from 'readline';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import * as tools from './agent_tools.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({
  model: "gemini-flash-latest",
  toolConfig: {
    functionCallingConfig: {
      mode: "ANY"
    }
  },
  tools: [
    {
      functionDeclarations: [
        {
          name: "navigate",
          description: "Navigate to a URL",
          parameters: {
            type: "OBJECT",
            properties: {
              url: { type: "STRING" }
            },
            required: ["url"]
          }
        },
        {
          name: "getPageContent",
          description: "Get visible interactable elements, stable selectors, labels, options, and page text for the current page",
          parameters: { type: "OBJECT", properties: {} }
        },
        {
          name: "fillField",
          description: "Fill a text field, textarea, select, checkbox, or radio group. Prefer the stable selector from getPageContent, but a label/name hint also works.",
          parameters: {
            type: "OBJECT",
            properties: {
              selector: { type: "STRING", description: "Stable selector/ref from getPageContent, or a label/name hint such as 'First name'" },
              value: { type: "STRING", description: "Text to enter, option label/value to choose, or yes/no for checkboxes" }
            },
            required: ["selector", "value"]
          }
        },
        {
          name: "clickElement",
          description: "Click a non-final button or link. The tool refuses obvious final submit/application buttons.",
          parameters: {
            type: "OBJECT",
            properties: {
              selector: { type: "STRING", description: "Stable selector/ref from getPageContent, visible text, or label hint" }
            },
            required: ["selector"]
          }
        },
        {
          name: "uploadResume",
          description: "Upload the resume file to a file input",
          parameters: {
            type: "OBJECT",
            properties: {
              selector: { type: "STRING" }
            },
            required: ["selector"]
          }
        },
        {
          name: "requestUserInput",
          description: "Ask the user for information that is not available in personal_info.json",
          parameters: {
            type: "OBJECT",
            properties: {
              question: { type: "STRING" },
              fieldKey: { type: "STRING", description: "The key to save this info under in personal_info.json (e.g. 'favorite_color')" }
            },
            required: ["question", "fieldKey"]
          }
        },
        {
          name: "signalCompletion",
          description: "Signal that the form is filled as much as possible without submitting",
          parameters: { type: "OBJECT", properties: {} }
        },
        {
          name: "waitForTimeout",
          description: "Wait for a specified amount of time in milliseconds",
          parameters: {
            type: "OBJECT",
            properties: {
              ms: { type: "NUMBER" }
            },
            required: ["ms"]
          }
        }
      ]
    }
  ]
});

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function askUser(question) {
  if (!process.stdin.isTTY || rl.closed) {
    throw new Error(`User input required but stdin is not interactive: ${question}`);
  }
  return new Promise(resolve => rl.question(`[USER REQUIRED] ${question}: `, resolve));
}

function retryDelayMs(error) {
  const retryInfo = error.errorDetails?.find?.(detail => detail['@type']?.includes('RetryInfo'));
  const retryDelay = retryInfo?.retryDelay;
  if (retryDelay) {
    const seconds = Number(String(retryDelay).replace(/s$/, ''));
    if (Number.isFinite(seconds)) return Math.min(Math.max(seconds * 1000, 1000), 90000);
  }

  const match = error.message?.match(/retry in ([\d.]+)s/i) || error.message?.match(/retryDelay":"(\d+)s/i);
  if (match) return Math.min(Math.max(Number(match[1]) * 1000, 1000), 90000);
  return 15000;
}

async function sendMessageWithRetry(chat, message, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await chat.sendMessage(message);
    } catch (error) {
      lastError = error;
      if (error.status !== 429 || attempt === attempts) throw error;
      const waitMs = retryDelayMs(error);
      console.warn(`Gemini quota window hit; retrying in ${Math.ceil(waitMs / 1000)}s...`);
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
  }
  throw lastError;
}

function normalizeText(value = '') {
  return String(value).replace(/\s+/g, ' ').trim().toLowerCase();
}

const METRO_ALIASES = {
  'san francisco': ['san francisco', 'bay area', 'sf bay', 'silicon valley', 'san jose', 'east bay', 'greater san francisco'],
  'new york': ['new york', 'nyc', 'new york city', 'manhattan', 'brooklyn', 'greater new york'],
  'los angeles': ['los angeles', 'la ', 'l.a.', 'socal', 'southern california'],
  'seattle': ['seattle', 'puget sound', 'bellevue', 'redmond'],
  'chicago': ['chicago', 'chicagoland'],
  'boston': ['boston', 'greater boston'],
  'austin': ['austin'],
  'denver': ['denver', 'boulder'],
  'miami': ['miami', 'south florida'],
  'portland': ['portland'],
  'atlanta': ['atlanta'],
  'dallas': ['dallas', 'dfw', 'fort worth'],
  'houston': ['houston'],
  'washington': ['washington dc', 'washington, dc', 'dc metro', 'northern virginia', 'nova'],
};

function isUserInArea(label, userLocation) {
  const userLoc = normalizeText(userLocation || '');
  for (const [, aliases] of Object.entries(METRO_ALIASES)) {
    const mentionsArea = aliases.some(alias => label.includes(alias));
    if (!mentionsArea) continue;
    return aliases.some(alias => userLoc.includes(alias));
  }
  return null;
}

function getKnownAnswer(field, personalInfo) {
  const label = normalizeText([
    field.label,
    field.name,
    field.id,
    field.placeholder,
    field.ariaLabel
  ].filter(Boolean).join(' '));

  if (!label) return undefined;
  const isYesOption = /^yes\b/.test(label);
  const isNoOption = /^no\b/.test(label);
  const isChoice = field.inputType === 'checkbox' || field.inputType === 'radio';

  if (field.inputType === 'file' && /resume|cv/.test(label)) return '__UPLOAD_RESUME__';
  if (isChoice && /located in the united states|based in the united states|eligible to work|legally authorized|work authorization/.test(label)) {
    if (isYesOption) return 'yes';
    if (isNoOption) return 'no';
  }
  if (isChoice && /sponsor|visa|h1b/.test(label)) {
    if (isNoOption) return 'yes';
    if (isYesOption) return 'no';
  }
  if (isChoice && /based in|located in|do you (?:currently )?(?:live|reside|work) in/.test(label)) {
    const inArea = isUserInArea(label, personalInfo.location);
    if (inArea !== null) {
      if (isYesOption) return inArea ? 'yes' : 'no';
      if (isNoOption) return inArea ? 'no' : 'yes';
    }
  }
  if (/full name|legal name|preferred name|\bname\b/.test(label) && !/company|employer|reference/.test(label)) return personalInfo.full_name;
  if (/first name|given name/.test(label)) return personalInfo.first_name || personalInfo.full_name?.split(/\s+/)[0];
  if (/last name|family name|surname/.test(label)) return personalInfo.last_name || personalInfo.full_name?.split(/\s+/).slice(1).join(' ');
  if (/email|e-mail/.test(label)) return personalInfo.email;
  if (/phone|mobile|telephone/.test(label)) return personalInfo.phone;
  if (/linkedin/.test(label)) return personalInfo.linkedin_url;
  if (/github/.test(label)) return personalInfo.github_url;
  if (/portfolio|website|personal site/.test(label)) return personalInfo.portfolio_url || personalInfo.github_url;
  if (/current company|employer/.test(label)) return personalInfo.current_company;
  if (/current title|job title|current role/.test(label)) return personalInfo.current_title;
  if (/authorized|work authorization|eligible to work|legally authorized/.test(label)) return personalInfo.work_authorization || 'Yes';
  if (/sponsor|visa/.test(label)) return personalInfo.sponsorship_required || 'No';
  if (/location|city|address/.test(label) && !/relocat/.test(label)) return personalInfo.location;
  if (/salary|compensation|pay expectation/.test(label)) return personalInfo.desired_salary;
  if (/start date|available/.test(label)) return personalInfo.available_start_date;
  if (/pronoun/.test(label)) return personalInfo.pronouns;
  if (/how did you hear|source/.test(label)) return personalInfo.application_source || 'Company careers page';

  return undefined;
}

function annotateSnapshot(snapshot, personalInfo) {
  return {
    ...snapshot,
    interactables: snapshot.interactables.map(item => {
      if (!['input', 'textarea', 'select'].includes(item.type)) return item;
      if (!needsValue(item)) return item;
      const suggestedValue = getKnownAnswer(item, personalInfo);
      if (!suggestedValue) return item;
      return { ...item, suggestedValue };
    })
  };
}

function compactSnapshot(snapshot) {
  const groupKey = item => {
    if (item.inputType !== 'checkbox' && item.inputType !== 'radio') return '';
    const label = String(item.label || '');
    const parts = label.split('|').map(part => part.trim()).filter(Boolean);
    return parts[1] || item.name || item.id || label;
  };
  const checkedGroups = new Set(snapshot.interactables
    .filter(item => (item.inputType === 'checkbox' || item.inputType === 'radio') && item.checked)
    .map(groupKey)
    .filter(Boolean));

  const visibleToAgent = snapshot.interactables.filter(item => {
    const label = normalizeText(item.label || item.text || '');
    if (!item.required && /gender|race|veteran status|disability|decline to self-identify|other \| type here|unknown field/.test(label)) {
      return false;
    }
    if ((item.inputType === 'checkbox' || item.inputType === 'radio') && checkedGroups.has(groupKey(item)) && !item.checked) {
      return false;
    }
    return true;
  });

  return {
    url: snapshot.url,
    title: snapshot.title,
    summary: snapshot.summary?.slice(0, 900),
    remainingRequired: visibleToAgent.filter(item => item.required && needsValue(item)).length,
    interactables: visibleToAgent.map(item => {
      if (item.type === 'button' || item.type === 'link') {
        return {
          type: item.type,
          selector: item.selector,
          text: item.text,
          href: item.href,
          isTerminalSubmit: item.isTerminalSubmit
        };
      }

      const compact = {
        type: item.type,
        selector: item.selector,
        inputType: item.inputType,
        label: item.label,
        required: item.required,
        value: item.value,
        checked: item.checked,
        suggestedValue: item.suggestedValue
      };
      if (item.options?.length) {
        compact.options = item.options.slice(0, 20).map(option => ({
          text: option.text,
          value: option.value,
          selected: option.selected,
          selector: option.selector
        }));
      }
      return compact;
    })
  };
}

function needsValue(field) {
  if (field.inputType === 'file') return !field.value;
  if (field.inputType === 'checkbox' || field.inputType === 'radio') return !field.checked;
  return !String(field.value || '').trim();
}

async function getAnnotatedPage(page, personalInfo) {
  return annotateSnapshot(await tools.getPageContent(page), personalInfo);
}

async function prefillKnownFields(page, personalInfo) {
  const filled = [];
  let snapshot = await getAnnotatedPage(page, personalInfo);

  for (const field of snapshot.interactables) {
    if (!['input', 'textarea', 'select'].includes(field.type)) continue;
    if (!field.suggestedValue || !needsValue(field)) continue;

    const shouldAutofill = field.required ||
      /full name|first name|last name|email|phone|linkedin|github|portfolio|website|location|work authorization|sponsor|visa|current company|current title/i.test(field.label || '');
    if (!shouldAutofill) continue;

    try {
      if (field.suggestedValue === '__UPLOAD_RESUME__') {
        await tools.uploadResume(page, field.selector);
        filled.push({ selector: field.selector, label: field.label, action: 'uploadedResume' });
      } else {
        await tools.fillField(page, field.selector, field.suggestedValue);
        filled.push({ selector: field.selector, label: field.label, value: field.suggestedValue });
      }
    } catch (error) {
      filled.push({ selector: field.selector, label: field.label, error: error.message });
    }

    if (filled.length >= 12) break;
  }

  if (filled.length) {
    snapshot = await getAnnotatedPage(page, personalInfo);
  }

  return { snapshot, filled };
}

async function preparePageForAgent(page, personalInfo) {
  const actions = [];
  let snapshot = await getAnnotatedPage(page, personalInfo);
  const fields = snapshot.interactables.filter(item => ['input', 'textarea', 'select'].includes(item.type));
  const startControl = snapshot.interactables.find(item =>
    (item.type === 'button' || item.type === 'link') &&
    !item.isTerminalSubmit &&
    /^(apply for this job|apply now|start application|begin application)$/i.test(item.text || '')
  );

  if (!fields.length && startControl) {
    await tools.clickElement(page, startControl.selector);
    actions.push({ action: 'clickedStart', selector: startControl.selector, text: startControl.text });
  }

  const prefill = await prefillKnownFields(page, personalInfo);
  snapshot = prefill.snapshot;
  actions.push(...prefill.filled);
  return { snapshot, actions };
}

function markReadyIfDone(toolResult, compactPage) {
  if (compactPage.interactables?.length === 0) {
    return {
      ...toolResult,
      status: 'no_elements',
      message: 'No interactive elements found on this page. Check the page summary/title to understand what is visible. The form may be inside an iframe — try navigating to a direct application URL (e.g. add /apply to the current URL) or look for an "Apply" link in the page summary.'
    };
  }
  if (compactPage.remainingRequired === 0) {
    return {
      ...toolResult,
      status: 'ready_for_review',
      message: 'All detected required fields are filled. Check if there is a Next/Continue button; if not, call signalCompletion.'
    };
  }
  return toolResult;
}

async function runAgent(targetUrl) {
  console.log(`🤖 Agent starting for: ${targetUrl}`);
  
  const browser = await chromium.launch({ headless: process.env.HEADLESS === 'true' ? true : false });
  const context = await browser.newContext({
    viewport: { width: 1365, height: 900 },
    acceptDownloads: true
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.setDefaultNavigationTimeout(45000);
  const personalInfo = JSON.parse(fs.readFileSync(join(__dirname, '../config/personal_info.json'), 'utf8'));
  const resumeText = fs.existsSync(join(__dirname, '../config/resume.txt'))
    ? fs.readFileSync(join(__dirname, '../config/resume.txt'), 'utf8').slice(0, 5000)
    : '';
  
  const chat = model.startChat({
    history: [
      {
        role: "user",
        parts: [{ text: `You are an automated job application agent. Your goal is to fill out the job application at the provided URL.

        CRITICAL RULES:
        0. YOU MUST ALWAYS RESPOND WITH A TOOL CALL. Never respond with plain text. Every single response must invoke exactly one tool. If you think you are done, call signalCompletion. If you need to do something else, call the appropriate tool. No exceptions.
        1. ALWAYS use getPageContent after navigate or clickElement. The page may change, reveal new fields, or open a multi-step form.
        2. Prefer selectors exactly as returned by getPageContent, e.g. [data-agent-ref="el-4"]. If a selector fails, retry once using a human label/name hint.
        3. Fill every clearly answerable required field using MY PERSONAL INFO and RESUME TEXT. getPageContent may include suggestedValue on fields; use it when it matches the field.
        4. For work authorization and sponsorship: use the values in MY PERSONAL INFO.
        5. For location questions (e.g. "Are you based in [City]?"): compare MY PERSONAL INFO location against the city/region mentioned. Answer accurately.
        6. For experience and skills questions (e.g. "Do you have experience with Kubernetes?", "Years of experience with X?"): answer based on MY RESUME TEXT. If the resume clearly shows the skill, answer yes/provide relevant detail. If the skill isn't on the resume, answer honestly (no / 0 years) or use requestUserInput if genuinely uncertain.
        7. For open-ended motivation questions (e.g. "Why do you want to work here?", "What excites you about this role?"): write a concise, genuine answer grounded in MY RESUME TEXT and what the job posting suggests about the company. Do NOT make up facts; base it on the applicant's actual background.
        8. If a tool returns status "no_elements", the form may be inside an iframe. If the result includes iframeUrl, navigate directly to that URL. Otherwise, try appending /apply to the current URL or look at the page summary/title to find an application link.
        9. If you do not see any fields, look for and click a non-final button like "Apply for this job", "Start application", "Continue", or "Next" to advance the form.
        10. NEVER click a final submission control. Do not click buttons named exactly "Submit", "Submit Application", "Send Application", "Complete Application", or equivalent.
        11. When a tool result contains status "ready_for_review", it means all currently visible required fields are filled. At that point: check if there is a "Next", "Continue", "Review", or similar non-submit navigation button in the page interactables. If yes, click it to proceed to the next page. If no such button exists and the form appears complete, call signalCompletion.
        12. Call signalCompletion only when all pages of the application are filled and no further non-submit navigation is available. Optional EEOC/self-identification fields may be left blank.
        13. If a required field cannot be answered from the provided info/resume, call requestUserInput with a reusable fieldKey.
        14. Do not request screenshots. Use getPageContent and tool results for state.

        MY PERSONAL INFO:
        ${JSON.stringify(personalInfo, null, 2)}

        RESUME TEXT:
        ${resumeText}

        If you need information that is not here, use 'requestUserInput'.

        START:
        1. Navigate to: ${targetUrl}
        2. Then get page content to see what to do next.` }]
      }
    ]
  });

  let step = 1;
  let finished = false;

  while (!finished && step <= 40) {
    console.log(`\n--- Step ${step} ---`);
    let result;
    try {
      result = await sendMessageWithRetry(chat, "What is your next action?");
    } catch (error) {
      console.error("Agent model call failed:", error.message);
      break;
    }
    const calls = result.response.functionCalls();
    
    if (!calls || calls.length === 0) {
      console.log("Agent finished or didn't return a tool call.");
      console.log("Response:", result.response.text());
      break;
    }

    const responses = [];

    for (const call of calls) {
      console.log(`Action: ${call.name}`, call.args);

      let toolResult;
      try {
        switch (call.name) {
          case 'navigate':
            await page.goto(call.args.url, { waitUntil: 'commit', timeout: 45000 });
            await page.waitForLoadState('domcontentloaded', { timeout: 15000 }).catch(() => {});
            await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
            {
              const { snapshot, actions } = await preparePageForAgent(page, personalInfo);
              const compact = compactSnapshot(snapshot);
              toolResult = markReadyIfDone({
                status: "success",
                currentUrl: page.url(),
                actions,
                page: compact
              }, compact);
            }
            break;
          case 'getPageContent': {
            const { snapshot, actions } = await preparePageForAgent(page, personalInfo);
            const compact = compactSnapshot(snapshot);
            toolResult = markReadyIfDone(compact, compact);
            if (actions.length) toolResult.actions = actions;
            console.log(`[DEBUG] Page Content: ${snapshot.interactables.length} elements found. URL: ${snapshot.url}`);
            if (snapshot.interactables.length > 0) {
              console.log(`[DEBUG] First 5 elements:`, JSON.stringify(snapshot.interactables.slice(0, 5), null, 2));
            } else {
              console.log(`[DEBUG] Page title: "${snapshot.title}" | Summary: "${snapshot.summary?.slice(0, 300)}"`);
              if (snapshot.iframeUrl) console.log(`[DEBUG] Iframe detected at: ${snapshot.iframeUrl}`);
            }
            break;
          }
          case 'fillField': {
            await tools.fillField(page, call.args.selector, call.args.value);
            const { snapshot, actions } = await preparePageForAgent(page, personalInfo);
            const compact = compactSnapshot(snapshot);
            toolResult = markReadyIfDone({
              status: "success",
              currentUrl: page.url(),
              actions,
              page: compact
            }, compact);
            break;
          }
          case 'clickElement': {
            await tools.clickElement(page, call.args.selector);
            const { snapshot, actions } = await preparePageForAgent(page, personalInfo);
            const compact = compactSnapshot(snapshot);
            toolResult = markReadyIfDone({
              status: "success",
              currentUrl: page.url(),
              actions,
              page: compact
            }, compact);
            break;
          }
          case 'uploadResume': {
            await tools.uploadResume(page, call.args.selector);
            const { snapshot, actions } = await preparePageForAgent(page, personalInfo);
            const compact = compactSnapshot(snapshot);
            toolResult = markReadyIfDone({
              status: "success",
              currentUrl: page.url(),
              actions,
              page: compact
            }, compact);
            break;
          }
          case 'waitForTimeout':
            await tools.waitForTimeout(page, call.args.ms);
            toolResult = { status: "success" };
            break;
          case 'requestUserInput': {
            const answer = await askUser(call.args.question);
            tools.updatePersonalInfo({ [call.args.fieldKey]: answer });
            toolResult = { status: "success", answer };
            break;
          }
          case 'signalCompletion':
            console.log("✅ Agent signals completion!");
            finished = true;
            toolResult = { status: "done", currentUrl: page.url() };
            break;
          default:
            toolResult = { status: "error", message: "Unknown tool" };
        }
      } catch (error) {
        console.error(`Tool Error (${call.name}):`, error.message);
        if (call.name === 'requestUserInput') {
          finished = true;
        }
        toolResult = {
          status: call.name === 'requestUserInput' ? "needs_user_input" : "error",
          message: error.message,
          guidance: "Call getPageContent, choose a currently visible stable selector, or retry with a label/name hint."
        };
      }

      responses.push({
        functionResponse: {
          name: call.name,
          response: toolResult
        }
      });

      if (finished) break;
    }

    try {
      await sendMessageWithRetry(chat, responses);
    } catch (error) {
      console.error("Agent model response handling failed:", error.message);
      break;
    }

    step++;
  }

  console.log("\nAgent loop finished. Keeping browser open for 30s for review...");
  await new Promise(r => setTimeout(r, 30000));
  await browser.close();
  rl.close();
}

const target = process.argv[2];
if (!target) {
  console.error("Usage: node src/apply_agent.js <job-application-url>");
  process.exit(1);
}
runAgent(target);
