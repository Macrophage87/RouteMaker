// The rider-facing page on how traffic-stress ratings work (OWNER-DECISIONS 461): a static page in
// public/, served by both edges at STRESS_PAGE. Its structure is held here; the browser a11y suite
// (scripts/a11y/check.mjs) checks it at 320 px.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { STRESS_PAGE } from "./stressLegend.ts";

// The road panel's words for each level (src/core/segment_info.py, TIER_WORDS; OWNER-DECISIONS 441l).
const PANEL_WORDS = [
  "Comfortable for everyone",
  "Fine for adults",
  "For experienced cyclists",
  "High stress: busy, fast traffic",
  "Avoid",
];

const page = readFileSync(new URL(`../../public${STRESS_PAGE}`, import.meta.url), "utf8");
const text = page.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("the page is a whole document in English, with a title and a viewport", () => {
  assert.match(page, /^<!doctype html>\n<html lang="en">/);
  assert.match(page, /<title>[^<]+<\/title>/);
  assert.match(page, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
});

test("it runs no script and loads nothing from another host (the app's content security policy)", () => {
  assert.doesNotMatch(page, /<script/i);
  assert.doesNotMatch(page, /\b(src|href)="(https?:)?\/\//i);
  assert.doesNotMatch(page, /@import|url\(/i);
});

test("one h1, and no heading skips a level", () => {
  const levels = [...page.matchAll(/<h([1-6])[\s>]/g)].map((m) => Number(m[1]));
  assert.equal(levels.filter((l) => l === 1).length, 1);
  assert.equal(levels[0], 1);
  for (let i = 1; i < levels.length; i++) assert.ok(levels[i] <= levels[i - 1] + 1, `h${levels[i - 1]} then h${levels[i]}`);
});

test("it has the landmarks a screen reader moves by, and a skip link to the content", () => {
  for (const tag of ["header", "nav", "main", "footer"]) assert.match(page, new RegExp(`<${tag}[\\s>]`), tag);
  assert.match(page, /<a class="skip" href="#main">/);
  assert.match(page, /<main id="main">/);
  for (const [, id] of page.matchAll(/href="#([^"]+)"/g)) assert.match(page, new RegExp(`id="${id}"`), `#${id}`);
});

// Each level's map colors in words, pinned verbatim (the mutation re-check's N6b).
const MAP_WORDS = [
  "On the map: a thin, solid light green line with a dark green edge.",
  "On the map: long green dashes with a dark blue edge.",
  "On the map: short yellow dashes on orange, with a black edge.",
  "On the map: very long orange dashes on red, with a black edge, in a wider line.",
  "On the map: red dashes and dots on black, the widest line.",
];

test("every swatch is hidden from a screen reader, and each level is named in the road panel's words beside it", () => {
  const swatches = [...page.matchAll(/<svg[^>]*>/g)].map((m) => m[0]);
  assert.equal(swatches.length, 5);
  for (const svg of swatches) assert.match(svg, /aria-hidden="true"/);
  for (const words of PANEL_WORDS) assert.ok(text.includes(words), words);
});

test("each level is said whole, with a stop after its name, the legend's words marked, and its map color in words", () => {
  const items = [...page.matchAll(/<li>\s*<svg[\s\S]*?<\/svg>\s*<span>([\s\S]*?)<\/span>\s*<\/li>/g)].map((m) => m[1]);
  assert.equal(items.length, 5);
  items.forEach((item, i) => {
    const name = item.match(/^<strong>([^<]+)<\/strong> /)?.[1] ?? "";
    assert.ok(name.endsWith(`${PANEL_WORDS[i]}.`), name);
    assert.match(item, /<\/strong> Map legend: "/, "the legend's words are labelled as such");
    // The accessibility review's SF2: the color of each swatch in words, for a pilot's "the orange one".
    assert.ok(item.endsWith(MAP_WORDS[i]), `${i}: ${item}`);
    assert.match(item, /On the map: [^.]*\b(green|blue|yellow|orange|red|black)\b[^.]*\.$/, item);
  });
  assert.match(text, /The High contrast switch/, "the control's own label (accessibilitySwitch.ts)");
  assert.doesNotMatch(text, /accessibility switch/i, "Accessibility mode (455) does not change the colors");
});

test("closed ways: rated singletrack everywhere, other mountain-bike trails open on Gravel and Mountain Goat (presets.OFFROAD_PRESETS)", () => {
  assert.match(text, /rated mountain-bike singletrack/);
  assert.match(text, /Other natural-surface mountain-bike trails are closed on most ride types\. They are open on Gravel and Mountain Goat\./);
  assert.doesNotMatch(text, /mountain-bike-only trails/);
});

test("the cost table: one short-named region, a short caption, and LTS 1 and 2 said once above it", () => {
  assert.doesNotMatch(page, /<section [^>]*aria-labelledby/, "plain sections: the h2s give the headings, not 10 more regions");
  const regions = [...page.matchAll(/<div [^>]*role="region"[^>]*>/g)].map((m) => m[0]);
  assert.deepEqual(regions, ['<div class="table-wrap" tabindex="0" role="region" aria-label="Cost table, scrolls sideways">']);
  assert.match(page, /<caption>Calm miles per mile, at each ride type's starting slider<\/caption>/);
  assert.match(text, /Their level adds nothing at LTS 1 or 2\. A quiet street counts as 1\./);
  assert.match(text, /Traffic-free paths and protected bike lanes count for less \(except on Mass Ride\)/);
  assert.doesNotMatch(text, /always count as about 1/);
  // The LTS 4 hold is one combined figure against the router's first route (the spec re-check's R2).
  assert.match(text, /more LTS 4, Avoid and very high stress crossings, counted together, than the router's own first route/);
  assert.doesNotMatch(page, /<th scope="col">LTS 1 and 2<\/th>/);
});

test("it says where it differs from the literature, and links the full list", () => {
  assert.match(page, /<h2 id="why-differ">Sources and why we differ<\/h2>/);
  assert.match(text, /docs\/stress\/literature\.md/);
  assert.match(text, /We add an Avoid level/);
});

test("US units first, metric in brackets", () => {
  assert.match(text, /1 mile \[1\.6 km\]/);
  assert.match(text, /1,200 feet \[370 m\]/);
  assert.doesNotMatch(text, /\b\d+ (m|km)\b(?![^[]*\])/, "a metric figure outside brackets");
  // And every US figure has its metric (the accessibility review's N6): "20 mph" alone fails.
  const figures = [...text.matchAll(/\b\d[\d,.]*(?: to \d[\d,.]*)? (?:extra )?(?:mph|feet|miles?)\b(.{0,2})/g)];
  assert.ok(figures.length >= 8, String(figures.length));
  for (const m of figures) assert.equal(m[1], " [", `metric missing after "${m[0]}"`);
});

test("US spelling, as the app's own text", () => {
  assert.doesNotMatch(text, /colour|neighbour|behaviour|centre|metre/i);
});

test("the sources are credited in text", () => {
  for (const credit of [
    "OpenStreetMap contributors",
    "DC Open Data",
    "VDOT",
    "Montgomery County Planning Department",
    "Open Baltimore",
    "U.S. Census Bureau",
    "Furth",
    "Broach, Dill and Gliebe",
    "Eugene",
    "RouteMaker Mass Ride model",
  ]) {
    assert.ok(text.includes(credit), credit);
  }
});

test("what is not built is marked planned", () => {
  assert.match(text, /Half steps and the stress chart \(planned\)/);
  assert.match(text, /Planned, not built yet\./);
});
