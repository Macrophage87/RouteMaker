// The cue bench from the command line (src/lib/cueBench.ts). From frontend/:
//
//   node scripts/cueBench.ts                 check every fixture against its kept transcript; list the findings
//   node scripts/cueBench.ts --update        write the transcripts and the shared cue rows afresh
//   node scripts/cueBench.ts --out DIR       write the transcripts to DIR (run in two checkouts, then diff -ru the two)
//   node scripts/cueBench.ts kenyon-warder   one fixture (any of the above)
//
// The fixtures are fixtures/cues/*.json (scripts/cue_bench_capture.py); the transcripts fixtures/cues/transcripts/,
// the shared rows fixtures/cues/expected/. A change in the transcripts is every cue a change touched.
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { fixtureTranscript, sharedRows, type CueFixture } from "../src/lib/cueBench.ts";

const root = new URL("../../fixtures/cues/", import.meta.url);
const args = process.argv.slice(2);
const update = args.includes("--update");
const outAt = args.indexOf("--out");
const out = outAt >= 0 ? args[outAt + 1] : null;
const names = args.filter((a, i) => !a.startsWith("--") && (outAt < 0 || i !== outAt + 1));
const all = readdirSync(root)
  .filter((f) => f.endsWith(".json") && f !== "trips.json")
  .map((f) => f.slice(0, -5))
  .sort();
const chosen = names.length ? names : all;
let changed = 0;
let findings = 0;
for (const name of chosen) {
  if (!all.includes(name)) {
    console.error(`No fixture ${name}: one of ${all.join(", ")}`);
    process.exit(2);
  }
  const fixture = JSON.parse(readFileSync(new URL(`${name}.json`, root), "utf8")) as CueFixture;
  const { text, runs } = fixtureTranscript(fixture);
  const rows = JSON.stringify(sharedRows(fixture), null, 1) + "\n";
  const kept = new URL(`transcripts/${name}.txt`, root);
  const keptRows = new URL(`expected/${name}.json`, root);
  if (out) {
    mkdirSync(out, { recursive: true });
    writeFileSync(`${out}/${name}.txt`, text);
  } else if (update) {
    mkdirSync(new URL("transcripts/", root), { recursive: true });
    mkdirSync(new URL("expected/", root), { recursive: true });
    writeFileSync(kept, text);
    writeFileSync(keptRows, rows);
  } else {
    const same = existsSync(kept) && readFileSync(kept, "utf8") === text && existsSync(keptRows) && readFileSync(keptRows, "utf8") === rows;
    if (!same) {
      changed++;
      console.log(`${name}: changed from the kept transcript (git diff after --update shows how)`);
    }
  }
  for (const run of runs) {
    for (const f of run.findings) {
      findings++;
      console.log(`${name} ${run.mph} mph: ${f.rule} at ${f.atM.toFixed(0)} m: ${f.words}`);
    }
  }
}
console.log(`${chosen.length} fixtures, ${findings} findings${update || out ? "" : `, ${changed} changed`}`);
process.exit(changed ? 1 : 0);
