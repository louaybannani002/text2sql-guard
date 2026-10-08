// Lighthouse audit of the running web UI (mobile + desktop); fails under the budget.
// Usage: pnpm lighthouse [url]   (default http://127.0.0.1:3000; needs Chrome installed)
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";

const url = process.argv[2] ?? "http://127.0.0.1:3000/";
const BUDGET = { performance: 90, accessibility: 90 };
const LIGHTHOUSE = "lighthouse@13.5.0";
mkdirSync("lighthouse", { recursive: true });

let failed = false;
for (const preset of ["mobile", "desktop"]) {
  const args = [
    "--yes",
    LIGHTHOUSE,
    url,
    "--only-categories=performance,accessibility,best-practices",
    "--chrome-flags=--headless=new --disable-gpu --no-first-run",
    "--output=json",
    "--output=html",
    `--output-path=lighthouse/${preset}`,
    "--quiet",
    ...(preset === "desktop" ? ["--preset=desktop"] : []),
  ];
  const run = spawnSync("npx", args, { stdio: "inherit", shell: process.platform === "win32" });
  if (run.status !== 0) {
    console.error(`${preset}: lighthouse failed to run`);
    failed = true;
    continue;
  }
  const report = JSON.parse(readFileSync(`lighthouse/${preset}.report.json`, "utf8"));
  const scores = Object.fromEntries(
    Object.values(report.categories).map((c) => [c.id, Math.round(c.score * 100)]),
  );
  console.log(`${preset.padEnd(8)}`, scores);
  for (const [category, minimum] of Object.entries(BUDGET)) {
    if (scores[category] < minimum) {
      console.error(`  ${category} ${scores[category]} < ${minimum}`);
      failed = true;
    }
  }
}
process.exit(failed ? 1 : 0);
