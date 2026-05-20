# job-hunter

An AI-powered job hunting toolkit that discovers, evaluates, and applies to software engineering jobs automatically.

## Features

- **Job discovery** — crawls LinkedIn and company career pages for relevant listings
- **Evaluation** — scores jobs against your requirements (location, salary, role type, skill match)
- **Apply agent** — fills out job applications on any ATS (Ashby, Greenhouse, Lever, Workday, etc.) using your resume and personal info, without submitting
- **Report generation** — produces ranked job lists as Markdown reports

## Setup

### 1. Install dependencies

```bash
npm install
npx playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your API keys
```

You need a [Gemini API key](https://ai.google.dev/) (`GEMINI_API_KEY`). The other keys are only needed for the discovery features:
- `FIRECRAWL_API_KEY` — [Firecrawl](https://www.firecrawl.dev/) for web crawling
- `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` — [Browserbase](https://www.browserbase.com/) for cloud browser sessions

### 3. Configure your profile

```bash
cp config/personal_info.example.json config/personal_info.json
cp config/resume.example.txt config/resume.txt
cp config/requirements.example.json config/requirements.json
cp config/watchlist.example.json config/watchlist.json
```

Edit each file:
- `config/personal_info.json` — your contact info, LinkedIn/GitHub URLs, work authorization status
- `config/resume.txt` — plain-text version of your resume (used by the apply agent)
- `resume.pdf` — your resume PDF (used for file upload on application forms)
- `config/requirements.json` — your job preferences and scoring weights
- `config/watchlist.json` — job search queries to run

## Usage

### Apply to a job

Fill out (but do not submit) a job application:

```bash
node src/apply_agent.js <job-application-url>
```

The agent uses your `personal_info.json` and `resume.txt` to fill every field it can — contact info, work authorization, location yes/no questions, experience questions from your resume, and open-ended motivation questions. It stops before the final submit button and keeps the browser open for 30 seconds so you can review.

**Supported ATS platforms:** Ashby, Greenhouse, Lever, Workday, and others. For sites that embed the form in an iframe (e.g. Greenhouse widgets on company career pages), the agent detects the iframe URL and navigates to it automatically.

### Discover jobs

```bash
node src/main.js
```

Runs the configured watchlist queries, stores results in `data/jobs.db`, evaluates them against your requirements, and writes a ranked report to `reports/ranked_jobs.md`.

## Configuration

### `config/personal_info.json`

| Field | Description |
|---|---|
| `full_name` | Used for name fields on application forms |
| `email` / `phone` | Contact fields |
| `linkedin_url` / `github_url` / `portfolio_url` | Profile links |
| `location` | Used to answer location yes/no questions (e.g. "Are you based in San Francisco?") |
| `work_authorization` | Text answer for authorization fields |
| `sponsorship_required` | `"No"` / `"Yes"` |
| `current_company` / `current_title` | Current employer fields |
| `desired_salary` | Optional — salary expectation fields |
| `available_start_date` | Optional — start date fields |
| `pronouns` | Optional — pronoun fields |
| `application_source` | Optional — "How did you hear about us?" fields |

Any field missing from `personal_info.json` that the agent cannot answer from the resume will trigger an interactive prompt asking you for the value, which is then saved back to the file for future use.

### `config/requirements.json`

Controls how jobs are scored and filtered. Set your location center, remote preference, target salary, and scoring weights.

### `config/watchlist.json`

Array of search queries to run during discovery. Each entry specifies a platform (`linkedin`), search query, location, and result limit.

## Project structure

```
src/
  apply_agent.js     # AI agent that fills job application forms
  agent_tools.js     # Playwright browser tools used by the agent
  main.js            # Entry point for job discovery + evaluation pipeline
  crawler.js         # Scrapes job listings from career pages
  discovery.js       # Runs watchlist queries across platforms
  evaluator.js       # Scores jobs against requirements.json
  extractor.js       # Extracts structured job data from raw HTML
  db.js              # SQLite persistence
  generate_report.js # Produces ranked_jobs.md
  geocoder.js        # Resolves job location coordinates
  utils.js           # Shared utilities
config/
  personal_info.example.json
  resume.example.txt
  requirements.example.json
  watchlist.example.json
data/               # SQLite database (gitignored)
reports/            # Generated reports and screenshots (gitignored)
```
