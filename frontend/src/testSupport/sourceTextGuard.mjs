// Which test files read the interface's own source as text (a .ts, .tsx, .css or .mjs file through readFileSync, or
// appSource.mjs's stitched App), for sourceTextTests.test.ts's guard. Kept here so the rule is one regular expression.
import { readFileSync, readdirSync, statSync } from "node:fs";

const SOURCE_PATH = /["'`][^"'`\n]*\.(?:tsx|ts|css|mjs)["'`]/;

/** The file's text without its import statements, whose paths name modules it runs, not text it reads. */
const withoutImports = (text) => text.replace(/\bfrom\s*["'][^"']*["']/g, "").replace(/\bimport\s*\(?\s*["'][^"']*["']/g, "");

/** Whether a test file's text reads source as text. */
export function readsSourceText(text) {
  return (text.includes("readFileSync") && SOURCE_PATH.test(withoutImports(text))) || /\bappSource\b/.test(text);
}

/** Every test file under `dir` (src/), as a path from src/, sorted. */
export function testFiles(dir, base = "") {
  const out = [];
  for (const name of readdirSync(new URL(base, dir))) {
    const path = `${base}${name}`;
    if (statSync(new URL(path, dir)).isDirectory()) out.push(...testFiles(dir, `${path}/`));
    else if (/\.test\.(?:ts|tsx|mjs)$/.test(name)) out.push(path);
  }
  return out.sort();
}

/** The test files under `dir` that read source as text (but the guard's own, whose examples would match). */
export function sourceTextTests(dir) {
  return testFiles(dir).filter((path) => path !== "sourceTextTests.test.ts" && readsSourceText(readFileSync(new URL(path, dir), "utf8")));
}
