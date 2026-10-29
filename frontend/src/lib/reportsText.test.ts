// Reports' text (P8): it leads with the phone's gesture on a phone, in short lines, and a computer keeps its right-click.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { STALE_DAYS, logHint } from "./report311Log.ts";
import { suggestHint } from "./sidebar.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const sentenceCount = (text: string) => (text.match(/[.?!](\s|$)/g) ?? []).length;

test("the 311 checklist's how-to: the ride's 311 button or holding a road, as three short lines", () => {
  assert.deepEqual(logHint(true), [
    "Log from a ride's 311 button or by holding a road.",
    "Copy the report into the site, then check it off.",
    `One left unchecked is archived after ${STALE_DAYS} days.`,
  ]);
  assert.match(logHint(false)[0], /right-clicking a road/);
  assert.doesNotMatch(logHint(true).join(" "), /click/i);
  const view = src("../Report311Log.tsx");
  assert.match(view, /<ul className="hint info-bullets">\s*\{logHint\(looksLikePhone\(\)\)\.map\(\(line\) => \(\s*<li key=\{line\}>\{line\}<\/li>/);
});

test("suggesting a change: press and hold on a phone, right-click on a computer, two sentences", () => {
  assert.match(suggestHint(true), /^Press and hold a road, then choose Suggest a change/);
  assert.doesNotMatch(suggestHint(true), /click/i);
  assert.match(suggestHint(false), /^Right-click a road, then choose Suggest a change/);
  for (const touch of [true, false]) assert.equal(sentenceCount(suggestHint(touch)), 2);
  assert.match(src("../app/Sheets.tsx"), /\{suggestHint\(looksLikePhone\(\)\)\}/);
});
