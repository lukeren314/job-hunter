import { isWithinRange } from './geocoder.js';
import { GoogleGenerativeAI } from "@google/generative-ai";
import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { initDb } from './db.js';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

export async function evaluateJobFit(extractedData, resumeText, requirements) {

    // Deterministic Must-Have Check: Location
    const locationOk = await isWithinRange(extractedData.location);
    if (!locationOk && extractedData.work_type !== 'Remote') {
        return { fit_score: 0, reasoning: "Fails hard location requirement (outside 15 miles and not remote)." };
    }

    // AI Fit Scoring
    const model = genAI.getGenerativeModel({ model: "gemini-flash-latest" });
    const prompt = `
You are a recruiter. Rank the fit of this candidate for this job.
CANDIDATE RESUME:
${resumeText.substring(0, 3000)}

JOB DATA:
${JSON.stringify(extractedData, null, 2)}

REQUIREMENTS & PREFERENCES:
${JSON.stringify(requirements, null, 2)}

### SCORING HEURISTICS:
1. Seniority/Level Match (40%): Does the job level (Junior/Mid/Senior) match the candidate's experience? Avoid over/underselling.
2. Field Match (30%): How well does the tech stack (Cloud/Backend/Infra) align?
3. Skill Match (20%): Specific tool/language matches.
4. Preferences (10%): Salary match (> $150k), Prestige company match.

Return ONLY a JSON object:
{
  "fit_score": number (0-100),
  "reasoning": "Brief explanation of why this score was given, focusing on seniority alignment.",
  "matches": ["list of matching points"],
  "gaps": ["list of significant gaps"]
}
`;

    try {
        const result = await model.generateContent(prompt);
        const text = (await result.response).text();
        const jsonMatch = text.match(/\{[\s\S]*\}/);
        return JSON.parse(jsonMatch ? jsonMatch[0] : text);
    } catch (e) {
        if (e.message.includes('429')) {
            throw new Error('FATAL_GEMINI_LIMIT');
        }
        console.error("   ❌ Evaluation Error:", e.message);
        return null;
    }
}

export async function runEvaluator() {
    console.log("🚀 Starting Evaluation Stage...");
    const db = await initDb();

    const pendingJobs = await db.all(`
        SELECT j.*
        FROM jobs j
        LEFT JOIN evaluations e ON j.canonical_id = e.job_id
        WHERE e.job_id IS NULL
        LIMIT 50
    `);

    console.log(`   📂 Found ${pendingJobs.length} unevaluated jobs.`);
    if (pendingJobs.length === 0) return;

    const resumeText = fs.readFileSync(join(__dirname, '../config/resume.txt'), 'utf8');
    const requirements = JSON.parse(fs.readFileSync(join(__dirname, '../config/requirements.json'), 'utf8'));

    for (const job of pendingJobs) {
        try {
            console.log(`🧠 Evaluating: ${job.company} - ${job.title}`);
            const result = await evaluateJobFit(job, resumeText, requirements);
            
            if (result) {
                await db.run(
                    'INSERT OR REPLACE INTO evaluations (job_id, fit_score, reasoning) VALUES (?, ?, ?)',
                    [job.canonical_id, result.fit_score, result.reasoning]
                );
                console.log(`   ✨ Fit: ${result.fit_score}%`);
            }
        } catch (e) {
            if (e.message.startsWith('FATAL_')) {
                console.error(`🛑 ABORTING: ${e.message}`);
                throw e;
            }
            console.error(`   ⚠️ Evaluation loop error:`, e.message);
        }
    }
    console.log("✅ Evaluation Stage Finished.\n");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    runEvaluator().catch(err => console.error("Evaluator Fatal:", err));
}
