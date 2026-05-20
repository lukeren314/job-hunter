import { DiscoveryEngine } from './discovery.js';
import { runExtractor } from './extractor.js';
import { runEvaluator } from './evaluator.js';

async function main() {
    console.log("🏁 Starting Job-Hunter Full Pipeline...\n");

    try {
        // Stage 1 + 2: Discovery and Extraction run in parallel.
        // The extractor polls for pending URLs while discovery is still crawling,
        // then exits once discovery is done and the queue is drained.
        let discoveryDone = false;
        const discovery = new DiscoveryEngine();

        await Promise.all([
            discovery.run().finally(() => { discoveryDone = true; }),
            runExtractor(() => discoveryDone),
        ]);

        // Stage 3: Evaluation runs after all jobs are extracted.
        await runEvaluator();

        console.log("🏁 Pipeline Run Complete. Run 'node src/generate_report.js' to see results.");
    } catch (err) {
        console.error("🏁 Pipeline Fatal Error:", err);
    }
}

main();
