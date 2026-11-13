// The rule against new source-text tests (frontend/TESTING.md): a test that reads App.tsx, RideMode.tsx, styles.css
// or another source file as text passes while the screen is broken and fails when working code is only reformatted.
// New tests render the component (testSupport/render.ts) instead. The files that still read source are listed in
// testSupport/sourceTextTests.txt, which only shrinks.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { readsSourceText, sourceTextTests } from "./testSupport/sourceTextGuard.mjs";

const SRC = new URL("./", import.meta.url);
const listed = readFileSync(new URL("./testSupport/sourceTextTests.txt", import.meta.url), "utf8")
  .split("\n")
  .filter((line) => line.trim() !== "" && !line.startsWith("#"));
const found = sourceTextTests(SRC);

test("no new test file reads the interface's source as text", () => {
  const added = found.filter((path) => !listed.includes(path));
  assert.deepEqual(added, [], "render the component instead (testSupport/render.ts, frontend/TESTING.md)");
});

test("a converted file comes off the list, so the list only shrinks", () => {
  const converted = listed.filter((path) => !found.includes(path));
  assert.deepEqual(converted, [], "delete these lines from testSupport/sourceTextTests.txt");
});

test("the guard sees the ways a test reads source, and not a test's own imports", () => {
  assert.ok(readsSourceText('const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");'));
  assert.ok(readsSourceText('const read = (p) => readFileSync(p, "utf8");\nread("../styles.css");'));
  assert.ok(readsSourceText('import { appSource } from "./testSupport/appSource.mjs";'));
  assert.ok(readsSourceText('const { readFile } = await import("node:fs/promises");\nawait readFile(new URL("../App.tsx", import.meta.url));'));
  assert.ok(readsSourceText('for (const name of readdirSync(srcDir)) if (/\\.tsx$/.test(name)) readFileSync(name);'));
  assert.ok(!readsSourceText('for (const name of readdirSync(FIXTURES)) readFileSync(new URL(name, FIXTURES));'), "a fixtures walk");
  assert.ok(!readsSourceText('import { readFileSync } from "node:fs";\nimport { x } from "./lib/x.ts";\nreadFileSync("../fixtures/a.json");'));
  assert.ok(!readsSourceText('import { render } from "./testSupport/render.ts";'));
});
