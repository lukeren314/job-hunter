import sqlite3 from 'sqlite3';
import { open } from 'sqlite';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function generateReport() {
    console.log("Generating Modular Markdown report...");
    const dbPath = join(__dirname, '../data/jobs.db');
    const reportPath = join(__dirname, '../reports/ranked_jobs.md');

    try {
        const db = await open({
            filename: dbPath,
            driver: sqlite3.Database
        });

        // Join jobs and evaluations
        const results = await db.all(`
            SELECT 
                j.title, 
                j.company, 
                j.location, 
                j.salary_min, 
                j.salary_max, 
                j.level, 
                j.work_type,
                j.source_url,
                e.fit_score, 
                e.reasoning
            FROM jobs j
            JOIN evaluations e ON j.canonical_id = e.job_id
            ORDER BY e.fit_score DESC

        `);

        let md = `# 🎯 Job Hunter: Ranked Report\n\n`;
        md += `Generated on: ${new Date().toLocaleString()}\n\n`;
        
        md += `| Score | Title | Company | Location | Salary Range | Type | Link |\n`;
        md += `| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n`;

        results.forEach(r => {
            const title = r.title.length > 35 ? r.title.substring(0, 32) + "..." : r.title;
            const salary = (r.salary_min && r.salary_max) ? `\$${(r.salary_min/1000).toFixed(0)}k - \$${(r.salary_max/1000).toFixed(0)}k` : 'Not Mentioned';
            md += `| **${r.fit_score}%** | ${title} | ${r.company} | ${r.location} | ${salary} | ${r.work_type} | [View](${r.source_url}) |\n`;
        });

        md += `\n## 📝 Detailed Reasoning\n\n`;

        results.filter(r => r.fit_score >= 70).forEach(r => {
            md += `### ${r.title} @ ${r.company} (${r.fit_score}%)\n\n`;
            md += `- **Location:** ${r.location} (${r.work_type})\n`;
            md += `- **Level:** ${r.level}\n`;
            md += `- **Reasoning:** ${r.reasoning}\n`;
            md += `- **Job URL:** ${r.source_url}\n\n`;
            md += `--- \n\n`;
        });

        if (!fs.existsSync(dirname(reportPath))) {
            fs.mkdirSync(dirname(reportPath), { recursive: true });
        }
        fs.writeFileSync(reportPath, md);
        console.log(`✅ Report successfully generated at: ${reportPath}`);

    } catch (err) {
        console.error(`❌ Failed to generate report: ${err.message}`);
    }
}

generateReport();
