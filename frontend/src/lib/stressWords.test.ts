// The legend's words are the owner's step words (OWNER-DECISIONS 441l, 441j; 460.8-11), the ones the road
// panel and its editor use (core/segment_info.py TIER_WORDS), so no surface says a level two ways.
import { test } from "node:test";
import assert from "node:assert/strict";
import { currentTiers } from "../stressStyle.js";
import { StressLegend } from "./stressLegend.ts";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

const WORDS: Record<number, string> = {
  1: "Comfortable for everyone",
  2: "Fine for adults",
  3: "For experienced cyclists",
  4: "High stress: busy, fast traffic",
  5: "Avoid",
};

test("each level of the legend carries the owner's words for it", () => {
  const tiers = currentTiers() as Array<{ tier: number; label: string }>;
  assert.deepEqual(
    tiers.map((t) => [t.tier, t.label]),
    Object.entries(WORDS).map(([tier, label]) => [Number(tier), label]),
  );
});

test("the legend says Avoid once, not as a name and again as its description", () => {
  const html = renderToStaticMarkup(createElement(StressLegend, { facilities: new Set(), zoom: 14, shown: true }));
  assert.ok(html.includes("Fine for adults"));
  assert.ok(html.includes("High stress: busy, fast traffic"));
  assert.ok(!html.includes("Comfortable for most"));
  assert.ok(!html.includes("For confident riders"));
  assert.ok(!html.includes("best avoided</span>"));
  assert.equal((html.match(/>Avoid</g) ?? []).length, 1);
});
