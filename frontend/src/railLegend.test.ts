// The rail stations' legend, on the panel in both themes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { contrastRatio } from "./stressStyle.js";

// The map's station icons are ringed for the light base map (stationIcons.ts);
// the legend's swatches sit on the panel, which is dark in the dark theme, so
// their ring is --rail-ring, set per theme in styles.css.
test("the legend's ring stands 3:1 off both panel themes", () => {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  const blocks = css.split("@media (prefers-color-scheme: dark)");
  const pick = (block: string, name: string) => block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1];
  for (const block of blocks.slice(0, 2)) {
    const bg = pick(block, "bg");
    const ring = pick(block, "rail-ring");
    assert.ok(bg && ring, "both themes set --bg and --rail-ring");
    assert.ok(contrastRatio(ring, bg) >= 3, `${ring} on ${bg}`);
  }
});
