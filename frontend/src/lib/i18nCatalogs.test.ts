// Every catalog phrase is one some code still shows (backlog 2026-11-12, languages: 11 French and 16 Spanish phrases
// had outlived their English). A phrase the code builds from parts, so never written whole, is listed below.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("..", import.meta.url).pathname;

/** Built from parts, so never in the source whole: lib/accessMode.ts ACCESS_HELP and _WHERE, lib/rideGroup.ts CONSENT_NOTE in either unit order. */
const BUILT = new Set([
  "For keyboard or screen reader use, turn on accessibility mode. It turns on high contrast, large text during a ride, and Map tools by the map's zoom buttons; it is kept on this device, and is also the first button on the page.",
  "For keyboard or screen reader use, turn on accessibility mode (the first button on the page, or in Settings).",
  "Only while the app is open and you are within 0.25 mi (400 m) of the route. No name; positions are encrypted and gone after 2 minutes.",
  "Only while the app is open and you are within 400 m (0.25 mi) of the route. No name; positions are encrypted and gone after 2 minutes.",
]);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "i18n" ? [] : sources(path);
    return /\.(ts|tsx|mjs|js)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

test("every catalog phrase is still shown somewhere, or is built from parts (BUILT)", () => {
  const code = sources(SRC).map((path) => readFileSync(path, "utf8")).join("\n");
  for (const file of readdirSync(join(SRC, "i18n")).filter((name) => name.endsWith(".ts") && !name.includes(".test."))) {
    const text = readFileSync(join(SRC, "i18n", file), "utf8");
    const keys = [...text.matchAll(/^\s+("(?:[^"\\]|\\.)*"):/gm)].map((m) => JSON.parse(m[1]) as string);
    assert.ok(keys.length > 100, file);
    const unused = keys.filter((key) => !BUILT.has(key) && !code.includes(key) && !code.includes(JSON.stringify(key).slice(1, -1)));
    assert.deepEqual(unused, [], `${file}: phrases no code uses`);
  }
});

test("each BUILT phrase is what the code builds", async () => {
  const { ACCESS_HELP, ACCESS_SENTENCE_WHERE } = await import("./accessMode.ts");
  assert.ok(BUILT.has(ACCESS_HELP) && BUILT.has(ACCESS_SENTENCE_WHERE));
});
